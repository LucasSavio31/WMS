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
