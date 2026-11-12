"""
Camada Web (Controller) da MarketPulse API.

Responsabilidades:
- expor os 4 endpoints RESTful da ficha do Domínio 3 (Varejo & E-commerce);
- delegar todo o processamento à camada de serviços (services.py);
- traduzir exceções em Status Codes HTTP semânticos com JSON de erro padronizado;
- publicar a documentação OpenAPI interativa em /docs (Swagger UI).

Execução local:  uvicorn app.main:app --reload
"""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import services
from app.schemas import (
    AjusteEstoqueDTO,
    AjusteEstoqueResponseDTO,
    CriarPedidoDTO,
    ErroPadronizadoDTO,
    PedidoDTO,
    ProdutoDTO,
)

app = FastAPI(
    title="MarketPulse API — Varejo & E-commerce",
    description=(
        "Web Service RESTful da rede **MarketPulse Varejo** para consulta de catálogo, "
        "fechamento de pedidos de compra e ajuste de estoque.\n\n"
        "**Máquina de estados do pedido:** PENDENTE_PAGAMENTO ➔ PAGO ➔ ENVIADO (ou CANCELADO).\n\n"
        "Todos os erros seguem o formato padronizado "
        "`{codigo_erro, mensagem, timestamp}`."
    ),
    version="1.0.0",
    openapi_tags=[
        {"name": "Produtos", "description": "Catálogo e controle de estoque"},
        {"name": "Pedidos", "description": "Fechamento e consulta de pedidos"},
    ],
)


# ---------------------------------------------------------------------------
# Tratamento de exceções -> JSON de erro padronizado
# ---------------------------------------------------------------------------

def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resposta_erro(status_code: int, codigo_erro: str, mensagem: str) -> JSONResponse:
    corpo = ErroPadronizadoDTO(
        codigo_erro=codigo_erro, mensagem=mensagem, timestamp=_agora_iso()
    )
    return JSONResponse(status_code=status_code, content=corpo.model_dump())


@app.exception_handler(services.RecursoNaoEncontrado)
async def tratar_nao_encontrado(_: Request, exc: services.RecursoNaoEncontrado):
    return _resposta_erro(status.HTTP_404_NOT_FOUND, exc.codigo_erro, exc.mensagem)


@app.exception_handler(services.RegraNegocioViolada)
async def tratar_regra_violada(_: Request, exc: services.RegraNegocioViolada):
    return _resposta_erro(status.HTTP_400_BAD_REQUEST, exc.codigo_erro, exc.mensagem)


@app.exception_handler(RequestValidationError)
async def tratar_validacao(_: Request, exc: RequestValidationError):
    """Converte o 422 padrão do FastAPI/Pydantic em 400 Bad Request padronizado."""
    detalhes = []
    for erro in exc.errors():
        if erro.get("type") == "json_invalid":
            detalhes.append("corpo da requisição não é um JSON válido")
            continue
        campo = ".".join(str(p) for p in erro.get("loc", []) if p != "body")
        detalhes.append(f"{campo or 'corpo'}: {erro.get('msg')}")
    mensagem = "Requisição inválida. " + "; ".join(detalhes)
    return _resposta_erro(status.HTTP_400_BAD_REQUEST, "REQUISICAO_INVALIDA", mensagem)


@app.exception_handler(StarletteHTTPException)
async def tratar_http(_: Request, exc: StarletteHTTPException):
    """Rotas inexistentes (404), verbo não permitido (405) etc. também no formato padrão."""
    codigos = {404: "ROTA_NAO_ENCONTRADA", 405: "METODO_NAO_PERMITIDO"}
    return _resposta_erro(
        exc.status_code, codigos.get(exc.status_code, "ERRO_HTTP"), str(exc.detail)
    )


@app.exception_handler(Exception)
async def tratar_erro_inesperado(_: Request, __: Exception):
    """Nunca expõe stack trace ao cliente."""
    return _resposta_erro(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "ERRO_INTERNO",
        "Ocorreu um erro inesperado ao processar a requisição.",
    )


ERRO_400 = {"model": ErroPadronizadoDTO, "description": "Requisição inválida ou regra de negócio violada"}
ERRO_404 = {"model": ErroPadronizadoDTO, "description": "Recurso não encontrado"}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def raiz():
    return RedirectResponse(url="/docs")


@app.get(
    "/api/v1/produtos",
    response_model=List[ProdutoDTO],
    status_code=status.HTTP_200_OK,
    responses={400: ERRO_400},
    summary="Consultar catálogo de produtos",
    tags=["Produtos"],
)
def consultar_catalogo(
    categoria: Optional[str] = Query(
        None,
        description="Filtra por categoria (ex: PERIFERICOS, ELETRONICOS, INFORMATICA). "
        "Não diferencia maiúsculas/minúsculas.",
        examples=["PERIFERICOS"],
    ),
):
    """
    Retorna o catálogo de produtos com preço e quantidade em estoque.

    - Sem filtro: todos os produtos.
    - Categoria sem produtos: lista vazia `[]` (200 OK).
    """
    return services.listar_catalogo(categoria)


@app.post(
    "/api/v1/pedidos",
    response_model=PedidoDTO,
    status_code=status.HTTP_201_CREATED,
    responses={400: ERRO_400, 404: ERRO_404},
    summary="Processar e fechar pedido",
    tags=["Pedidos"],
)
def fechar_pedido(payload: CriarPedidoDTO):
    """
    Fecha um pedido de compra.

    1. Verifica se todos os produtos existem (**404** se algum não existir).
    2. Verifica se há estoque suficiente para cada item (**400** se faltar).
    3. Se tudo estiver válido, decrementa o estoque e cria o pedido com status
       `PENDENTE_PAGAMENTO` (**201**).

    A operação é atômica: se qualquer item falhar, nenhum estoque é alterado.
    """
    return services.fechar_pedido(payload)


@app.get(
    "/api/v1/pedidos/{id_pedido}",
    response_model=PedidoDTO,
    status_code=status.HTTP_200_OK,
    responses={404: ERRO_404},
    summary="Detalhar resumo do pedido",
    tags=["Pedidos"],
)
def detalhar_pedido(id_pedido: str):
    """Retorna o resumo completo de um pedido pelo seu ID (ex: `PED-2026-001`)."""
    return services.obter_pedido(id_pedido)


@app.patch(
    "/api/v1/produtos/{id_produto}/estoque",
    response_model=AjusteEstoqueResponseDTO,
    status_code=status.HTTP_200_OK,
    responses={400: ERRO_400, 404: ERRO_404},
    summary="Reposição/ajuste de estoque",
    tags=["Produtos"],
)
def ajustar_estoque(id_produto: str, payload: AjusteEstoqueDTO):
    """
    Ajusta o estoque de um produto.

    - `quantidade_adicional` positiva: entrada/reposição.
    - `quantidade_adicional` negativa: baixa manual.
    - **400** se o ajuste resultar em estoque negativo; **404** se o produto não existir.
    """
    return services.ajustar_estoque(id_produto, payload)
