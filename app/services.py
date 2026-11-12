"""
Camada de Serviços (Regras de Negócio) da MarketPulse API.

Responsabilidades:
- aplicar as regras do domínio de Varejo & E-commerce (catálogo, fechamento
  de pedido e ajuste de estoque);
- converter os modelos internos de persistência (database.py) nos DTOs do
  contrato (schemas.py), para que a estrutura do "banco" nunca vaze para o
  cliente (Abstração de Serviço);
- sinalizar falhas por meio de exceções de domínio.

Esta camada NÃO conhece HTTP (Baixo Acoplamento): ela não importa FastAPI nem
devolve status codes. Quem traduz as exceções abaixo para 404/400 é main.py.
"""

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional

from app import database
from app.database import ItemPedidoModel, PedidoModel, ProdutoModel
from app.schemas import (
    AjusteEstoqueDTO,
    AjusteEstoqueResponseDTO,
    CriarPedidoDTO,
    ItemDetalhadoDTO,
    PedidoDTO,
    ProdutoDTO,
    StatusPedido,
)


# ---------------------------------------------------------------------------
# Exceções de domínio
# ---------------------------------------------------------------------------

class ErroDominio(Exception):
    """Base das exceções de negócio. Carrega o código e a mensagem do erro padronizado."""

    codigo_erro: str = "ERRO_DOMINIO"

    def __init__(self, mensagem: str, codigo_erro: Optional[str] = None):
        super().__init__(mensagem)
        self.mensagem = mensagem
        if codigo_erro:
            self.codigo_erro = codigo_erro


class RecursoNaoEncontrado(ErroDominio):
    """O recurso solicitado não existe (main.py responde 404)."""


class RegraNegocioViolada(ErroDominio):
    """A operação fere uma regra do domínio (main.py responde 400)."""


class ProdutoNaoEncontrado(RecursoNaoEncontrado):
    codigo_erro = "PRODUTO_NAO_ENCONTRADO"

    def __init__(self, id_produto: str):
        super().__init__(f"O produto '{id_produto}' não existe no catálogo.")
        self.id_produto = id_produto


class PedidoNaoEncontrado(RecursoNaoEncontrado):
    codigo_erro = "PEDIDO_NAO_ENCONTRADO"

    def __init__(self, id_pedido: str):
        super().__init__(f"O pedido '{id_pedido}' não foi encontrado.")
        self.id_pedido = id_pedido


class EstoqueInsuficiente(RegraNegocioViolada):
    codigo_erro = "ESTOQUE_INSUFICIENTE"

    def __init__(self, produto: ProdutoModel, solicitado: int):
        super().__init__(
            f"Estoque insuficiente para '{produto.nome}' ({produto.id_produto}): "
            f"solicitado {solicitado}, disponível {produto.estoque_qtd}."
        )


class EstoqueNegativo(RegraNegocioViolada):
    codigo_erro = "ESTOQUE_NEGATIVO"

    def __init__(self, produto: ProdutoModel, ajuste: int):
        super().__init__(
            f"Ajuste inválido para '{produto.nome}' ({produto.id_produto}): "
            f"estoque atual {produto.estoque_qtd}, ajuste {ajuste} resultaria em "
            f"{produto.estoque_qtd + ajuste}. O estoque não pode ficar negativo."
        )


# ---------------------------------------------------------------------------
# Funções auxiliares (internas)
# ---------------------------------------------------------------------------

_CENTAVOS = Decimal("0.01")


def _dinheiro(valor: Decimal) -> float:
    """Arredonda para centavos (meio para cima) evitando erros de ponto flutuante."""
    return float(valor.quantize(_CENTAVOS, rounding=ROUND_HALF_UP))


def _obter_produto_ou_falhar(id_produto: str) -> ProdutoModel:
    produto = database.buscar_produto(id_produto)
    if produto is None:
        raise ProdutoNaoEncontrado(id_produto)
    return produto


def _produto_para_dto(produto: ProdutoModel) -> ProdutoDTO:
    return ProdutoDTO(
        id_produto=produto.id_produto,
        nome=produto.nome,
        categoria=produto.categoria,
        preco=produto.preco,
        estoque_qtd=produto.estoque_qtd,
    )


def _pedido_para_dto(pedido: PedidoModel) -> PedidoDTO:
    return PedidoDTO(
        id_pedido=pedido.id_pedido,
        cliente_id=pedido.cliente_id,
        itens_detalhados=[
            ItemDetalhadoDTO(
                produto_id=item.produto_id,
                nome_produto=item.nome_produto,
                quantidade=item.quantidade,
                preco_unitario=item.preco_unitario,
                subtotal=item.subtotal,
            )
            for item in pedido.itens
        ],
        valor_total=pedido.valor_total,
        status=StatusPedido(pedido.status),
        data_pedido=pedido.data_pedido,
    )


def _consolidar_itens(payload: CriarPedidoDTO) -> Dict[str, int]:
    """Soma as quantidades de um mesmo produto_id, mantendo a ordem da 1ª ocorrência."""
    quantidades: Dict[str, int] = {}
    for item in payload.itens:
        quantidades[item.produto_id] = quantidades.get(item.produto_id, 0) + item.quantidade
    return quantidades


# ---------------------------------------------------------------------------
# Casos de uso
# ---------------------------------------------------------------------------

def listar_catalogo(categoria: Optional[str] = None) -> List[ProdutoDTO]:
    """
    Retorna o catálogo, opcionalmente filtrado por categoria.

    O filtro não diferencia maiúsculas/minúsculas e ignora espaços nas pontas.
    Categoria vazia ("") é tratada como ausência de filtro. Uma categoria sem
    produtos não é erro: devolve lista vazia.
    """
    filtro = categoria.strip() if categoria else None
    return [_produto_para_dto(p) for p in database.listar_produtos(filtro or None)]


def fechar_pedido(payload: CriarPedidoDTO) -> PedidoDTO:
    """
    Fecha um pedido de compra de forma atômica.

    1. Consolida itens repetidos (soma as quantidades do mesmo produto).
    2. Verifica se TODOS os produtos existem -> ProdutoNaoEncontrado (404).
    3. Verifica se há estoque para TODOS os itens -> EstoqueInsuficiente (400).
    4. Só então decrementa o estoque, calcula os valores e grava o pedido com
       status PENDENTE_PAGAMENTO.

    Se qualquer validação falhar, nenhum estoque é alterado. O lock garante
    que duas requisições simultâneas não vendam a mesma unidade.
    """
    quantidades = _consolidar_itens(payload)

    with database.lock_estoque:
        # Etapa 1: existência (404 tem prioridade sobre 400)
        produtos: Dict[str, ProdutoModel] = {
            id_produto: _obter_produto_ou_falhar(id_produto) for id_produto in quantidades
        }

        # Etapa 2: disponibilidade de estoque
        for id_produto, quantidade in quantidades.items():
            produto = produtos[id_produto]
            if quantidade > produto.estoque_qtd:
                raise EstoqueInsuficiente(produto, quantidade)

        # Etapa 3: efetivação (só chega aqui se tudo for válido)
        itens: List[ItemPedidoModel] = []
        total = Decimal("0")
        for id_produto, quantidade in quantidades.items():
            produto = produtos[id_produto]
            preco = Decimal(str(produto.preco))
            subtotal = preco * quantidade
            total += subtotal
            itens.append(
                ItemPedidoModel(
                    produto_id=produto.id_produto,
                    nome_produto=produto.nome,
                    quantidade=quantidade,
                    preco_unitario=_dinheiro(preco),
                    subtotal=_dinheiro(subtotal),
                )
            )
            database.atualizar_estoque(id_produto, produto.estoque_qtd - quantidade)

        pedido = PedidoModel(
            id_pedido=database.gerar_id_pedido(),
            cliente_id=payload.cliente_id,
            itens=itens,
            valor_total=_dinheiro(total),
            status=StatusPedido.PENDENTE_PAGAMENTO.value,
            forma_pagamento=payload.forma_pagamento,
            data_pedido=datetime.now(timezone.utc).replace(microsecond=0),
        )
        database.salvar_pedido(pedido)

    return _pedido_para_dto(pedido)


def obter_pedido(id_pedido: str) -> PedidoDTO:
    """Retorna o resumo de um pedido ou lança PedidoNaoEncontrado (404)."""
    pedido = database.buscar_pedido(id_pedido)
    if pedido is None:
        raise PedidoNaoEncontrado(id_pedido)
    return _pedido_para_dto(pedido)


def ajustar_estoque(id_produto: str, payload: AjusteEstoqueDTO) -> AjusteEstoqueResponseDTO:
    """
    Aplica um ajuste ao estoque de um produto.

    - Positivo: entrada/reposição.  Negativo: baixa manual.  Zero: aceito, sem alteração.
    - Lança ProdutoNaoEncontrado (404) se o produto não existir.
    - Lança EstoqueNegativo (400) se o saldo final ficar abaixo de zero.
    """
    with database.lock_estoque:
        produto = _obter_produto_ou_falhar(id_produto)
        ajuste = payload.quantidade_adicional
        novo_estoque = produto.estoque_qtd + ajuste
        if novo_estoque < 0:
            raise EstoqueNegativo(produto, ajuste)
        database.atualizar_estoque(id_produto, novo_estoque)

    return AjusteEstoqueResponseDTO(
        id_produto=produto.id_produto,
        nome=produto.nome,
        estoque_anterior=produto.estoque_qtd,
        estoque_atualizado=novo_estoque,
    )
