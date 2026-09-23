import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api(tmp_path, monkeypatch):
    from app import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "teste.db"))
    from app.main import app
    with TestClient(app) as c:
        yield c


def produto(api, sku="LEITE", ean="7890000000001"):
    r = api.post("/api/produtos", json={"sku": sku, "descricao": "Leite 1L", "ean": ean})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def saldo(api, lote):
    return sum(l["quantidade"] or 0 for l in api.get("/api/estoque").json() if l["lote"] == lote)


def test_baixa_por_quantidade_segue_fefo(api):
    pid = produto(api)
    api.post("/api/entradas", json={"produto_id": pid, "lote": "L2", "validade": "2030-12-31", "quantidade": 10})
    api.post("/api/entradas", json={"produto_id": pid, "lote": "L1", "validade": "2030-01-31", "quantidade": 5})

    r = api.post("/api/baixas", json={"codigo": "7890000000001", "quantidade": 7, "origem": "COLETOR", "meio": "BARRAS"})
    assert r.status_code == 200, r.text
    assert [(l["lote"], l["quantidade"]) for l in r.json()["lotes"]] == [("L1", 5), ("L2", 2)]
    assert saldo(api, "L1") == 0 and saldo(api, "L2") == 8

    r = api.post("/api/baixas", json={"produto_id": pid, "quantidade": 100})
    assert r.status_code == 400 and "insuficiente" in r.json()["detail"]


def test_entrada_e_baixa_rfid(api):
    pid = produto(api)
    r = api.post("/api/entradas", json={"produto_id": pid, "lote": "L1", "validade": "2030-01-01",
                                        "epcs": ["e2001", "E2002", "E2003"], "origem": "COLETOR"})
    assert r.json()["quantidade"] == 3
    r = api.post("/api/baixas", json={"epcs": ["E2001", "E2001", "FFFF"], "origem": "COLETOR", "meio": "RFID"})
    oks = [t["ok"] for t in r.json()["tags"]]
    assert oks == [True, False, False]          # repetida e desconhecida falham sozinhas
    assert saldo(api, "L1") == 2
    assert api.get("/api/tags/E2001").json()["status"] == "BAIXADA"


def test_inventario_confronta_e_ajusta(api):
    pid = produto(api)
    api.post("/api/entradas", json={"produto_id": pid, "lote": "A", "validade": "2030-01-01", "epcs": ["A1", "A2"]})
    api.post("/api/entradas", json={"produto_id": pid, "lote": "B", "validade": "2031-01-01", "quantidade": 10})
    lote_b = next(l["lote_id"] for l in api.get("/api/estoque").json() if l["lote"] == "B")

    inv = api.post("/api/inventarios", json={"nome": "Geral"}).json()["id"]
    api.post(f"/api/inventarios/{inv}/contagens", json={"epcs": ["A1", "A1"], "origem": "COLETOR", "meio": "RFID"})
    api.post(f"/api/inventarios/{inv}/contagens", json={"lote_id": lote_b, "quantidade": 12})

    confronto = {c["lote"]: c for c in api.get(f"/api/inventarios/{inv}").json()["confronto"]}
    assert confronto["A"]["diferenca"] == -1 and confronto["B"]["diferenca"] == 2

    assert api.post(f"/api/inventarios/{inv}/fechar").json()["ajustes"] == 2
    assert saldo(api, "A") == 1 and saldo(api, "B") == 12
    assert api.post(f"/api/inventarios/{inv}/contagens", json={"lote_id": lote_b, "quantidade": 1}).status_code == 400


def test_fefo_ignora_vencidos_exceto_motivo_vencimento(api):
    pid = produto(api)
    api.post("/api/entradas", json={"produto_id": pid, "lote": "VELHO", "validade": "2020-01-01", "quantidade": 5})
    api.post("/api/entradas", json={"produto_id": pid, "lote": "NOVO", "validade": "2030-01-01", "quantidade": 5})

    r = api.post("/api/baixas", json={"produto_id": pid, "quantidade": 2})
    assert [l["lote"] for l in r.json()["lotes"]] == ["NOVO"]
    r = api.post("/api/baixas", json={"produto_id": pid, "quantidade": 5, "motivo": "VENCIMENTO"})
    assert [l["lote"] for l in r.json()["lotes"]] == ["VELHO"]
    assert saldo(api, "VELHO") == 0 and saldo(api, "NOVO") == 3


def test_baixa_por_quantidade_nao_usa_unidades_com_tag(api):
    pid = produto(api)
    api.post("/api/entradas", json={"produto_id": pid, "lote": "RF", "validade": "2030-01-01", "epcs": ["T1", "T2"]})
    api.post("/api/entradas", json={"produto_id": pid, "lote": "CB", "validade": "2031-01-01", "quantidade": 5})

    r = api.post("/api/baixas", json={"produto_id": pid, "quantidade": 3})
    assert [l["lote"] for l in r.json()["lotes"]] == ["CB"]       # pula o lote etiquetado
    r = api.post("/api/baixas", json={"epcs": ["T1"]})
    assert r.json()["tags"][0]["ok"]                              # a tag continua podendo sair
    # sem etiqueta acabou (5-3=2): a baixa por quantidade usa as etiquetadas e baixa a tag
    r = api.post("/api/baixas", json={"produto_id": pid, "quantidade": 3})
    assert r.status_code == 200, r.text
    assert [(l["lote"], l["quantidade"], l["etiquetas"]) for l in r.json()["lotes"]] == [("CB", 2, 0), ("RF", 1, 1)]
    assert api.get("/api/tags/T2").json()["status"] == "BAIXADA" and saldo(api, "RF") == 0


def lote_id(api, lote):
    return next(l["lote_id"] for l in api.get("/api/estoque").json() if l["lote"] == lote)


def test_pedido_reserva_fefo_e_expede(api):
    pid = produto(api)
    api.post("/api/entradas", json={"produto_id": pid, "lote": "L1", "validade": "2030-01-01", "quantidade": 4})
    api.post("/api/entradas", json={"produto_id": pid, "lote": "L2", "validade": "2031-01-01", "quantidade": 10})

    r = api.post("/api/pedidos", json={"cliente": "Mercado X", "itens": [
        {"codigo": "7890000000001", "quantidade": 3}, {"produto_id": pid, "quantidade": 3}]})
    assert r.status_code == 200, r.text
    ped = r.json()["id"]
    assert r.json()["numero"] == f"PED-{ped:05d}"
    assert api.post(f"/api/pedidos/{ped}/liberar").json()["status"] == "SEPARANDO"

    sep = api.get(f"/api/pedidos/{ped}").json()["separacao"]
    assert [(s["lote"], s["quantidade"]) for s in sep] == [("L1", 4), ("L2", 2)]
    # O reservado não pode sair em outra baixa
    assert api.post("/api/baixas", json={"produto_id": pid, "quantidade": 9}).status_code == 400
    assert api.post("/api/baixas", json={"produto_id": pid, "quantidade": 8}).status_code == 200

    assert api.post(f"/api/pedidos/{ped}/expedir").json()["status"] == "EXPEDIDO"
    assert saldo(api, "L1") == 0 and saldo(api, "L2") == 0
    movs = api.get("/api/movimentos", params={"busca": f"PED-{ped:05d}"}).json()
    assert len(movs) == 2 and all(m["motivo"] == "VENDA" for m in movs)
    assert api.post(f"/api/pedidos/{ped}/cancelar").status_code == 400


def test_cancelar_pedido_devolve_reserva(api):
    pid = produto(api)
    api.post("/api/entradas", json={"produto_id": pid, "lote": "L1", "quantidade": 5})
    ped = api.post("/api/pedidos", json={"cliente": "C", "itens": [{"produto_id": pid, "quantidade": 5}]}).json()["id"]
    api.post(f"/api/pedidos/{ped}/liberar")
    assert api.post("/api/baixas", json={"produto_id": pid, "quantidade": 1}).status_code == 400
    api.post(f"/api/pedidos/{ped}/cancelar")
    assert api.post("/api/baixas", json={"produto_id": pid, "quantidade": 5}).status_code == 200


def test_lote_bloqueado_fica_fora_do_fefo(api):
    pid = produto(api)
    api.post("/api/entradas", json={"produto_id": pid, "lote": "Q", "validade": "2030-01-01", "quantidade": 5})
    api.post("/api/entradas", json={"produto_id": pid, "lote": "OK", "validade": "2031-01-01", "quantidade": 5})
    q = lote_id(api, "Q")
    assert api.post(f"/api/lotes/{q}/bloquear", json={"motivo": ""}).status_code == 400   # motivo obrigatório
    assert api.post(f"/api/lotes/{q}/bloquear", json={"motivo": "Embalagem molhada"}).status_code == 200

    r = api.post("/api/baixas", json={"produto_id": pid, "quantidade": 2})
    assert [l["lote"] for l in r.json()["lotes"]] == ["OK"]
    # Lote bloqueado só sai por descarte
    assert api.post("/api/baixas", json={"lote_id": q, "quantidade": 1, "motivo": "CONSUMO"}).status_code == 400
    assert api.post("/api/baixas", json={"lote_id": q, "quantidade": 1, "motivo": "AVARIA"}).status_code == 200
    api.post(f"/api/lotes/{q}/liberar")
    r = api.post("/api/baixas", json={"produto_id": pid, "quantidade": 1})
    assert [l["lote"] for l in r.json()["lotes"]] == ["Q"]


def test_entrada_na_doca_e_transferencia(api):
    pid = produto(api)
    r = api.post("/api/entradas", json={"produto_id": pid, "lote": "L1", "validade": "31/12/2030",
                                        "quantidade": 6, "documento": "NF 123"})
    assert r.json()["endereco"] == "DOCA-REC"
    end = api.post("/api/enderecos", json={"codigo": "a-01-01"}).json()["id"]
    assert api.post("/api/enderecos", json={"codigo": "A-01-01"}).status_code == 400   # duplicado

    l1 = lote_id(api, "L1")
    assert api.post(f"/api/lotes/{l1}/transferir", json={"endereco": "A-01-01"}).json()["para"] == "A-01-01"
    linha = next(l for l in api.get("/api/estoque").json() if l["lote"] == "L1")
    assert linha["endereco"] == "A-01-01" and linha["validade"] == "2030-12-31"
    assert api.post(f"/api/lotes/{l1}/transferir", json={"endereco_id": end}).status_code == 400
    # Endereço com estoque não pode ser inativado
    assert api.put(f"/api/enderecos/{end}", json={"codigo": "A-01-01", "ativo": False}).status_code == 400
    tipos = [m["tipo"] for m in api.get("/api/movimentos").json()]
    assert tipos == ["TRANSFERENCIA", "ENTRADA"]


def test_validacoes_de_cadastro_e_quantidade(api):
    pid = produto(api)
    assert api.post("/api/produtos", json={"sku": "OUTRO", "descricao": "x", "ean": "7890000000001"}).status_code == 400
    r = api.post("/api/produtos", json={"sku": "", "descricao": "x"})
    assert r.status_code == 400 and "sku" in r.json()["detail"]
    r = api.post("/api/entradas", json={"produto_id": pid, "lote": "L", "quantidade": 1.5})
    assert r.status_code == 400 and "inteira" in r.json()["detail"]
    assert api.post("/api/entradas", json={"produto_id": pid, "lote": "L", "validade": "32/13/2030",
                                           "quantidade": 1}).status_code == 400
    # Produto inativo não recebe entrada
    api.put(f"/api/produtos/{pid}", json={"sku": "LEITE", "descricao": "Leite 1L", "ativo": False})
    assert api.post("/api/entradas", json={"produto_id": pid, "quantidade": 1}).status_code == 400


def test_resumo_e_csv(api):
    pid = produto(api)
    api.post("/api/entradas", json={"produto_id": pid, "lote": "V", "validade": "2020-01-01", "quantidade": 2})
    r = api.get("/api/resumo").json()
    assert r["vencidos"] == 1 and r["entradas_hoje"] == 2 and r["na_doca"] == 1
    csv = api.get("/api/estoque.csv")
    assert csv.status_code == 200 and "LEITE;Leite 1L" in csv.text


def test_migra_banco_da_versao_anterior(tmp_path, monkeypatch):
    import sqlite3
    from app import db
    caminho = tmp_path / "antigo.db"
    antigo = sqlite3.connect(caminho)
    antigo.executescript("""
        CREATE TABLE produtos (id INTEGER PRIMARY KEY, sku TEXT UNIQUE, descricao TEXT, ean TEXT,
                               unidade TEXT DEFAULT 'UN', estoque_min REAL DEFAULT 0);
        CREATE TABLE lotes (id INTEGER PRIMARY KEY, produto_id INTEGER, lote TEXT, validade TEXT,
                            quantidade REAL DEFAULT 0, UNIQUE (produto_id, lote));
        CREATE TABLE movimentos (id INTEGER PRIMARY KEY, data_hora TEXT, tipo TEXT, lote_id INTEGER,
                                 quantidade REAL, epc TEXT, origem TEXT, meio TEXT, motivo TEXT);
        INSERT INTO produtos (sku, descricao) VALUES ('A', 'Antigo');
        INSERT INTO lotes (produto_id, lote, quantidade) VALUES (1, 'L', 3);""")
    antigo.commit(); antigo.close()
    monkeypatch.setattr(db, "DB_PATH", str(caminho))
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        linha = next(l for l in c.get("/api/estoque").json() if l["lote"] == "L")
        assert linha["endereco"] == "DOCA-REC" and linha["status"] == "LIBERADO"
        assert c.post("/api/baixas", json={"produto_id": 1, "quantidade": 1}).status_code == 200


def test_excluir_produto_com_movimentacao(api):
    pid = produto(api)
    outro = produto(api, sku="CAFE", ean="7890000000002")
    api.post("/api/entradas", json={"produto_id": pid, "lote": "L1", "epcs": ["X1"], "quantidade": 0})
    api.post("/api/entradas", json={"produto_id": pid, "lote": "L2", "quantidade": 5})
    api.post("/api/entradas", json={"produto_id": outro, "lote": "C1", "quantidade": 5})
    inv = api.post("/api/inventarios", json={"nome": "I"}).json()["id"]
    api.post(f"/api/inventarios/{inv}/contagens", json={"epcs": ["X1"]})
    so_ele = api.post("/api/pedidos", json={"cliente": "A", "itens": [{"produto_id": pid, "quantidade": 2}]}).json()["id"]
    misto = api.post("/api/pedidos", json={"cliente": "B", "itens": [
        {"produto_id": pid, "quantidade": 1}, {"produto_id": outro, "quantidade": 1}]}).json()["id"]
    api.post(f"/api/pedidos/{so_ele}/liberar")

    r = api.delete(f"/api/produtos/{pid}")
    assert r.status_code == 200 and r.json()["lotes"] == 2
    assert all(p["id"] != pid for p in api.get("/api/produtos").json())
    assert all(m["sku"] == "CAFE" for m in api.get("/api/movimentos").json())
    assert api.get(f"/api/pedidos/{so_ele}").status_code == 400          # pedido vazio sumiu
    assert len(api.get(f"/api/pedidos/{misto}").json()["itens"]) == 1
    assert api.get("/api/tags/X1").status_code == 400


def test_lista_tags_e_paginas(api):
    pid = produto(api)
    api.post("/api/entradas", json={"produto_id": pid, "lote": "L1", "epcs": ["T1", "T2"]})
    api.post("/api/baixas", json={"epcs": ["T1"]})
    assert [t["epc"] for t in api.get("/api/tags", params={"status": "ATIVA"}).json()] == ["T2"]
    assert len(api.get("/api/tags").json()) == 2
    assert "DataWedge" in api.get("/m").text
    assert api.get("/coletor").status_code == 404 and "Mini WMS" in api.get("/").text
    st = api.get("/api/status").json()
    assert st["servidor"] == "Mini WMS" and st["coletor"].startswith("http://")


def test_limpar_tudo(api):
    pid = produto(api)
    api.post("/api/enderecos", json={"codigo": "A-01-01"})
    api.post("/api/entradas", json={"produto_id": pid, "lote": "L1", "epcs": ["T1"]})
    api.post("/api/pedidos", json={"cliente": "C", "itens": [{"produto_id": pid, "quantidade": 1}]})
    api.post("/api/inventarios", json={"nome": "I"})

    # Mantendo cadastros: some só a movimentação
    assert api.post("/api/limpar-tudo", json={"manter_cadastros": True}).status_code == 200
    assert len(api.get("/api/produtos").json()) == 1 and len(api.get("/api/enderecos").json()) == 2
    assert api.get("/api/movimentos").json() == [] and api.get("/api/pedidos").json() == []
    assert api.get("/api/inventarios").json() == [] and api.get("/api/tags").json() == []

    # Tudo: sobra só a doca padrão, e os códigos recomeçam do 1
    api.post("/api/limpar-tudo", json={})
    assert api.get("/api/produtos").json() == []
    assert [e["codigo"] for e in api.get("/api/enderecos").json()] == ["DOCA-REC"]
    assert produto(api) == 1
    api.post("/api/entradas", json={"produto_id": 1, "lote": "N", "quantidade": 2})
    assert api.get("/api/resumo").json()["unidades"] == 2


def test_ordem_de_recebimento_online(api):
    pid = produto(api)
    cafe = produto(api, sku="CAFE", ean="7890000000002")
    r = api.post("/api/recebimentos", json={"documento": "NF 900", "fornecedor": "Laticínios X", "itens": [
        {"produto_id": pid, "lote": "l1", "validade": "31/12/2030", "quantidade": 2},
        {"codigo": "CAFE", "lote": "C1", "quantidade": 5}]})
    assert r.status_code == 200, r.text
    rec = r.json()["id"]
    assert r.json()["numero"] == f"REC-{rec:05d}"

    # Coletor: bipa o produto (acha o item) e lê as etiquetas; cada leitura grava na hora
    r = api.post(f"/api/recebimentos/{rec}/leituras", json={"codigo": "7890000000001", "epcs": ["A1", "A2", "A1", "A3"]})
    tags = {t["epc"]: t for t in r.json()["tags"]}
    assert tags["A1"]["ok"] and tags["A2"]["ok"] and not tags["A3"]["ok"] and tags["A3"]["excedente"]
    assert r.json()["lidas"] == 2
    again = api.post(f"/api/recebimentos/{rec}/leituras", json={"codigo": "7890000000001", "epcs": ["A1"]}).json()
    assert again["tags"][0]["repetida"]
    # Item sem etiqueta: quantidade; não pode passar do previsto
    assert api.post(f"/api/recebimentos/{rec}/leituras", json={"codigo": "CAFE", "quantidade": 6, "meio": "BARRAS"}).status_code == 400
    assert api.post(f"/api/recebimentos/{rec}/leituras", json={"codigo": "CAFE", "quantidade": 4, "meio": "BARRAS"}).status_code == 200

    # Etiqueta de outra ordem aberta é recusada
    rec2 = api.post("/api/recebimentos", json={"itens": [{"produto_id": pid, "lote": "L9", "quantidade": 3}]}).json()["id"]
    r = api.post(f"/api/recebimentos/{rec2}/leituras", json={"epcs": ["A1", "B1"]})   # item único: escolhido sozinho
    assert [t["ok"] for t in r.json()["tags"]] == [False, True]

    d = api.get(f"/api/recebimentos/{rec}").json()
    assert [(i["sku"], i["lidas"], i["prevista"]) for i in d["itens"]] == [("LEITE", 2, 2), ("CAFE", 4, 5)]
    assert len(d["leituras"]) == 3 and api.get("/api/resumo").json()["recebimentos_abertos"] == 2

    f = api.post(f"/api/recebimentos/{rec}/finalizar").json()
    assert f["divergencias"] == ["CAFE lote C1: recebido 4 de 5"]
    assert not r.json()["tags"][0].get("excedente")
    assert saldo(api, "L1") == 2 and saldo(api, "C1") == 4
    assert api.get("/api/tags/A1").json()["status"] == "ATIVA"
    assert all(m["documento"] == "NF 900" for m in api.get("/api/movimentos").json() if m["tipo"] == "ENTRADA")
    assert api.post(f"/api/recebimentos/{rec}/leituras", json={"codigo": "CAFE", "quantidade": 1}).status_code == 400
    # Agora A1 está em estoque: não entra em outra ordem
    r = api.post(f"/api/recebimentos/{rec2}/leituras", json={"epcs": ["A2"]})
    assert "estoque" in r.json()["tags"][0]["erro"]
    assert api.post(f"/api/recebimentos/{rec2}/cancelar").json()["status"] == "CANCELADO"
    api.post("/api/limpar-tudo", json={"manter_cadastros": True})
    assert api.get("/api/recebimentos").json() == []


def test_inventario_por_rfid_e_estorno(api):
    pid = produto(api)
    rec = api.post("/api/recebimentos", json={"itens": [{"produto_id": pid, "quantidade": 4}]}).json()["id"]  # lote opcional
    api.post(f"/api/recebimentos/{rec}/leituras", json={"epcs": ["T1", "T2", "T3", "T4"]})
    api.post(f"/api/recebimentos/{rec}/finalizar")
    assert saldo(api, "SEM-LOTE") == 4
    # unidade sem etiqueta no mesmo produto (não entra no inventário RFID)
    api.post("/api/entradas", json={"produto_id": pid, "lote": "CX", "quantidade": 5})

    # baixa por leitura e estorno (leitura por engano)
    api.post("/api/baixas", json={"epcs": ["T4"], "origem": "COLETOR", "meio": "RFID"})
    assert saldo(api, "SEM-LOTE") == 3
    assert api.post("/api/tags/T4/estornar").status_code == 200
    assert saldo(api, "SEM-LOTE") == 4 and api.get("/api/tags/T4").json()["status"] == "ATIVA"
    assert api.post("/api/tags/T4/estornar").status_code == 400          # já está em estoque
    api.post("/api/baixas", json={"epcs": ["T3"]})                        # T3 sai de verdade

    # inventário lendo etiquetas: T1, T2 e T3 (baixada, mas achada); T4 não foi lida
    inv = api.post("/api/inventarios", json={"nome": "RFID"}).json()["id"]
    api.post(f"/api/inventarios/{inv}/contagens", json={"epcs": ["T1", "T2", "T3"], "origem": "COLETOR", "meio": "RFID"})
    d = api.get(f"/api/inventarios/{inv}").json()
    conf = {c["lote"]: c for c in d["confronto"]}
    assert "CX" not in conf                                               # sem etiqueta: fora da conta
    assert [(e["epc"], e["situacao"]) for e in d["etiquetas"]] == [("T4", "FALTA"), ("T3", "SOBRA"), ("T1", "OK"), ("T2", "OK")]
    assert (conf["SEM-LOTE"]["sistema"], conf["SEM-LOTE"]["contado"]) == (3, 3)
    # 2 etiquetas que o sistema não conhece: contam como sobra, em vermelho
    r = api.post(f"/api/inventarios/{inv}/contagens", json={"epcs": ["X9", "X8", "X9"], "origem": "COLETOR", "meio": "RFID"})
    assert all(t["ok"] for t in r.json()["tags"])
    d = api.get(f"/api/inventarios/{inv}").json()
    extra = [c for c in d["confronto"] if c["lote_id"] is None][0]
    assert (extra["contado"], extra["diferenca"]) == (2, 2)
    assert [(e["epc"], e["situacao"]) for e in d["etiquetas"][:2]] == [("X8", "SOBRA"), ("X9", "SOBRA")]
    r = api.post(f"/api/inventarios/{inv}/fechar").json()
    assert (r["faltas"], r["sobras"], r["desconhecidas"]) == (1, 3, 2)   # sobra: T3 + as 2 não cadastradas
    # fechado: continua mostrando o que foi lido na hora (não o estoque de agora)
    api.post("/api/baixas", json={"epcs": ["T1"]})
    conf = {c["lote"]: c for c in api.get(f"/api/inventarios/{inv}").json()["confronto"]}
    assert (conf["SEM-LOTE"]["sistema"], conf["SEM-LOTE"]["contado"]) == (3, 3)
    guardadas = [(e["epc"], e["situacao"]) for e in api.get(f"/api/inventarios/{inv}").json()["etiquetas"]]
    assert guardadas == [("X8", "SOBRA"), ("X9", "SOBRA"), ("T4", "FALTA"), ("T3", "SOBRA"), ("T1", "OK"), ("T2", "OK")]
    assert [c for c in api.get(f"/api/inventarios/{inv}").json()["confronto"] if c["lote_id"] is None][0]["contado"] == 2
    # incluir as 2 a mais no estoque (inventário já fechado)
    r = api.post(f"/api/inventarios/{inv}/incluir-sobras", json={"produto_id": pid})
    assert r.status_code == 200 and r.json()["incluidas"] == 2
    assert api.get("/api/tags/X8").json()["status"] == "ATIVA" and saldo(api, "SEM-LOTE") == 4   # 2 (T1 baixada agora) + 2
    assert all(e["descricao"] == "incluída no estoque" for e in api.get(f"/api/inventarios/{inv}").json()["etiquetas"][:2])
    assert api.post(f"/api/inventarios/{inv}/incluir-sobras", json={"produto_id": pid}).status_code == 400   # nada mais a incluir

    # inventário aberto: incluída passa a contar como lida normal
    inv2 = api.post("/api/inventarios", json={"nome": "aberto"}).json()["id"]
    api.post(f"/api/inventarios/{inv2}/contagens", json={"epcs": ["Z1"]})
    api.post(f"/api/inventarios/{inv2}/incluir-sobras", json={"produto_id": pid})
    d2 = api.get(f"/api/inventarios/{inv2}").json()
    assert [(e["epc"], e["situacao"]) for e in d2["etiquetas"] if e["epc"] == "Z1"] == [("Z1", "OK")]
    api.post("/api/tags/T1/estornar")
    assert api.get("/api/tags/T4").json()["status"] == "BAIXADA" and api.get("/api/tags/T3").json()["status"] == "ATIVA"
    assert saldo(api, "SEM-LOTE") == 6 and saldo(api, "CX") == 5   # 4 + Z1 incluída + T1 estornada
