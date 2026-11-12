"""
Testes unitários da camada de serviços (regras de negócio), sem HTTP.

Mostram que services.py funciona isolado do FastAPI (Baixo Acoplamento):
as falhas são exceções de domínio, e não status codes.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from app import database, services
from app.schemas import AjusteEstoqueDTO, CriarPedidoDTO, PedidoDTO, ProdutoDTO


def novo_pedido(*itens, forma_pagamento="PIX"):
    return CriarPedidoDTO(
        cliente_id="CLI-0042",
        itens=[{"produto_id": p, "quantidade": q} for p, q in itens],
        forma_pagamento=forma_pagamento,
    )


def test_listar_catalogo_devolve_dtos():
    produtos = services.listar_catalogo()
    assert len(produtos) == 8
    assert all(isinstance(p, ProdutoDTO) for p in produtos)


def test_listar_catalogo_ignora_espacos_e_maiusculas():
    assert len(services.listar_catalogo("  informatica ")) == 2


def test_listar_catalogo_categoria_vazia_nao_filtra():
    assert len(services.listar_catalogo("")) == 8


def test_fechar_pedido_devolve_dto_e_grava():
    resultado = services.fechar_pedido(novo_pedido(("PROD-101", 2)))
    assert isinstance(resultado, PedidoDTO)
    assert resultado.status.value == "PENDENTE_PAGAMENTO"
    gravado = database.buscar_pedido(resultado.id_pedido)
    assert gravado is not None
    assert gravado.forma_pagamento == "PIX"


def test_produto_inexistente_lanca_excecao_de_dominio():
    with pytest.raises(services.ProdutoNaoEncontrado) as erro:
        services.fechar_pedido(novo_pedido(("PROD-999", 1)))
    assert isinstance(erro.value, services.RecursoNaoEncontrado)
    assert erro.value.codigo_erro == "PRODUTO_NAO_ENCONTRADO"


def test_estoque_insuficiente_lanca_excecao_de_dominio():
    with pytest.raises(services.EstoqueInsuficiente) as erro:
        services.fechar_pedido(novo_pedido(("PROD-103", 6)))
    assert isinstance(erro.value, services.RegraNegocioViolada)
    assert erro.value.codigo_erro == "ESTOQUE_INSUFICIENTE"


def test_pedido_inexistente_lanca_excecao_de_dominio():
    with pytest.raises(services.PedidoNaoEncontrado) as erro:
        services.obter_pedido("PED-0000-000")
    assert erro.value.codigo_erro == "PEDIDO_NAO_ENCONTRADO"


def test_estoque_negativo_lanca_excecao_de_dominio():
    with pytest.raises(services.EstoqueNegativo) as erro:
        services.ajustar_estoque("PROD-103", AjusteEstoqueDTO(quantidade_adicional=-6))
    assert isinstance(erro.value, services.RegraNegocioViolada)
    assert database.buscar_produto("PROD-103").estoque_qtd == 5


def test_alterar_dto_devolvido_nao_altera_a_base():
    produto = services.listar_catalogo("PERIFERICOS")[0]
    produto.estoque_qtd = 9999
    assert database.buscar_produto(produto.id_produto).estoque_qtd != 9999


def test_pedidos_concorrentes_nao_vendem_alem_do_estoque():
    """20 clientes disputam as 5 unidades do PROD-103 ao mesmo tempo: só 5 vendas passam."""

    def comprar(_):
        try:
            services.fechar_pedido(novo_pedido(("PROD-103", 1)))
            return True
        except services.EstoqueInsuficiente:
            return False

    with ThreadPoolExecutor(max_workers=20) as executor:
        resultados = list(executor.map(comprar, range(20)))

    assert resultados.count(True) == 5
    assert database.buscar_produto("PROD-103").estoque_qtd == 0


def test_ajustes_concorrentes_nao_perdem_atualizacoes():
    with ThreadPoolExecutor(max_workers=10) as executor:
        list(executor.map(
            lambda _: services.ajustar_estoque("PROD-101", AjusteEstoqueDTO(quantidade_adicional=1)),
            range(50),
        ))
    assert database.buscar_produto("PROD-101").estoque_qtd == 65
