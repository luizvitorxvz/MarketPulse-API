"""
Camada de Persistência da MarketPulse API (armazenamento em memória).

Os registros internos são modelados com dataclasses próprias da persistência,
diferentes dos DTOs de schemas.py. A conversão entre os dois mundos acontece na
camada de serviços: assim, a estrutura do "banco" nunca vaza para o contrato da
API (Abstração de Serviço / Baixo Acoplamento).

As demais camadas acessam os dados somente pelas funções de repositório
abaixo. Trocar esta implementação por SQLite/ORM no futuro não exige mudanças
em services.py nem em main.py.

Observação sobre Statelessness: estes dicionários representam o armazenamento
do serviço (equivalente a um banco de dados), e não estado de sessão do
cliente. Nenhuma requisição depende de informação guardada de uma requisição
anterior do mesmo usuário.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from itertools import count
from threading import Lock
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Modelos internos de persistência (NÃO são expostos pela API)
# ---------------------------------------------------------------------------

@dataclass
class ProdutoModel:
    id_produto: str
    nome: str
    categoria: str
    preco: float
    estoque_qtd: int


@dataclass
class ItemPedidoModel:
    produto_id: str
    nome_produto: str
    quantidade: int
    preco_unitario: float
    subtotal: float


@dataclass
class PedidoModel:
    id_pedido: str
    cliente_id: str
    itens: List[ItemPedidoModel]
    valor_total: float
    status: str
    forma_pagamento: str
    data_pedido: datetime


# ---------------------------------------------------------------------------
# Armazenamento em memória
# ---------------------------------------------------------------------------

_CATALOGO_INICIAL: List[ProdutoModel] = [
    ProdutoModel("PROD-101", "Mouse Sem Fio", "PERIFERICOS", 89.90, 15),
    ProdutoModel("PROD-102", "Teclado Mecânico ABNT2", "PERIFERICOS", 249.90, 8),
    ProdutoModel("PROD-103", "Headset Gamer USB", "PERIFERICOS", 199.00, 5),
    ProdutoModel("PROD-201", "Smartphone Android 128GB", "ELETRONICOS", 1499.00, 10),
    ProdutoModel("PROD-202", "Fone Bluetooth TWS", "ELETRONICOS", 159.90, 20),
    ProdutoModel("PROD-203", "Smartwatch Fitness", "ELETRONICOS", 349.90, 0),
    ProdutoModel("PROD-301", "Monitor LED 24 Full HD", "INFORMATICA", 799.00, 6),
    ProdutoModel("PROD-302", "SSD NVMe 1TB", "INFORMATICA", 459.90, 12),
]

_produtos: Dict[str, ProdutoModel] = {}
_pedidos: Dict[str, PedidoModel] = {}
_sequencia_pedidos = count(1)

# Lock usado pela camada de serviços para tornar o fechamento de pedido
# atômico (verificar estoque + decrementar sem interferência de requisições
# concorrentes, já que o FastAPI executa rotas síncronas em threads).
lock_estoque = Lock()


def inicializar_base() -> None:
    """(Re)carrega o catálogo inicial e limpa os pedidos."""
    global _sequencia_pedidos
    _produtos.clear()
    _pedidos.clear()
    for produto in _CATALOGO_INICIAL:
        _produtos[produto.id_produto] = deepcopy(produto)
    _sequencia_pedidos = count(1)


# ---------------------------------------------------------------------------
# Repositório de Produtos
# ---------------------------------------------------------------------------

def listar_produtos(categoria: Optional[str] = None) -> List[ProdutoModel]:
    """Lista produtos, opcionalmente filtrando por categoria (sem diferenciar maiúsculas)."""
    produtos = list(_produtos.values())
    if categoria:
        alvo = categoria.strip().upper()
        produtos = [p for p in produtos if p.categoria.upper() == alvo]
    return [deepcopy(p) for p in produtos]


def buscar_produto(id_produto: str) -> Optional[ProdutoModel]:
    """Retorna uma cópia do produto ou None se não existir."""
    produto = _produtos.get(id_produto)
    return deepcopy(produto) if produto else None


def atualizar_estoque(id_produto: str, novo_estoque: int) -> None:
    """Grava o novo saldo de estoque de um produto existente."""
    _produtos[id_produto].estoque_qtd = novo_estoque


# ---------------------------------------------------------------------------
# Repositório de Pedidos
# ---------------------------------------------------------------------------

def gerar_id_pedido() -> str:
    """Gera IDs no formato da ficha: PED-<ANO>-<SEQUENCIAL>, ex: PED-2026-001."""
    ano = datetime.now().year
    return f"PED-{ano}-{next(_sequencia_pedidos):03d}"


def salvar_pedido(pedido: PedidoModel) -> None:
    _pedidos[pedido.id_pedido] = deepcopy(pedido)


def buscar_pedido(id_pedido: str) -> Optional[PedidoModel]:
    pedido = _pedidos.get(id_pedido)
    return deepcopy(pedido) if pedido else None


# Carrega os dados ao importar o módulo
inicializar_base()
