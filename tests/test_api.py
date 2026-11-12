"""
Testes automatizados de ponta a ponta (HTTP) da MarketPulse API.

Cobrem os 4 endpoints da ficha com casos de sucesso e de erro, o formato
padronizado de erro e as regras de negócio (atomicidade, ordem de validação,
itens repetidos e ajuste de estoque).

Execução:  pytest -v
"""

from datetime import datetime
import re

BASE = "/api/v1"
CHAVES_ERRO = {"codigo_erro", "mensagem", "timestamp"}
CHAVES_PRODUTO = {"id_produto", "nome", "categoria", "preco", "estoque_qtd"}
CHAVES_PEDIDO = {"id_pedido", "cliente_id", "itens_detalhados", "valor_total", "status", "data_pedido"}


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------

def pedido(itens, cliente_id="CLI-0042", forma_pagamento="PIX"):
    return {
        "cliente_id": cliente_id,
        "itens": [{"produto_id": p, "quantidade": q} for p, q in itens],
        "forma_pagamento": forma_pagamento,
    }


def estoque_de(client, id_produto):
    produtos = client.get(f"{BASE}/produtos").json()
    return next(p["estoque_qtd"] for p in produtos if p["id_produto"] == id_produto)


def assert_erro(resp, status, codigo):
    assert resp.status_code == status, resp.text
    corpo = resp.json()
    assert set(corpo) == CHAVES_ERRO
    assert corpo["codigo_erro"] == codigo
    assert corpo["mensagem"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", corpo["timestamp"])
    return corpo


# ---------------------------------------------------------------------------
# 1. GET /api/v1/produtos
# ---------------------------------------------------------------------------

class TestCatalogo:
    def test_lista_todos_os_produtos(self, client):
        resp = client.get(f"{BASE}/produtos")
        assert resp.status_code == 200
        produtos = resp.json()
        assert len(produtos) == 8
        for p in produtos:
            assert set(p) == CHAVES_PRODUTO

    def test_filtra_por_categoria(self, client):
        produtos = client.get(f"{BASE}/produtos", params={"categoria": "PERIFERICOS"}).json()
        assert {p["id_produto"] for p in produtos} == {"PROD-101", "PROD-102", "PROD-103"}
        assert all(p["categoria"] == "PERIFERICOS" for p in produtos)

    def test_filtro_nao_diferencia_maiusculas(self, client):
        resp = client.get(f"{BASE}/produtos", params={"categoria": "eletronicos"})
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    def test_categoria_sem_produtos_retorna_lista_vazia(self, client):
        resp = client.get(f"{BASE}/produtos", params={"categoria": "BRINQUEDOS"})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_dados_do_produto(self, client):
        produtos = client.get(f"{BASE}/produtos").json()
        mouse = next(p for p in produtos if p["id_produto"] == "PROD-101")
        assert mouse == {
            "id_produto": "PROD-101",
            "nome": "Mouse Sem Fio",
            "categoria": "PERIFERICOS",
            "preco": 89.9,
            "estoque_qtd": 15,
        }


# ---------------------------------------------------------------------------
# 2. POST /api/v1/pedidos
# ---------------------------------------------------------------------------

class TestFecharPedido:
    def test_fecha_pedido_com_sucesso(self, client):
        resp = client.post(f"{BASE}/pedidos", json=pedido([("PROD-101", 2), ("PROD-202", 1)]))
        assert resp.status_code == 201, resp.text
        corpo = resp.json()
        assert set(corpo) == CHAVES_PEDIDO
        assert corpo["cliente_id"] == "CLI-0042"
        assert corpo["status"] == "PENDENTE_PAGAMENTO"
        assert corpo["valor_total"] == 339.7
        assert corpo["itens_detalhados"] == [
            {"produto_id": "PROD-101", "nome_produto": "Mouse Sem Fio",
             "quantidade": 2, "preco_unitario": 89.9, "subtotal": 179.8},
            {"produto_id": "PROD-202", "nome_produto": "Fone Bluetooth TWS",
             "quantidade": 1, "preco_unitario": 159.9, "subtotal": 159.9},
        ]

    def test_id_e_data_no_formato_da_ficha(self, client):
        corpo = client.post(f"{BASE}/pedidos", json=pedido([("PROD-101", 1)])).json()
        ano = datetime.now().year
        assert corpo["id_pedido"] == f"PED-{ano}-001"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", corpo["data_pedido"])

    def test_ids_sao_sequenciais(self, client):
        ids = [
            client.post(f"{BASE}/pedidos", json=pedido([("PROD-101", 1)])).json()["id_pedido"]
            for _ in range(3)
        ]
        assert [i[-3:] for i in ids] == ["001", "002", "003"]

    def test_decrementa_estoque(self, client):
        client.post(f"{BASE}/pedidos", json=pedido([("PROD-101", 2), ("PROD-202", 1)]))
        assert estoque_de(client, "PROD-101") == 13
        assert estoque_de(client, "PROD-202") == 19

    def test_pode_comprar_todo_o_estoque(self, client):
        resp = client.post(f"{BASE}/pedidos", json=pedido([("PROD-103", 5)]))
        assert resp.status_code == 201
        assert estoque_de(client, "PROD-103") == 0

    def test_arredondamento_monetario(self, client):
        corpo = client.post(
            f"{BASE}/pedidos", json=pedido([("PROD-101", 3), ("PROD-302", 3)])
        ).json()
        # 3 x 89,90 = 269,70 ; 3 x 459,90 = 1379,70 ; total = 1649,40
        assert [i["subtotal"] for i in corpo["itens_detalhados"]] == [269.7, 1379.7]
        assert corpo["valor_total"] == 1649.4

    def test_aceita_todas_as_formas_de_pagamento(self, client):
        for forma in ("PIX", "CARTAO", "BOLETO"):
            resp = client.post(f"{BASE}/pedidos", json=pedido([("PROD-101", 1)], forma_pagamento=forma))
            assert resp.status_code == 201

    def test_itens_repetidos_tem_quantidades_somadas(self, client):
        corpo = client.post(
            f"{BASE}/pedidos", json=pedido([("PROD-101", 2), ("PROD-202", 1), ("PROD-101", 3)])
        ).json()
        assert [(i["produto_id"], i["quantidade"]) for i in corpo["itens_detalhados"]] == [
            ("PROD-101", 5), ("PROD-202", 1),
        ]
        assert estoque_de(client, "PROD-101") == 10

    def test_itens_repetidos_somados_estouram_estoque(self, client):
        # PROD-103 tem 5 unidades: 3 + 3 = 6 deve falhar mesmo cada linha cabendo sozinha
        resp = client.post(f"{BASE}/pedidos", json=pedido([("PROD-103", 3), ("PROD-103", 3)]))
        assert_erro(resp, 400, "ESTOQUE_INSUFICIENTE")
        assert estoque_de(client, "PROD-103") == 5

    def test_produto_inexistente_retorna_404(self, client):
        resp = client.post(f"{BASE}/pedidos", json=pedido([("PROD-999", 1)]))
        corpo = assert_erro(resp, 404, "PRODUTO_NAO_ENCONTRADO")
        assert "PROD-999" in corpo["mensagem"]

    def test_estoque_insuficiente_retorna_400(self, client):
        resp = client.post(f"{BASE}/pedidos", json=pedido([("PROD-103", 999)], forma_pagamento="CARTAO"))
        corpo = assert_erro(resp, 400, "ESTOQUE_INSUFICIENTE")
        assert corpo["mensagem"] == (
            "Estoque insuficiente para 'Headset Gamer USB' (PROD-103): "
            "solicitado 999, disponível 5."
        )

    def test_produto_sem_estoque_retorna_400(self, client):
        resp = client.post(f"{BASE}/pedidos", json=pedido([("PROD-203", 1)]))
        assert_erro(resp, 400, "ESTOQUE_INSUFICIENTE")

    def test_falha_nao_altera_estoque_atomicidade(self, client):
        # 1º item válido, 2º sem estoque: o 1º NÃO pode ser debitado
        resp = client.post(f"{BASE}/pedidos", json=pedido([("PROD-101", 2), ("PROD-103", 999)]))
        assert_erro(resp, 400, "ESTOQUE_INSUFICIENTE")
        assert estoque_de(client, "PROD-101") == 15

    def test_falha_nao_cria_pedido(self, client):
        client.post(f"{BASE}/pedidos", json=pedido([("PROD-101", 1), ("PROD-999", 1)]))
        # Nenhum pedido foi gravado e a sequência não foi consumida
        ano = datetime.now().year
        assert_erro(client.get(f"{BASE}/pedidos/PED-{ano}-001"), 404, "PEDIDO_NAO_ENCONTRADO")
        novo = client.post(f"{BASE}/pedidos", json=pedido([("PROD-101", 1)])).json()
        assert novo["id_pedido"] == f"PED-{ano}-001"
        assert estoque_de(client, "PROD-101") == 14

    def test_produto_inexistente_tem_prioridade_sobre_estoque(self, client):
        # Item sem estoque vem ANTES do inexistente; ainda assim a resposta é 404
        resp = client.post(f"{BASE}/pedidos", json=pedido([("PROD-103", 999), ("PROD-999", 1)]))
        assert_erro(resp, 404, "PRODUTO_NAO_ENCONTRADO")

    def test_forma_de_pagamento_invalida(self, client):
        resp = client.post(f"{BASE}/pedidos", json=pedido([("PROD-101", 1)], forma_pagamento="DINHEIRO"))
        assert_erro(resp, 400, "REQUISICAO_INVALIDA")

    def test_quantidade_zero(self, client):
        resp = client.post(f"{BASE}/pedidos", json=pedido([("PROD-101", 0)], forma_pagamento="BOLETO"))
        assert_erro(resp, 400, "REQUISICAO_INVALIDA")
        assert estoque_de(client, "PROD-101") == 15

    def test_quantidade_negativa(self, client):
        resp = client.post(f"{BASE}/pedidos", json=pedido([("PROD-101", -2)]))
        assert_erro(resp, 400, "REQUISICAO_INVALIDA")
        assert estoque_de(client, "PROD-101") == 15

    def test_lista_de_itens_vazia(self, client):
        resp = client.post(f"{BASE}/pedidos", json=pedido([]))
        assert_erro(resp, 400, "REQUISICAO_INVALIDA")

    def test_campo_obrigatorio_ausente(self, client):
        payload = pedido([("PROD-101", 1)])
        del payload["cliente_id"]
        assert_erro(client.post(f"{BASE}/pedidos", json=payload), 400, "REQUISICAO_INVALIDA")

    def test_campo_extra_e_recusado(self, client):
        payload = pedido([("PROD-101", 1)])
        payload["desconto"] = 50
        assert_erro(client.post(f"{BASE}/pedidos", json=payload), 400, "REQUISICAO_INVALIDA")

    def test_json_malformado(self, client):
        resp = client.post(
            f"{BASE}/pedidos",
            content='{"cliente_id": "CLI-0042", ',
            headers={"Content-Type": "application/json"},
        )
        assert_erro(resp, 400, "REQUISICAO_INVALIDA")


# ---------------------------------------------------------------------------
# 3. GET /api/v1/pedidos/{id_pedido}
# ---------------------------------------------------------------------------

class TestDetalharPedido:
    def test_detalha_pedido_criado(self, client):
        criado = client.post(f"{BASE}/pedidos", json=pedido([("PROD-101", 2), ("PROD-202", 1)])).json()
        resp = client.get(f"{BASE}/pedidos/{criado['id_pedido']}")
        assert resp.status_code == 200
        assert resp.json() == criado

    def test_pedido_nao_expoe_dados_internos(self, client):
        criado = client.post(f"{BASE}/pedidos", json=pedido([("PROD-101", 1)])).json()
        corpo = client.get(f"{BASE}/pedidos/{criado['id_pedido']}").json()
        assert set(corpo) == CHAVES_PEDIDO  # sem "itens" nem "forma_pagamento" do modelo interno

    def test_pedido_inexistente_retorna_404(self, client):
        resp = client.get(f"{BASE}/pedidos/PED-0000-000")
        corpo = assert_erro(resp, 404, "PEDIDO_NAO_ENCONTRADO")
        assert "PED-0000-000" in corpo["mensagem"]


# ---------------------------------------------------------------------------
# 4. PATCH /api/v1/produtos/{id_produto}/estoque
# ---------------------------------------------------------------------------

class TestAjustarEstoque:
    def url(self, id_produto):
        return f"{BASE}/produtos/{id_produto}/estoque"

    def test_reposicao(self, client):
        resp = client.patch(self.url("PROD-302"), json={"quantidade_adicional": 10})
        assert resp.status_code == 200
        assert resp.json() == {
            "id_produto": "PROD-302",
            "nome": "SSD NVMe 1TB",
            "estoque_anterior": 12,
            "estoque_atualizado": 22,
        }
        assert estoque_de(client, "PROD-302") == 22

    def test_baixa_manual(self, client):
        corpo = client.patch(self.url("PROD-302"), json={"quantidade_adicional": -3}).json()
        assert (corpo["estoque_anterior"], corpo["estoque_atualizado"]) == (12, 9)
        assert estoque_de(client, "PROD-302") == 9

    def test_ajuste_zero_nao_altera(self, client):
        resp = client.patch(self.url("PROD-302"), json={"quantidade_adicional": 0})
        assert resp.status_code == 200
        assert resp.json()["estoque_atualizado"] == 12

    def test_baixa_ate_zerar_e_permitida(self, client):
        resp = client.patch(self.url("PROD-103"), json={"quantidade_adicional": -5})
        assert resp.status_code == 200
        assert resp.json()["estoque_atualizado"] == 0

    def test_estoque_negativo_retorna_400(self, client):
        resp = client.patch(self.url("PROD-302"), json={"quantidade_adicional": -1000})
        assert_erro(resp, 400, "ESTOQUE_NEGATIVO")
        assert estoque_de(client, "PROD-302") == 12

    def test_produto_inexistente_retorna_404(self, client):
        resp = client.patch(self.url("PROD-999"), json={"quantidade_adicional": 5})
        assert_erro(resp, 404, "PRODUTO_NAO_ENCONTRADO")

    def test_payload_invalido(self, client):
        assert_erro(client.patch(self.url("PROD-302"), json={}), 400, "REQUISICAO_INVALIDA")
        assert_erro(
            client.patch(self.url("PROD-302"), json={"quantidade_adicional": "dez"}),
            400, "REQUISICAO_INVALIDA",
        )
        assert_erro(
            client.patch(self.url("PROD-302"), json={"quantidade_adicional": 1, "x": 1}),
            400, "REQUISICAO_INVALIDA",
        )
        assert estoque_de(client, "PROD-302") == 12

    def test_reposicao_libera_venda(self, client):
        # PROD-203 começa com estoque 0
        assert_erro(client.post(f"{BASE}/pedidos", json=pedido([("PROD-203", 2)])), 400, "ESTOQUE_INSUFICIENTE")
        client.patch(self.url("PROD-203"), json={"quantidade_adicional": 2})
        assert client.post(f"{BASE}/pedidos", json=pedido([("PROD-203", 2)])).status_code == 201
        assert estoque_de(client, "PROD-203") == 0


# ---------------------------------------------------------------------------
# Erros genéricos no formato padronizado
# ---------------------------------------------------------------------------

class TestErrosGenericos:
    def test_rota_inexistente(self, client):
        assert_erro(client.get(f"{BASE}/clientes"), 404, "ROTA_NAO_ENCONTRADA")

    def test_metodo_nao_permitido(self, client):
        assert_erro(client.delete(f"{BASE}/produtos"), 405, "METODO_NAO_PERMITIDO")
