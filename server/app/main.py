"""Mini WMS RFID — servidor que roda no PC.

Iniciar:   uvicorn app.main:app --host 0.0.0.0 --port 8000
Tela web:  http://localhost:8000
O coletor Zebra acessa a mesma API pelo IP do PC na rede Wi-Fi.
"""
import csv
import io
import os
import sqlite3
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, estoque, relatorios, remoto
from .estoque import MOTIVOS_BAIXA, ErroEstoque

STATIC = os.path.join(os.path.dirname(__file__), "static")
# Telas sem cache: o navegador/coletor sempre pega a versão mais nova da tela
SEM_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}
Origem = Literal["PC", "COLETOR"]
Meio = Literal["MANUAL", "BARRAS", "RFID"]
Motivo = Literal["CONSUMO", "VENDA", "AVARIA", "PERDA", "VENCIMENTO", "DEVOLUCAO"]
TipoEndereco = Literal["RECEBIMENTO", "ARMAZENAGEM", "EXPEDICAO"]


@asynccontextmanager
async def iniciar(_app):
    db.inicializar()
    yield


app = FastAPI(title="Mini WMS RFID", lifespan=iniciar)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.exception_handler(ErroEstoque)
def erro_estoque(_req: Request, exc: ErroEstoque):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(RequestValidationError)
def erro_validacao(_req: Request, exc: RequestValidationError):
    """Transforma o erro de validação do FastAPI em uma frase para o usuário."""
    e = exc.errors()[0]
    campo = ".".join(str(x) for x in e["loc"] if x not in ("body", "query"))
    return JSONResponse(status_code=400, content={"detail": f"Campo inválido: {campo} ({e['msg']})"})


def conexao(request: Request):
    """Uma conexão por requisição; grava tudo no final (ou desfaz se deu erro).

    Requisições que alteram dados começam com BEGIN IMMEDIATE: duas baixas ao
    mesmo tempo (PC e coletor) são feitas uma depois da outra, sem furar o saldo.
    """
    con = db.conectar()
    try:
        if request.method != "GET":
            con.execute("BEGIN IMMEDIATE")
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


Con = sqlite3.Connection


def csv_resposta(nome, colunas, linhas):
    """Arquivo CSV (abre no Excel: separador ; e acentos em UTF-8 com BOM)."""
    saida = io.StringIO()
    saida.write("﻿")
    w = csv.writer(saida, delimiter=";")
    w.writerow([titulo for titulo, _ in colunas])
    for l in linhas:
        w.writerow([str(l[campo]).replace(".", ",") if isinstance(l[campo], float) else
                    ("" if l[campo] is None else l[campo]) for _, campo in colunas])
    return StreamingResponse(iter([saida.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{nome}"'})


@app.get("/", include_in_schema=False)
def pagina_inicial():
    return FileResponse(os.path.join(STATIC, "index.html"), headers=SEM_CACHE)


@app.get("/m", include_in_schema=False)
def tela_coletor():
    """Tela do coletor pelo navegador (Chrome + DataWedge com RFID Input)."""
    return FileResponse(os.path.join(STATIC, "m.html"), headers=SEM_CACHE)


@app.get("/api/status")
def status(request: Request):
    """O coletor usa para testar a conexão e para achar o servidor na rede ("servidor": "Mini WMS")."""
    porta = request.url.port or 8000
    return {"ok": True, "servidor": "Mini WMS", "data_hora": db.agora(), "motivos": MOTIVOS_BAIXA,
            "coletor": f"http://{db.ip_da_rede()}:{porta}", "banco": os.path.abspath(db.DB_PATH), "aviso": db.AVISO}


# ================================================================ painel
@app.get("/api/resumo")
def resumo(con: Con = Depends(conexao)):
    """Indicadores do painel inicial."""
    hoje = db.hoje()

    def valor(sql, *args):
        return con.execute(sql, args).fetchone()[0] or 0

    abaixo = db.linhas(con.execute(
        """SELECT p.id, p.sku, p.descricao, p.unidade, p.estoque_min, COALESCE(SUM(l.quantidade), 0) AS saldo
           FROM produtos p LEFT JOIN lotes l ON l.produto_id=p.id
           WHERE p.ativo=1 AND p.estoque_min > 0
           GROUP BY p.id HAVING saldo < p.estoque_min ORDER BY p.descricao"""))
    validade = db.linhas(con.execute(
        """SELECT l.id AS lote_id, p.sku, p.descricao, l.lote, l.validade, l.quantidade, e.codigo AS endereco,
                  CAST(julianday(l.validade) - julianday(?) AS INTEGER) AS dias_para_vencer
           FROM lotes l JOIN produtos p ON p.id=l.produto_id LEFT JOIN enderecos e ON e.id=l.endereco_id
           WHERE l.quantidade > 0 AND l.validade IS NOT NULL AND l.validade <= date(?, '+30 day')
           ORDER BY l.validade""", (hoje, hoje)))
    return {
        "produtos": valor("SELECT COUNT(*) FROM produtos WHERE ativo=1"),
        "unidades": valor("SELECT SUM(quantidade) FROM lotes"),
        "lotes": valor("SELECT COUNT(*) FROM lotes WHERE quantidade > 0"),
        "lotes_bloqueados": valor("SELECT COUNT(*) FROM lotes WHERE quantidade > 0 AND status='BLOQUEADO'"),
        "na_doca": valor("""SELECT COUNT(*) FROM lotes l JOIN enderecos e ON e.id=l.endereco_id
                            WHERE l.quantidade > 0 AND e.tipo='RECEBIMENTO'"""),
        "vencidos": sum(1 for v in validade if v["dias_para_vencer"] < 0),
        "a_vencer": sum(1 for v in validade if v["dias_para_vencer"] >= 0),
        "pedidos_abertos": valor("SELECT COUNT(*) FROM pedidos WHERE status IN ('ABERTO','SEPARANDO')"),
        "recebimentos_abertos": valor("SELECT COUNT(*) FROM recebimentos WHERE status='ABERTO'"),
        "inventarios_abertos": valor("SELECT COUNT(*) FROM inventarios WHERE status='ABERTO'"),
        "entradas_hoje": valor("SELECT SUM(quantidade) FROM movimentos WHERE tipo='ENTRADA' AND data_hora >= ?", hoje),
        "saidas_hoje": -valor("SELECT SUM(quantidade) FROM movimentos WHERE tipo='BAIXA' AND data_hora >= ?", hoje),
        "abaixo_minimo": abaixo,
        "validade": validade,
    }


# ================================================================ limpar tudo
class Limpeza(BaseModel):
    manter_cadastros: bool = False


@app.post("/api/limpar-tudo")
def limpar_tudo(opcoes: Limpeza, con: Con = Depends(conexao)):
    """Apaga os dados para recomeçar (produtos e endereços opcionais)."""
    return estoque.limpar_tudo(con, opcoes.manter_cadastros)


# ================================================================ produtos
class Produto(BaseModel):
    sku: str = Field(min_length=1, max_length=40)
    descricao: str = Field(min_length=1, max_length=120)
    ean: Optional[str] = None
    unidade: str = Field(default="UN", min_length=1, max_length=6)
    estoque_min: float = Field(default=0, ge=0)
    ativo: bool = True


def salvar_produto(con, p: Produto, produto_id=None):
    sku, ean = p.sku.strip().upper(), (p.ean or "").strip() or None
    if not sku or not p.descricao.strip():
        raise ErroEstoque("SKU e descrição são obrigatórios")
    if ean and con.execute("SELECT 1 FROM produtos WHERE ean=? AND id<>?", (ean, produto_id or 0)).fetchone():
        raise ErroEstoque(f"EAN {ean} já pertence a outro produto")
    dados = (sku, p.descricao.strip(), ean, p.unidade.strip().upper(), p.estoque_min, int(p.ativo))
    try:
        if produto_id:
            con.execute("UPDATE produtos SET sku=?, descricao=?, ean=?, unidade=?, estoque_min=?, ativo=? WHERE id=?",
                        (*dados, produto_id))
            return produto_id
        return con.execute("INSERT INTO produtos (sku, descricao, ean, unidade, estoque_min, ativo) VALUES (?,?,?,?,?,?)",
                           dados).lastrowid
    except sqlite3.IntegrityError:
        raise ErroEstoque(f"SKU {sku} já cadastrado")


@app.get("/api/produtos")
def listar_produtos(con: Con = Depends(conexao)):
    return db.linhas(con.execute(
        """SELECT p.*, COALESCE(SUM(l.quantidade), 0) AS saldo
           FROM produtos p LEFT JOIN lotes l ON l.produto_id=p.id
           GROUP BY p.id ORDER BY p.descricao"""))


@app.get("/api/produtos/busca")
def buscar_produto(codigo: str, con: Con = Depends(conexao)):
    """Produto pelo código de barras (EAN) ou SKU, com seus lotes em ordem FEFO."""
    p = estoque.buscar_produto(con, codigo=codigo)
    lotes = db.linhas(con.execute(
        """SELECT l.*, e.codigo AS endereco FROM lotes l LEFT JOIN enderecos e ON e.id=l.endereco_id
           WHERE l.produto_id=? ORDER BY l.quantidade <= 0, l.validade IS NULL, l.validade""", (p["id"],)))
    return {**dict(p), "lotes": lotes}


@app.post("/api/produtos")
def criar_produto(p: Produto, con: Con = Depends(conexao)):
    return {"id": salvar_produto(con, p)}


@app.put("/api/produtos/{produto_id}")
def editar_produto(produto_id: int, p: Produto, con: Con = Depends(conexao)):
    estoque.buscar_produto(con, produto_id)
    salvar_produto(con, p, produto_id)
    return {"ok": True}


@app.delete("/api/produtos/{produto_id}")
def excluir_produto(produto_id: int, con: Con = Depends(conexao)):
    """Exclui o produto e tudo que depende dele: lotes, tags, movimentos, contagens e itens de pedido."""
    return estoque.excluir_produto(con, produto_id)


# ================================================================ endereços
class Endereco(BaseModel):
    codigo: str = Field(min_length=1, max_length=20)
    descricao: Optional[str] = None
    tipo: TipoEndereco = "ARMAZENAGEM"
    ativo: bool = True


@app.get("/api/enderecos")
def listar_enderecos(con: Con = Depends(conexao)):
    return db.linhas(con.execute(
        """SELECT e.*, COUNT(l.id) AS lotes, COALESCE(SUM(l.quantidade), 0) AS quantidade
           FROM enderecos e LEFT JOIN lotes l ON l.endereco_id=e.id AND l.quantidade > 0
           GROUP BY e.id ORDER BY e.id"""))


def renomear_local(con, endereco_id, antigo, novo):
    """Local renomeado: o histórico e o "lote" com o nome do local passam a usar o nome novo."""
    con.execute("UPDATE movimentos SET endereco=? WHERE endereco=?", (novo, antigo))
    con.execute("""UPDATE lotes SET lote=? WHERE endereco_id=? AND lote=?
                   AND NOT EXISTS (SELECT 1 FROM lotes l2 WHERE l2.produto_id=lotes.produto_id AND l2.lote=?)""",
                (novo, endereco_id, antigo, novo))


def salvar_endereco(con, e: Endereco, endereco_id=None):
    codigo = e.codigo.strip()
    if con.execute("SELECT 1 FROM enderecos WHERE UPPER(codigo)=UPPER(?) AND id<>?", (codigo, endereco_id or 0)).fetchone():
        raise ErroEstoque(f"Local {codigo} já cadastrado")
    if endereco_id and not e.ativo and con.execute(
            "SELECT 1 FROM lotes WHERE endereco_id=? AND quantidade > 0", (endereco_id,)).fetchone():
        raise ErroEstoque(f"Local {codigo} tem estoque: mova os itens antes de inativar")
    dados = (codigo, (e.descricao or "").strip() or None, e.tipo, int(e.ativo))
    try:
        if endereco_id:
            antigo = con.execute("SELECT codigo FROM enderecos WHERE id=?", (endereco_id,)).fetchone()
            con.execute("UPDATE enderecos SET codigo=?, descricao=?, tipo=?, ativo=? WHERE id=?", (*dados, endereco_id))
            if antigo and antigo[0] != codigo:
                renomear_local(con, endereco_id, antigo[0], codigo)
            return endereco_id
        return con.execute("INSERT INTO enderecos (codigo, descricao, tipo, ativo) VALUES (?,?,?,?)", dados).lastrowid
    except sqlite3.IntegrityError:
        raise ErroEstoque(f"Local {codigo} já cadastrado")


@app.post("/api/enderecos")
def criar_endereco(e: Endereco, con: Con = Depends(conexao)):
    return {"id": salvar_endereco(con, e)}


@app.put("/api/enderecos/{endereco_id}")
def editar_endereco(endereco_id: int, e: Endereco, con: Con = Depends(conexao)):
    atual = con.execute("SELECT * FROM enderecos WHERE id=?", (endereco_id,)).fetchone()
    if not atual:
        raise HTTPException(404, "Endereço não encontrado")
    if atual["codigo"] == db.LOCAL_PADRAO and (e.codigo.strip() != db.LOCAL_PADRAO or not e.ativo):
        raise ErroEstoque(f"O {db.LOCAL_PADRAO} (local padrão) não pode ser renomeado nem inativado")
    salvar_endereco(con, e, endereco_id)
    return {"ok": True}


@app.delete("/api/enderecos/{endereco_id}")
def excluir_endereco(endereco_id: int, con: Con = Depends(conexao)):
    e = con.execute("SELECT * FROM enderecos WHERE id=?", (endereco_id,)).fetchone()
    if e and e["codigo"] == db.LOCAL_PADRAO:
        raise ErroEstoque(f"O {db.LOCAL_PADRAO} (local padrão) não pode ser excluído")
    if con.execute("SELECT 1 FROM lotes WHERE endereco_id=? AND quantidade > 0", (endereco_id,)).fetchone():
        raise ErroEstoque("O local tem itens: mova os itens antes de excluir")
    if con.execute("SELECT 1 FROM lotes WHERE endereco_id=?", (endereco_id,)).fetchone():
        raise ErroEstoque("O local já teve movimentação: em vez de excluir, marque como inativo")
    con.execute("DELETE FROM enderecos WHERE id=?", (endereco_id,))
    return {"ok": True}


# ================================================================ Dash, mover itens e relatórios
class ItemMover(BaseModel):
    produto_id: int
    local_id: int


class Mover(BaseModel):
    itens: list[ItemMover]
    destino_id: int


@app.get("/api/dash")
def dash(con: Con = Depends(conexao)):
    """Cada local com a quantidade total e os itens (Dash do PC)."""
    return estoque.estoque_por_local(con)


@app.post("/api/mover")
def mover(m: Mover, con: Con = Depends(conexao)):
    """Move itens de um local para outro (só pelo PC)."""
    return estoque.mover_itens(con, [i.model_dump() for i in m.itens], m.destino_id)


@app.get("/api/relatorios/estoque.pdf", include_in_schema=False)
def relatorio_estoque(con: Con = Depends(conexao)):
    return Response(relatorios.pdf_estoque(estoque.estoque_por_local(con)), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="estoque_{db.hoje()}.pdf"'})


@app.get("/api/relatorios/movimentos.pdf", include_in_schema=False)
def relatorio_movimentos(produto_id: Optional[int] = None, tipo: Optional[str] = None, de: Optional[str] = None,
                         ate: Optional[str] = None, busca: Optional[str] = None, con: Con = Depends(conexao)):
    movs = filtrar_movimentos(con, produto_id, tipo, de, ate, busca, 5000)
    filtros = " ".join(x for x in (f"· tipo {tipo}" if tipo else "", f"· de {de}" if de else "",
                                     f"· até {ate}" if ate else "", f"· busca '{busca}'" if busca else "") if x)
    return Response(relatorios.pdf_movimentos(movs, filtros), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="historico_{db.hoje()}.pdf"'})


# ================================================================ posição de estoque e lotes
SQL_ESTOQUE = """
    SELECT p.id AS produto_id, p.sku, p.descricao, p.unidade, p.estoque_min, p.ativo,
           l.id AS lote_id, l.lote, l.validade, l.quantidade, l.status,
           e.id AS endereco_id, e.codigo AS endereco, e.tipo AS tipo_endereco,
           CAST(julianday(l.validade) - julianday(?) AS INTEGER) AS dias_para_vencer,
           (SELECT COUNT(*) FROM tags t WHERE t.lote_id=l.id AND t.status='ATIVA') AS tags,
           (SELECT COALESCE(SUM(r.quantidade), 0) FROM reservas r WHERE r.lote_id=l.id) AS reservado
    FROM produtos p
    LEFT JOIN lotes l ON l.produto_id=p.id AND l.quantidade > 0
    LEFT JOIN enderecos e ON e.id=l.endereco_id
    WHERE p.ativo=1 OR l.id IS NOT NULL
    ORDER BY p.descricao, l.validade IS NULL, l.validade"""


@app.get("/api/estoque")
def posicao_estoque(con: Con = Depends(conexao)):
    """Saldo por produto e lote, em ordem de validade (FEFO)."""
    return db.linhas(con.execute(SQL_ESTOQUE, (db.hoje(),)))


@app.get("/api/estoque.csv", include_in_schema=False)
def exportar_estoque(con: Con = Depends(conexao)):
    linhas = [l for l in db.linhas(con.execute(SQL_ESTOQUE, (db.hoje(),))) if l["lote_id"]]
    return csv_resposta(f"estoque_{db.hoje()}.csv", [
        ("SKU", "sku"), ("Produto", "descricao"), ("Unidade", "unidade"), ("Lote", "lote"),
        ("Validade", "validade"), ("Endereco", "endereco"), ("Status", "status"), ("Saldo", "quantidade"),
        ("Reservado", "reservado"), ("Tags RFID", "tags")], linhas)


class Transferencia(BaseModel):
    endereco_id: Optional[int] = None
    endereco: Optional[str] = None        # ou o código do endereço (lido no coletor)
    origem: Origem = "PC"
    meio: Meio = "MANUAL"


class Bloqueio(BaseModel):
    motivo: str = ""


@app.post("/api/lotes/{lote_id}/transferir")
def transferir(lote_id: int, t: Transferencia, con: Con = Depends(conexao)):
    destino = estoque.buscar_endereco(con, t.endereco_id, t.endereco)
    return estoque.transferir(con, lote_id, destino["id"], t.origem, t.meio)


@app.post("/api/lotes/{lote_id}/bloquear")
def bloquear(lote_id: int, b: Bloqueio, con: Con = Depends(conexao)):
    return estoque.bloquear_lote(con, lote_id, b.motivo)


@app.post("/api/lotes/{lote_id}/liberar")
def liberar(lote_id: int, con: Con = Depends(conexao)):
    return estoque.liberar_lote(con, lote_id)


@app.get("/api/tags")
def listar_tags(status: Optional[str] = None, endereco_id: Optional[int] = None, limite: int = 200,
                con: Con = Depends(conexao)):
    """Etiquetas RFID (filtro por status e por local; a Consulta do coletor usa)."""
    where, args = [], []
    if status:
        where.append("t.status=?"); args.append(status)
    if endereco_id:
        where.append("l.endereco_id=?"); args.append(endereco_id)
    return db.linhas(con.execute(
        f"""SELECT t.epc, t.status, l.lote, l.endereco_id, p.id AS produto_id, p.sku, p.descricao FROM tags t
            JOIN lotes l ON l.id=t.lote_id JOIN produtos p ON p.id=l.produto_id
            {"WHERE " + " AND ".join(where) if where else ""} ORDER BY p.sku, l.lote, t.epc LIMIT ?""",
        (*args, min(max(limite, 1), 5000))))


class Regravacao(BaseModel):
    antigo: str
    novo: str


@app.post("/api/tags/regravar")
def regravar_tag(r: Regravacao, con: Con = Depends(conexao)):
    """Etiqueta regravada no coletor: o cadastro passa a usar o EPC novo."""
    return estoque.regravar_tag(con, r.antigo, r.novo)


@app.post("/api/tags/{epc}/estornar")
def estornar_tag(epc: str, con: Con = Depends(conexao)):
    """Desfaz a baixa de uma etiqueta lida por engano."""
    return estoque.estornar_baixa_tag(con, epc)


@app.get("/api/tags/{epc}")
def consultar_tag(epc: str, con: Con = Depends(conexao)):
    return dict(estoque.buscar_tag(con, epc))


# ================================================================ movimentos (kardex)
def filtrar_movimentos(con, produto_id=None, tipo=None, de=None, ate=None, busca=None, limite=500):
    where, args = [], []
    if produto_id:
        where.append("p.id=?"); args.append(produto_id)
    if tipo:
        where.append("m.tipo=?"); args.append(tipo)
    if de:
        where.append("m.data_hora >= ?"); args.append(de)
    if ate:
        where.append("m.data_hora < date(?, '+1 day')"); args.append(ate)
    if busca:
        where.append("(p.sku LIKE ? OR p.descricao LIKE ? OR l.lote LIKE ? OR m.documento LIKE ? OR m.epc LIKE ?)")
        args += [f"%{busca.strip()}%"] * 5
    sql = f"""SELECT m.*, p.sku, p.descricao, l.lote FROM movimentos m
              JOIN lotes l ON l.id=m.lote_id JOIN produtos p ON p.id=l.produto_id
              {"WHERE " + " AND ".join(where) if where else ""}
              ORDER BY m.id DESC LIMIT ?"""
    return db.linhas(con.execute(sql, (*args, min(max(limite, 1), 5000))))


@app.get("/api/movimentos")
def movimentos(limite: int = 200, produto_id: Optional[int] = None, tipo: Optional[str] = None,
               de: Optional[str] = None, ate: Optional[str] = None, busca: Optional[str] = None,
               con: Con = Depends(conexao)):
    return filtrar_movimentos(con, produto_id, tipo, de, ate, busca, limite)


@app.get("/api/movimentos.csv", include_in_schema=False)
def exportar_movimentos(produto_id: Optional[int] = None, tipo: Optional[str] = None, de: Optional[str] = None,
                        ate: Optional[str] = None, busca: Optional[str] = None, con: Con = Depends(conexao)):
    return csv_resposta(f"movimentos_{db.hoje()}.csv", [
        ("Data/hora", "data_hora"), ("Tipo", "tipo"), ("SKU", "sku"), ("Produto", "descricao"), ("Lote", "lote"),
        ("Endereco", "endereco"), ("Quantidade", "quantidade"), ("Saldo do lote", "saldo_apos"),
        ("Documento", "documento"), ("Motivo", "motivo"), ("EPC", "epc"), ("Origem", "origem"), ("Meio", "meio")],
        filtrar_movimentos(con, produto_id, tipo, de, ate, busca, 5000))


# ================================================================ entrada (recebimento)
class Entrada(BaseModel):
    produto_id: Optional[int] = None
    codigo: Optional[str] = None          # EAN lido pelo leitor de código de barras
    lote: str = ""
    validade: Optional[str] = None        # AAAA-MM-DD ou DD/MM/AAAA
    quantidade: float = 0
    epcs: list[str] = []                  # tags RFID lidas (1 tag = 1 unidade)
    endereco_id: Optional[int] = None     # sem endereço: vai para a doca de recebimento
    documento: Optional[str] = None       # nota fiscal
    origem: Origem = "PC"
    meio: Meio = "MANUAL"


@app.post("/api/entradas")
def entrada(e: Entrada, con: Con = Depends(conexao)):
    p = estoque.buscar_produto(con, e.produto_id, e.codigo)
    return estoque.entrada(con, p["id"], e.lote, e.validade, e.quantidade, e.epcs, e.origem, e.meio,
                           e.endereco_id, e.documento)


# ================================================================ baixa
class Baixa(BaseModel):
    epcs: list[str] = []                  # baixa por RFID
    produto_id: Optional[int] = None      # ou baixa por quantidade (lotes escolhidos por FEFO)
    codigo: Optional[str] = None
    lote_id: Optional[int] = None         # ou baixa de um lote escolhido (descarte)
    quantidade: float = 0
    motivo: Motivo = "CONSUMO"
    documento: Optional[str] = None
    endereco_id: Optional[int] = None     # local de onde saem os itens (vazio: qualquer local)
    origem: Origem = "PC"
    meio: Meio = "MANUAL"


@app.get("/api/fefo")
def fefo(produto_id: int, quantidade: float, motivo: str = "CONSUMO", endereco_id: Optional[int] = None,
         con: Con = Depends(conexao)):
    """Mostra de quais lotes a baixa vai sair, sem baixar nada."""
    return estoque.sugerir_fefo(con, produto_id, quantidade, usar_vencidos=(motivo == "VENCIMENTO"), endereco_id=endereco_id)


@app.post("/api/baixas")
def baixa(b: Baixa, con: Con = Depends(conexao)):
    if b.epcs:
        # Várias tags de uma vez: cada uma dá certo ou errado sozinha.
        resultado = []
        for epc in b.epcs:
            con.execute("SAVEPOINT tag")
            try:
                resultado.append({"ok": True, **estoque.baixa_tag(con, epc, b.motivo, b.origem, b.documento, b.endereco_id)})
                con.execute("RELEASE tag")
            except ErroEstoque as erro:
                con.execute("ROLLBACK TO tag")
                con.execute("RELEASE tag")
                resultado.append({"ok": False, "epc": epc, "erro": str(erro)})
        return {"tags": resultado}
    if b.lote_id:
        return estoque.baixa_lote(con, b.lote_id, b.quantidade, b.motivo, b.origem, b.meio, b.documento)
    p = estoque.buscar_produto(con, b.produto_id, b.codigo)
    return estoque.baixa_quantidade(con, p["id"], b.quantidade, b.motivo, b.origem, b.meio, b.documento, b.endereco_id)


# ================================================================ ordens de recebimento
class ItemRecebimento(BaseModel):
    produto_id: Optional[int] = None
    codigo: Optional[str] = None
    lote: str = ""
    validade: Optional[str] = None
    quantidade: float


class NovoRecebimento(BaseModel):
    numero: Optional[str] = None
    documento: Optional[str] = None       # nota fiscal
    fornecedor: Optional[str] = None
    endereco_id: Optional[int] = None
    itens: list[ItemRecebimento]


class LeituraRecebimento(BaseModel):
    item_id: Optional[int] = None         # ou codigo (EAN/SKU do produto) para achar o item
    codigo: Optional[str] = None
    epcs: list[str] = []                  # etiquetas RFID lidas
    quantidade: Optional[float] = None    # ou quantidade (item sem etiqueta)
    origem: Origem = "COLETOR"
    meio: Meio = "RFID"


@app.get("/api/recebimentos")
def listar_recebimentos(con: Con = Depends(conexao)):
    return db.linhas(con.execute(
        """SELECT r.*, e.codigo AS endereco,
                  (SELECT COUNT(*) FROM recebimento_itens i WHERE i.recebimento_id=r.id) AS itens,
                  (SELECT COALESCE(SUM(prevista), 0) FROM recebimento_itens i WHERE i.recebimento_id=r.id) AS prevista,
                  (SELECT COALESCE(SUM(quantidade), 0) FROM recebimento_leituras l WHERE l.recebimento_id=r.id) AS lidas
           FROM recebimentos r LEFT JOIN enderecos e ON e.id=r.endereco_id
           ORDER BY r.status <> 'ABERTO', r.id DESC"""))


@app.post("/api/recebimentos")
def criar_recebimento(r: NovoRecebimento, con: Con = Depends(conexao)):
    return estoque.criar_recebimento(con, [i.model_dump() for i in r.itens], r.documento, r.fornecedor,
                                     r.endereco_id, r.numero)


@app.get("/api/recebimentos/{recebimento_id}")
def ver_recebimento(recebimento_id: int, con: Con = Depends(conexao)):
    rec = estoque.buscar_recebimento(con, recebimento_id)
    endereco = con.execute("SELECT codigo FROM enderecos WHERE id=?", (rec["endereco_id"],)).fetchone()
    leituras = db.linhas(con.execute(
        """SELECT l.*, p.sku, i.lote FROM recebimento_leituras l
           JOIN recebimento_itens i ON i.id=l.item_id JOIN produtos p ON p.id=i.produto_id
           WHERE l.recebimento_id=? ORDER BY l.id DESC""", (recebimento_id,)))
    return {"recebimento": {**dict(rec), "endereco": endereco["codigo"] if endereco else None},
            "itens": estoque.itens_recebimento(con, recebimento_id), "leituras": leituras}


@app.post("/api/recebimentos/{recebimento_id}/leituras")
def ler_recebimento(recebimento_id: int, l: LeituraRecebimento, con: Con = Depends(conexao)):
    return estoque.ler_recebimento(con, recebimento_id, l.item_id, l.epcs, l.quantidade, l.codigo, l.origem, l.meio)


@app.delete("/api/recebimentos/{recebimento_id}/leituras/{leitura_id}")
def remover_leitura_recebimento(recebimento_id: int, leitura_id: int, con: Con = Depends(conexao)):
    return estoque.remover_leitura_recebimento(con, recebimento_id, leitura_id)


@app.post("/api/recebimentos/{recebimento_id}/finalizar")
def finalizar_recebimento(recebimento_id: int, con: Con = Depends(conexao)):
    return estoque.finalizar_recebimento(con, recebimento_id)


@app.post("/api/recebimentos/{recebimento_id}/cancelar")
def cancelar_recebimento(recebimento_id: int, con: Con = Depends(conexao)):
    return estoque.cancelar_recebimento(con, recebimento_id)


# ================================================================ pedidos (expedição)
class ItemPedido(BaseModel):
    produto_id: Optional[int] = None
    codigo: Optional[str] = None
    quantidade: float


class NovoPedido(BaseModel):
    cliente: str
    numero: Optional[str] = None
    observacao: Optional[str] = None
    itens: list[ItemPedido]


@app.get("/api/pedidos")
def listar_pedidos(con: Con = Depends(conexao)):
    return db.linhas(con.execute(
        """SELECT pe.*, COUNT(i.id) AS itens, COALESCE(SUM(i.quantidade), 0) AS unidades
           FROM pedidos pe LEFT JOIN pedido_itens i ON i.pedido_id=pe.id
           GROUP BY pe.id ORDER BY pe.status IN ('EXPEDIDO','CANCELADO'), pe.id DESC"""))


@app.post("/api/pedidos")
def criar_pedido(p: NovoPedido, con: Con = Depends(conexao)):
    return estoque.criar_pedido(con, p.cliente, [i.model_dump() for i in p.itens], p.numero, p.observacao)


@app.get("/api/pedidos/{pedido_id}")
def ver_pedido(pedido_id: int, con: Con = Depends(conexao)):
    ped = estoque.buscar_pedido(con, pedido_id)
    itens = db.linhas(con.execute(
        """SELECT i.*, p.sku, p.descricao, p.unidade,
                  (SELECT COALESCE(SUM(l.quantidade), 0) FROM lotes l WHERE l.produto_id=p.id) AS saldo
           FROM pedido_itens i JOIN produtos p ON p.id=i.produto_id WHERE i.pedido_id=? ORDER BY p.sku""",
        (pedido_id,)))
    # Lista de separação: ordenada por endereço para o separador andar menos
    separacao = db.linhas(con.execute(
        """SELECT r.*, e.codigo AS endereco, l.lote, l.validade, p.sku, p.descricao, p.unidade
           FROM reservas r JOIN lotes l ON l.id=r.lote_id JOIN produtos p ON p.id=l.produto_id
           LEFT JOIN enderecos e ON e.id=l.endereco_id
           WHERE r.pedido_id=? ORDER BY e.codigo, p.sku, l.validade""", (pedido_id,)))
    expedido = []
    if ped["status"] == "EXPEDIDO":
        expedido = db.linhas(con.execute(
            """SELECT m.endereco, l.lote, l.validade, p.sku, p.descricao, p.unidade, -m.quantidade AS quantidade
               FROM movimentos m JOIN lotes l ON l.id=m.lote_id JOIN produtos p ON p.id=l.produto_id
               WHERE m.documento=? AND m.tipo='BAIXA' ORDER BY m.endereco, p.sku""", (ped["numero"],)))
    return {"pedido": dict(ped), "itens": itens, "separacao": separacao or expedido}


@app.post("/api/pedidos/{pedido_id}/liberar")
def liberar_pedido(pedido_id: int, con: Con = Depends(conexao)):
    return estoque.liberar_pedido(con, pedido_id)


@app.post("/api/pedidos/{pedido_id}/expedir")
def expedir_pedido(pedido_id: int, con: Con = Depends(conexao)):
    return estoque.expedir_pedido(con, pedido_id)


@app.post("/api/pedidos/{pedido_id}/cancelar")
def cancelar_pedido(pedido_id: int, con: Con = Depends(conexao)):
    return estoque.cancelar_pedido(con, pedido_id)


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
           FROM inventarios i ORDER BY i.status <> 'ABERTO', i.id DESC"""))


@app.post("/api/inventarios")
def abrir_inventario(inv: NovoInventario, con: Con = Depends(conexao)):
    nome = inv.nome.strip() or f"Inventário {db.hoje()}"
    cur = con.execute("INSERT INTO inventarios (nome, aberto_em) VALUES (?,?)", (nome, db.agora()))
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
    return {"inventario": dict(inv), "confronto": estoque.confrontar(con, inventario_id), "contagens": contagens,
            "etiquetas": estoque.etiquetas_inventario(con, inventario_id)}


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


class IncluirSobras(BaseModel):
    produto_id: int
    epcs: list[str] = []                  # vazio = todas as não cadastradas
    origem: Origem = "PC"


@app.post("/api/inventarios/{inventario_id}/incluir-sobras")
def incluir_sobras(inventario_id: int, i: IncluirSobras, con: Con = Depends(conexao)):
    """Etiquetas a mais (não cadastradas) do inventário entram no estoque como o produto escolhido."""
    return estoque.incluir_sobras(con, inventario_id, i.produto_id, i.epcs, i.origem)


@app.post("/api/inventarios/{inventario_id}/cancelar")
def cancelar_inventario(inventario_id: int, con: Con = Depends(conexao)):
    return estoque.cancelar_inventario(con, inventario_id)


# ================================================================ leitor remoto (o PC aciona o leitor do coletor)
class ComandoRemoto(BaseModel):
    acao: Literal["ler", "parar", "gravar", "limpar"]
    ms: int = 3000                    # ler: por quanto tempo (0 = até mandar parar)
    texto: Optional[str] = None       # gravar: o código que vira o EPC
    potencia: Optional[int] = Field(None, ge=1, le=100)


class LeiturasRemotas(BaseModel):
    epcs: list[str]


class EventoRemoto(BaseModel):
    tipo: str
    dados: dict = {}


@app.post("/api/remoto/comando")
def remoto_comando(c: ComandoRemoto):
    """PC: manda o coletor ler, parar, gravar ou limpar a lista."""
    if c.acao == "gravar":
        texto = (c.texto or "").strip().upper()
        if not texto or len(texto) > 24 or any(ch not in "0123456789ABCDEF" for ch in texto):
            raise ErroEstoque("O código tem que ter até 24 caracteres, só números e letras de A a F")
        c.texto = texto
    return remoto.comando(c.acao, c.ms, c.texto, c.potencia)


@app.get("/api/remoto/comandos")
def remoto_comandos(apos: int = -1):
    """Coletor (tela Leitor do PC): comandos novos do PC."""
    return remoto.comandos_para_coletor(apos)


@app.post("/api/remoto/leituras")
def remoto_leituras(r: LeiturasRemotas):
    """Coletor: etiquetas lidas."""
    return {"total": remoto.registrar_leituras(r.epcs)}


@app.post("/api/remoto/evento")
def remoto_evento(e: EventoRemoto):
    """Coletor: resultado de um comando (gravação, parou de ler)."""
    remoto.registrar_evento(e.tipo, e.dados)
    return {"ok": True}


@app.get("/api/remoto/estado")
def remoto_estado(eventos_apos: int = 0, con: Con = Depends(conexao)):
    """PC: coletor conectado, leituras (com a situação no estoque) e eventos novos."""
    return remoto.estado(con, eventos_apos)
