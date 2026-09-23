"""Mini WMS RFID — servidor que roda no PC.

Iniciar:   uvicorn app.main:app --host 0.0.0.0 --port 8000
Tela web:  http://localhost:8000
O coletor Zebra acessa a mesma API pelo IP do PC na rede Wi-Fi.
"""
import os
import sqlite3
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, estoque
from .estoque import ErroEstoque

STATIC = os.path.join(os.path.dirname(__file__), "static")
MOTIVOS = ["CONSUMO", "VENDA", "AVARIA", "PERDA", "VENCIMENTO"]
Origem = Literal["PC", "COLETOR"]
Meio = Literal["MANUAL", "BARRAS", "RFID"]


@asynccontextmanager
async def iniciar(_app):
    db.inicializar()
    yield


app = FastAPI(title="Mini WMS RFID", lifespan=iniciar)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.exception_handler(ErroEstoque)
def erro_estoque(_req: Request, exc: ErroEstoque):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def conexao():
    """Uma conexão por requisição; grava tudo no final (ou desfaz se deu erro)."""
    con = db.conectar()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


Con = sqlite3.Connection


@app.get("/", include_in_schema=False)
def pagina_inicial():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/api/status")
def status():
    """O coletor usa para testar a conexão com o servidor."""
    return {"ok": True, "data_hora": db.agora(), "motivos": MOTIVOS}


# ================================================================ produtos
class Produto(BaseModel):
    sku: str
    descricao: str
    ean: Optional[str] = None
    unidade: str = "UN"
    estoque_min: float = 0


@app.get("/api/produtos")
def listar_produtos(con: Con = Depends(conexao)):
    return db.linhas(con.execute("SELECT * FROM produtos ORDER BY descricao"))


@app.get("/api/produtos/busca")
def buscar_produto(codigo: str, con: Con = Depends(conexao)):
    """Produto pelo código de barras (EAN) ou SKU, com seus lotes em ordem FEFO."""
    p = estoque.buscar_produto(con, codigo=codigo)
    lotes = db.linhas(con.execute(
        "SELECT * FROM lotes WHERE produto_id=? ORDER BY validade IS NULL, validade", (p["id"],)))
    return {**dict(p), "lotes": lotes}


@app.post("/api/produtos")
def criar_produto(p: Produto, con: Con = Depends(conexao)):
    try:
        cur = con.execute("INSERT INTO produtos (sku, descricao, ean, unidade, estoque_min) VALUES (?,?,?,?,?)",
                          (p.sku.strip(), p.descricao.strip(), (p.ean or "").strip() or None, p.unidade, p.estoque_min))
    except sqlite3.IntegrityError:
        raise HTTPException(400, "SKU já cadastrado")
    return {"id": cur.lastrowid}


@app.put("/api/produtos/{produto_id}")
def editar_produto(produto_id: int, p: Produto, con: Con = Depends(conexao)):
    try:
        con.execute("UPDATE produtos SET sku=?, descricao=?, ean=?, unidade=?, estoque_min=? WHERE id=?",
                    (p.sku.strip(), p.descricao.strip(), (p.ean or "").strip() or None, p.unidade, p.estoque_min,
                     produto_id))
    except sqlite3.IntegrityError:
        raise HTTPException(400, "SKU já cadastrado")
    return {"ok": True}


@app.delete("/api/produtos/{produto_id}")
def excluir_produto(produto_id: int, con: Con = Depends(conexao)):
    if con.execute("SELECT 1 FROM lotes WHERE produto_id=?", (produto_id,)).fetchone():
        raise HTTPException(400, "Produto já tem lotes/movimentação e não pode ser excluído")
    con.execute("DELETE FROM produtos WHERE id=?", (produto_id,))
    return {"ok": True}


# ================================================================ posição de estoque
@app.get("/api/estoque")
def posicao_estoque(con: Con = Depends(conexao)):
    """Saldo por produto e lote, em ordem de validade (FEFO)."""
    return db.linhas(con.execute(
        """SELECT p.id AS produto_id, p.sku, p.descricao, p.unidade, p.estoque_min,
                  l.id AS lote_id, l.lote, l.validade, l.quantidade,
                  CAST(julianday(l.validade) - julianday(?) AS INTEGER) AS dias_para_vencer,
                  (SELECT COUNT(*) FROM tags t WHERE t.lote_id=l.id AND t.status='ATIVA') AS tags
           FROM produtos p LEFT JOIN lotes l ON l.produto_id=p.id AND l.quantidade > 0
           ORDER BY p.descricao, l.validade IS NULL, l.validade""", (db.hoje(),)))


@app.get("/api/movimentos")
def movimentos(limite: int = 200, con: Con = Depends(conexao)):
    return db.linhas(con.execute(
        """SELECT m.*, p.sku, p.descricao, l.lote FROM movimentos m
           JOIN lotes l ON l.id=m.lote_id JOIN produtos p ON p.id=l.produto_id
           ORDER BY m.id DESC LIMIT ?""", (limite,)))


@app.get("/api/tags/{epc}")
def consultar_tag(epc: str, con: Con = Depends(conexao)):
    return dict(estoque.buscar_tag(con, epc))


# ================================================================ entrada
class Entrada(BaseModel):
    produto_id: Optional[int] = None
    codigo: Optional[str] = None          # EAN lido pelo leitor de código de barras
    lote: str = ""
    validade: Optional[str] = None        # AAAA-MM-DD
    quantidade: float = 0
    epcs: list[str] = []                  # tags RFID lidas (1 tag = 1 unidade)
    origem: Origem = "PC"
    meio: Meio = "MANUAL"


@app.post("/api/entradas")
def entrada(e: Entrada, con: Con = Depends(conexao)):
    p = estoque.buscar_produto(con, e.produto_id, e.codigo)
    return estoque.entrada(con, p["id"], e.lote, e.validade, e.quantidade, e.epcs, e.origem, e.meio)


# ================================================================ baixa
class Baixa(BaseModel):
    epcs: list[str] = []                  # baixa por RFID
    produto_id: Optional[int] = None      # ou baixa por quantidade (lotes escolhidos por FEFO)
    codigo: Optional[str] = None
    quantidade: float = 0
    motivo: str = "CONSUMO"
    origem: Origem = "PC"
    meio: Meio = "MANUAL"


@app.get("/api/fefo")
def fefo(produto_id: int, quantidade: float, motivo: str = "CONSUMO", con: Con = Depends(conexao)):
    """Mostra de quais lotes a baixa vai sair, sem baixar nada."""
    return estoque.sugerir_fefo(con, produto_id, quantidade, usar_vencidos=(motivo == "VENCIMENTO"))


@app.post("/api/baixas")
def baixa(b: Baixa, con: Con = Depends(conexao)):
    if b.epcs:
        # Várias tags de uma vez: cada uma dá certo ou errado sozinha.
        resultado = []
        for epc in b.epcs:
            con.execute("SAVEPOINT tag")
            try:
                resultado.append({"ok": True, **estoque.baixa_tag(con, epc, b.motivo, b.origem)})
                con.execute("RELEASE tag")
            except ErroEstoque as erro:
                con.execute("ROLLBACK TO tag")
                con.execute("RELEASE tag")
                resultado.append({"ok": False, "epc": epc, "erro": str(erro)})
        return {"tags": resultado}
    p = estoque.buscar_produto(con, b.produto_id, b.codigo)
    return estoque.baixa_quantidade(con, p["id"], b.quantidade, b.motivo, b.origem, b.meio)


# ================================================================ inventário
class NovoInventario(BaseModel):
    nome: str


class Contagem(BaseModel):
    epcs: list[str] = []                  # contagem por RFID
    lote_id: Optional[int] = None         # ou contagem por quantidade de um lote
    quantidade: Optional[float] = None
    origem: Origem = "PC"
    meio: Meio = "MANUAL"


@app.get("/api/inventarios")
def listar_inventarios(con: Con = Depends(conexao)):
    return db.linhas(con.execute(
        """SELECT i.*, (SELECT COUNT(*) FROM contagens c WHERE c.inventario_id=i.id) AS itens
           FROM inventarios i ORDER BY i.id DESC"""))


@app.post("/api/inventarios")
def abrir_inventario(inv: NovoInventario, con: Con = Depends(conexao)):
    cur = con.execute("INSERT INTO inventarios (nome, aberto_em) VALUES (?,?)", (inv.nome.strip(), db.agora()))
    return {"id": cur.lastrowid}


@app.get("/api/inventarios/{inventario_id}")
def ver_inventario(inventario_id: int, con: Con = Depends(conexao)):
    inv = con.execute("SELECT * FROM inventarios WHERE id=?", (inventario_id,)).fetchone()
    if not inv:
        raise HTTPException(404, "Inventário não encontrado")
    contagens = db.linhas(con.execute(
        """SELECT c.*, p.sku, p.descricao, l.lote FROM contagens c
           JOIN lotes l ON l.id=c.lote_id JOIN produtos p ON p.id=l.produto_id
           WHERE c.inventario_id=? ORDER BY c.id DESC""", (inventario_id,)))
    return {"inventario": dict(inv), "confronto": estoque.confrontar(con, inventario_id), "contagens": contagens}


@app.post("/api/inventarios/{inventario_id}/contagens")
def contar(inventario_id: int, c: Contagem, con: Con = Depends(conexao)):
    if c.epcs:
        resultado = []
        for epc in c.epcs:
            try:
                resultado.append({"ok": True, **estoque.contar_tag(con, inventario_id, epc, c.origem)})
            except ErroEstoque as erro:
                resultado.append({"ok": False, "epc": epc, "erro": str(erro)})
        return {"tags": resultado}
    return estoque.contar_quantidade(con, inventario_id, c.lote_id, c.quantidade, c.origem, c.meio)


@app.delete("/api/inventarios/{inventario_id}/contagens/{contagem_id}")
def remover_contagem(inventario_id: int, contagem_id: int, con: Con = Depends(conexao)):
    estoque.inventario_aberto(con, inventario_id)
    con.execute("DELETE FROM contagens WHERE id=? AND inventario_id=?", (contagem_id, inventario_id))
    return {"ok": True}


@app.post("/api/inventarios/{inventario_id}/fechar")
def fechar_inventario(inventario_id: int, con: Con = Depends(conexao)):
    return estoque.fechar_inventario(con, inventario_id)
