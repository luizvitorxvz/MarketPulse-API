"""
Camada de Contrato (DTOs / Schemas) da MarketPulse API.

Todos os payloads de entrada e saída da API passam por estas classes.
Elas formam o Contrato Padronizado do serviço (Thomas Erl) e isolam o
cliente da camada de persistência, evitando o Abstraction Leakage:
nenhuma rota recebe ou devolve dicionários soltos ou estruturas do banco.
"""

from datetime import datetime
from enum import Enum
from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Configuração base
# ---------------------------------------------------------------------------

class DTOEntrada(BaseModel):
    """Base dos DTOs de entrada: recusa campos não previstos no contrato."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# Enumerações do domínio
# ---------------------------------------------------------------------------

class StatusPedido(str, Enum):
    """
    Máquina de estados do pedido:
    PENDENTE_PAGAMENTO -> PAGO -> ENVIADO (ou CANCELADO).
    """

    PENDENTE_PAGAMENTO = "PENDENTE_PAGAMENTO"
    PAGO = "PAGO"
    ENVIADO = "ENVIADO"
    CANCELADO = "CANCELADO"


FormaPagamento = Literal["PIX", "CARTAO", "BOLETO"]


# ---------------------------------------------------------------------------
# DTOs de ENTRADA (Request)
# ---------------------------------------------------------------------------

class ItemPedidoDTO(DTOEntrada):
    """Item solicitado dentro de um pedido."""

    produto_id: str = Field(
        ..., min_length=1, description="Identificador do produto",
        examples=["PROD-101"],
    )
    quantidade: int = Field(
        ..., gt=0, description="Quantidade solicitada (inteiro maior que zero)",
        examples=[2],
    )


class CriarPedidoDTO(DTOEntrada):
    """Payload do POST /api/v1/pedidos."""

    cliente_id: str = Field(
        ..., min_length=1, description="Identificador do cliente",
        examples=["CLI-0042"],
    )
    itens: List[ItemPedidoDTO] = Field(
        ..., min_length=1, description="Lista de itens do pedido (ao menos um)",
    )
    forma_pagamento: FormaPagamento = Field(
        ..., description="Forma de pagamento: PIX, CARTAO ou BOLETO",
        examples=["PIX"],
    )

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [
                {
                    "cliente_id": "CLI-0042",
                    "itens": [
                        {"produto_id": "PROD-101", "quantidade": 2},
                        {"produto_id": "PROD-201", "quantidade": 1},
                    ],
                    "forma_pagamento": "PIX",
                }
            ]
        },
    )


class AjusteEstoqueDTO(DTOEntrada):
    """Payload do PATCH /api/v1/produtos/{id_produto}/estoque."""

    quantidade_adicional: int = Field(
        ...,
        description="Positivo para entrada (reposição) ou negativo para baixa manual",
        examples=[10],
    )


# ---------------------------------------------------------------------------
# DTOs de SAÍDA (Response)
# ---------------------------------------------------------------------------

class ProdutoDTO(BaseModel):
    """Produto do catálogo."""

    id_produto: str = Field(..., examples=["PROD-101"])
    nome: str = Field(..., examples=["Mouse Sem Fio"])
    categoria: str = Field(..., examples=["PERIFERICOS"])
    preco: float = Field(..., examples=[89.90])
    estoque_qtd: int = Field(..., examples=[15])


class ItemDetalhadoDTO(BaseModel):
    """Item do pedido já calculado pelo serviço."""

    produto_id: str = Field(..., examples=["PROD-101"])
    nome_produto: str = Field(..., examples=["Mouse Sem Fio"])
    quantidade: int = Field(..., examples=[2])
    preco_unitario: float = Field(..., examples=[89.90])
    subtotal: float = Field(..., examples=[179.80])


class PedidoDTO(BaseModel):
    """Resumo completo de um pedido."""

    id_pedido: str = Field(..., examples=["PED-2026-771"])
    cliente_id: str = Field(..., examples=["CLI-0042"])
    itens_detalhados: List[ItemDetalhadoDTO]
    valor_total: float = Field(..., examples=[179.80])
    status: StatusPedido = Field(..., examples=["PENDENTE_PAGAMENTO"])
    data_pedido: datetime = Field(..., examples=["2026-11-10T14:30:00Z"])


class AjusteEstoqueResponseDTO(BaseModel):
    """Resultado de um ajuste de estoque."""

    id_produto: str = Field(..., examples=["PROD-101"])
    nome: str = Field(..., examples=["Mouse Sem Fio"])
    estoque_anterior: int = Field(..., examples=[10])
    estoque_atualizado: int = Field(..., examples=[25])


# ---------------------------------------------------------------------------
# DTO de ERRO padronizado
# ---------------------------------------------------------------------------

class ErroPadronizadoDTO(BaseModel):
    """Formato único de erro exigido pela ficha para todas as respostas 4xx/5xx."""

    codigo_erro: str = Field(..., examples=["PRODUTO_NAO_ENCONTRADO"])
    mensagem: str = Field(
        ..., examples=["O produto 'PROD-999' não existe no catálogo."]
    )
    timestamp: str = Field(..., examples=["2026-11-05T14:30:00Z"])
