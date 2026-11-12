# MarketPulse API — Varejo & E-commerce

API RESTful da rede **MarketPulse Varejo** para consulta de catálogo, fechamento de pedidos de compra e ajuste de estoque.

Projeto Extraclasse — **Prática 3 (Marco 1)** da disciplina *Computação em Nuvem e Arquitetura Orientada a Serviços (SOA)*, Bacharelado em Ciência da Computação (7º Período), IFPA Campus Ananindeua. Prof. M.Sc. Fábio Ferreira.

**Domínio 3 — Varejo & E-commerce**

## Equipe

| Integrante | Responsabilidade |
|---|---|
| Luiz Vitor | Camada de persistência (`app/database.py`), estrutura do projeto e README |
| Mateus Souza | Contrato do serviço / DTOs (`app/schemas.py`) |
| Ricardo Silva | Regras de negócio (`app/services.py`) e testes automatizados (`tests/`) |
| Samuel Amoras | Endpoints e tratamento de erros (`app/main.py`) e coleção do Postman |

## Tecnologias

- Python 3.10+
- FastAPI (Swagger UI / OpenAPI automático)
- Pydantic v2 (DTOs)
- Uvicorn (servidor ASGI)
- Persistência em memória

## Arquitetura em camadas

```
MarketPulse-API/
├── app/
│   ├── __init__.py
│   ├── main.py        # Camada web: rotas, status codes e tratamento de exceções
│   ├── schemas.py     # DTOs de entrada, saída e erro (contrato do serviço)
│   ├── services.py    # Regras de negócio e validações do domínio
│   └── database.py    # Persistência em memória (repositório)
├── tests/
│   ├── conftest.py        # Fixtures (base reiniciada a cada teste, TestClient)
│   ├── test_api.py        # Testes de ponta a ponta dos 4 endpoints (HTTP)
│   └── test_services.py   # Testes unitários das regras de negócio (sem HTTP)
├── MarketPulse-API-Collection.postman_collection.json
├── requirements.txt
└── README.md
```

Fluxo de uma requisição: `main.py` → `services.py` → `database.py`. As rotas só recebem e devolvem DTOs de `schemas.py`. A camada de serviços não conhece HTTP: ela lança exceções de domínio, que `main.py` traduz para status codes.

## Princípios SOA aplicados (Thomas Erl)

| Princípio | Como foi aplicado |
|---|---|
| **Contrato Padronizado** | Todo payload passa por DTOs Pydantic. Campos extras são recusados (`extra="forbid"`). Todos os erros seguem o formato único `{codigo_erro, mensagem, timestamp}`. |
| **Baixo Acoplamento** | Camadas separadas. A regra de negócio lança exceções de domínio e não depende do FastAPI. A persistência é acessada só por funções de repositório. |
| **Abstração de Serviço** | Os modelos internos de persistência (dataclasses em `database.py`) são diferentes dos DTOs e nunca são expostos. Não há *Abstraction Leakage*. |
| **Statelessness** | Não há sessão de usuário. Cada requisição traz no payload e nos parâmetros tudo o que precisa para ser processada. |

## Como executar localmente

```bash
# 1. Clonar o repositório
git clone https://github.com/luizvitorxvz/MarketPulse-API.git
cd MarketPulse-API

# 2. Criar e ativar o ambiente virtual
python -m venv venv
# Linux/macOS:
source venv/bin/activate
# Windows:
venv\Scripts\activate

# 3. Instalar dependências
pip install -r requirements.txt

# 4. Subir a API
uvicorn app.main:app --reload
```

- API: http://localhost:8000
- **Swagger UI:** http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

> Os dados ficam em memória: a cada reinício da API o catálogo volta ao estado inicial e os pedidos são apagados.

## Endpoints

| # | Verbo | Rota | Sucesso | Erros |
|---|---|---|---|---|
| 1 | GET | `/api/v1/produtos?categoria=` | 200: lista de produtos | — |
| 2 | POST | `/api/v1/pedidos` | 201: `PedidoDTO` | 404 produto inexistente · 400 estoque insuficiente ou payload inválido |
| 3 | GET | `/api/v1/pedidos/{id_pedido}` | 200: `PedidoDTO` | 404 pedido inexistente |
| 4 | PATCH | `/api/v1/produtos/{id_produto}/estoque` | 200: estoque anterior e atualizado | 404 produto inexistente · 400 estoque negativo |

### Exemplo: fechar pedido

```http
POST /api/v1/pedidos
Content-Type: application/json

{
  "cliente_id": "CLI-0042",
  "itens": [
    {"produto_id": "PROD-101", "quantidade": 2},
    {"produto_id": "PROD-202", "quantidade": 1}
  ],
  "forma_pagamento": "PIX"
}
```

Resposta `201 Created`:

```json
{
  "id_pedido": "PED-2026-001",
  "cliente_id": "CLI-0042",
  "itens_detalhados": [
    {"produto_id": "PROD-101", "nome_produto": "Mouse Sem Fio", "quantidade": 2, "preco_unitario": 89.9, "subtotal": 179.8},
    {"produto_id": "PROD-202", "nome_produto": "Fone Bluetooth TWS", "quantidade": 1, "preco_unitario": 159.9, "subtotal": 159.9}
  ],
  "valor_total": 339.7,
  "status": "PENDENTE_PAGAMENTO",
  "data_pedido": "2026-11-10T14:30:00Z"
}
```

### Formato padronizado de erro

```json
{
  "codigo_erro": "ESTOQUE_INSUFICIENTE",
  "mensagem": "Estoque insuficiente para 'Headset Gamer USB' (PROD-103): solicitado 999, disponível 5.",
  "timestamp": "2026-11-05T14:30:00Z"
}
```

| `codigo_erro` | Status | Quando ocorre |
|---|---|---|
| `PRODUTO_NAO_ENCONTRADO` | 404 | `produto_id` / `id_produto` não existe |
| `PEDIDO_NAO_ENCONTRADO` | 404 | `id_pedido` não existe |
| `ESTOQUE_INSUFICIENTE` | 400 | Quantidade pedida maior que o estoque |
| `ESTOQUE_NEGATIVO` | 400 | Ajuste deixaria o estoque abaixo de zero |
| `REQUISICAO_INVALIDA` | 400 | Payload malformado, campo faltando ou valor fora do contrato |
| `ROTA_NAO_ENCONTRADA` | 404 | URL inexistente |
| `METODO_NAO_PERMITIDO` | 405 | Verbo HTTP não suportado na rota |
| `ERRO_INTERNO` | 500 | Falha inesperada (sem expor stack trace) |

## Regras de negócio e decisões de projeto

- **Status inicial do pedido:** `PENDENTE_PAGAMENTO`. Máquina de estados: PENDENTE_PAGAMENTO ➔ PAGO ➔ ENVIADO (ou CANCELADO).
- **Fechamento atômico:** a API primeiro valida *todos* os itens (existência e estoque). Só se todos forem válidos ela decrementa o estoque e cria o pedido. Se um item falhar, nenhum estoque é alterado.
- **Ordem de validação:** produto inexistente (404) é verificado antes de estoque insuficiente (400).
- **Itens repetidos:** o mesmo `produto_id` informado mais de uma vez tem as quantidades somadas.
- **Filtro de categoria:** não diferencia maiúsculas e minúsculas. Categoria sem produtos retorna `[]` com 200 OK.
- **Ajuste de estoque:** valor positivo é entrada, negativo é baixa manual e zero é aceito sem alterar o estoque. Se o resultado ficar negativo, a API responde 400.
- **Validação de payload:** o 422 padrão do FastAPI é convertido em **400 Bad Request** no formato padronizado.

## Catálogo inicial

| ID | Produto | Categoria | Preço | Estoque |
|---|---|---|---|---|
| PROD-101 | Mouse Sem Fio | PERIFERICOS | 89,90 | 15 |
| PROD-102 | Teclado Mecânico ABNT2 | PERIFERICOS | 249,90 | 8 |
| PROD-103 | Headset Gamer USB | PERIFERICOS | 199,00 | 5 |
| PROD-201 | Smartphone Android 128GB | ELETRONICOS | 1.499,00 | 10 |
| PROD-202 | Fone Bluetooth TWS | ELETRONICOS | 159,90 | 20 |
| PROD-203 | Smartwatch Fitness | ELETRONICOS | 349,90 | 0 |
| PROD-301 | Monitor LED 24 Full HD | INFORMATICA | 799,00 | 6 |
| PROD-302 | SSD NVMe 1TB | INFORMATICA | 459,90 | 12 |

## Testes

### Postman

1. Suba a API (`uvicorn app.main:app --reload`).
2. No Postman: **Import** → `MarketPulse-API-Collection.postman_collection.json`.
3. Rode a coleção pelo **Collection Runner**, na ordem. A variável `{{idPedido}}` é preenchida automaticamente pelo pedido criado.

A coleção tem 14 requisições com casos de sucesso (200/201) e de erro (400/404) dos 4 endpoints, e cada uma tem scripts de verificação.

### Testes automatizados (pytest)

```bash
pip install pytest httpx2
pytest -v
```
