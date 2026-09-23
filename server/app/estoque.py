"""Regras do estoque. Toda a lógica fica aqui, no servidor.

O PC e o coletor chamam as mesmas funções, então uma baixa feita
no coletor se comporta igual a uma baixa feita no PC.
"""
from . import db


class ErroEstoque(Exception):
    """Erro de regra de negócio (mensagem mostrada ao usuário)."""


# ----------------------------------------------------------------- buscas
def buscar_produto(con, produto_id=None, codigo=None):
    """Acha o produto pelo id ou por um código lido (EAN do código de barras ou SKU)."""
    if produto_id:
        p = con.execute("SELECT * FROM produtos WHERE id=?", (produto_id,)).fetchone()
    elif codigo:
        codigo = codigo.strip()
        p = con.execute("SELECT * FROM produtos WHERE ean=? OR sku=?", (codigo, codigo)).fetchone()
    else:
        raise ErroEstoque("Informe o produto")
    if not p:
        raise ErroEstoque(f"Produto não encontrado: {codigo or produto_id}")
    return p


def buscar_lote(con, lote_id):
    l = con.execute("SELECT * FROM lotes WHERE id=?", (lote_id,)).fetchone()
    if not l:
        raise ErroEstoque("Lote não encontrado")
    return l


def buscar_tag(con, epc):
    t = con.execute(
        """SELECT t.epc, t.status, l.id AS lote_id, l.lote, l.validade, p.id AS produto_id, p.sku, p.descricao
           FROM tags t JOIN lotes l ON l.id=t.lote_id JOIN produtos p ON p.id=l.produto_id
           WHERE t.epc=?""", (epc.strip().upper(),)).fetchone()
    if not t:
        raise ErroEstoque(f"Tag {epc} não cadastrada")
    return t


def lotes_fefo(con, produto_id):
    """Lotes com saldo, do que vence primeiro para o que vence por último (FEFO)."""
    return con.execute(
        """SELECT * FROM lotes WHERE produto_id=? AND quantidade > 0
           ORDER BY validade IS NULL, validade, id""", (produto_id,)).fetchall()


# ----------------------------------------------------------------- movimento
def movimentar(con, tipo, lote_id, quantidade, origem, meio, motivo=None, epc=None):
    """Altera o saldo de um lote e grava o histórico."""
    lote = buscar_lote(con, lote_id)
    if lote["quantidade"] + quantidade < 0:
        raise ErroEstoque(f"Saldo insuficiente no lote {lote['lote']} (saldo {lote['quantidade']:g})")
    con.execute("UPDATE lotes SET quantidade = quantidade + ? WHERE id=?", (quantidade, lote_id))
    con.execute(
        """INSERT INTO movimentos (data_hora, tipo, lote_id, quantidade, epc, origem, meio, motivo)
           VALUES (?,?,?,?,?,?,?,?)""",
        (db.agora(), tipo, lote_id, quantidade, epc, origem, meio, motivo))


# ----------------------------------------------------------------- entrada
def entrada(con, produto_id, lote, validade, quantidade=0, epcs=(), origem="PC", meio="MANUAL"):
    """Entrada de estoque. Com tags RFID, cada EPC lido vale 1 unidade."""
    p = buscar_produto(con, produto_id)
    lote = (lote or "").strip().upper() or "SEM-LOTE"
    epcs = sorted({e.strip().upper() for e in epcs if e.strip()})
    if epcs:
        quantidade = len(epcs)
    if not quantidade or quantidade <= 0:
        raise ErroEstoque("Quantidade deve ser maior que zero")

    existente = con.execute("SELECT * FROM lotes WHERE produto_id=? AND lote=?", (p["id"], lote)).fetchone()
    if existente:
        lote_id = existente["id"]
        if validade and existente["validade"] and validade != existente["validade"]:
            raise ErroEstoque(f"Lote {lote} já existe com validade {existente['validade']}")
    else:
        lote_id = con.execute("INSERT INTO lotes (produto_id, lote, validade) VALUES (?,?,?)",
                              (p["id"], lote, validade or None)).lastrowid

    for epc in epcs:
        t = con.execute("SELECT status FROM tags WHERE epc=?", (epc,)).fetchone()
        if t and t["status"] == "ATIVA":
            raise ErroEstoque(f"Tag {epc} já está em estoque")
        con.execute("INSERT OR REPLACE INTO tags (epc, lote_id, status) VALUES (?,?,'ATIVA')", (epc, lote_id))
        movimentar(con, "ENTRADA", lote_id, 1, origem, "RFID", epc=epc)
    if not epcs:
        movimentar(con, "ENTRADA", lote_id, quantidade, origem, meio)
    return {"sku": p["sku"], "lote": lote, "quantidade": quantidade}


# ----------------------------------------------------------------- baixa
def sugerir_fefo(con, produto_id, quantidade, usar_vencidos=False):
    """Quanto tirar de cada lote, começando pelo que vence primeiro.

    Lotes vencidos ficam de fora, a não ser na baixa por motivo VENCIMENTO.
    """
    if not quantidade or quantidade <= 0:
        raise ErroEstoque("Quantidade deve ser maior que zero")
    falta, plano = quantidade, []
    for l in lotes_fefo(con, produto_id):
        if vencido(l) != usar_vencidos:
            continue
        tirar = min(l["quantidade"], falta)
        plano.append({"lote_id": l["id"], "lote": l["lote"], "validade": l["validade"], "quantidade": tirar})
        falta -= tirar
        if falta <= 0:
            return plano
    tipo = "vencido" if usar_vencidos else "dentro da validade"
    raise ErroEstoque(f"Estoque {tipo} insuficiente: disponível {quantidade - falta:g}, pedido {quantidade:g}")


def baixa_quantidade(con, produto_id, quantidade, motivo, origem="PC", meio="MANUAL"):
    """Baixa por quantidade (PC ou código de barras): o sistema escolhe os lotes por FEFO."""
    plano = sugerir_fefo(con, produto_id, quantidade, usar_vencidos=(motivo == "VENCIMENTO"))
    for item in plano:
        movimentar(con, "BAIXA", item["lote_id"], -item["quantidade"], origem, meio, motivo)
    return {"lotes": plano, "avisos": []}


def baixa_tag(con, epc, motivo, origem="COLETOR"):
    """Baixa por RFID: a tag diz exatamente qual lote está saindo."""
    t = buscar_tag(con, epc)
    if t["status"] != "ATIVA":
        raise ErroEstoque(f"Tag {t['epc']} já foi baixada")
    con.execute("UPDATE tags SET status='BAIXADA' WHERE epc=?", (t["epc"],))
    movimentar(con, "BAIXA", t["lote_id"], -1, origem, "RFID", motivo, t["epc"])
    avisos = avisos_validade([dict(t)])
    # FEFO: existe outro lote (ainda válido) que vence antes deste?
    validos = [l for l in lotes_fefo(con, t["produto_id"]) if not vencido(l)]
    if validos and validos[0]["validade"] and t["validade"] and validos[0]["validade"] < t["validade"]:
        avisos.append(f"FEFO: o lote {validos[0]['lote']} vence antes ({validos[0]['validade']})")
    return {"epc": t["epc"], "sku": t["sku"], "lote": t["lote"], "avisos": avisos}


def vencido(lote) -> bool:
    return bool(lote["validade"]) and lote["validade"] < db.hoje()


def avisos_validade(lotes):
    return [f"Lote {l['lote']} VENCIDO em {l['validade']}" for l in lotes if vencido(l)]


# ----------------------------------------------------------------- inventário
def inventario_aberto(con, inventario_id):
    inv = con.execute("SELECT * FROM inventarios WHERE id=?", (inventario_id,)).fetchone()
    if not inv:
        raise ErroEstoque("Inventário não encontrado")
    if inv["status"] != "ABERTO":
        raise ErroEstoque("Inventário já fechado")
    return inv


def contar_tag(con, inventario_id, epc, origem="COLETOR"):
    inventario_aberto(con, inventario_id)
    t = buscar_tag(con, epc)
    if con.execute("SELECT 1 FROM contagens WHERE inventario_id=? AND epc=?", (inventario_id, t["epc"])).fetchone():
        return {"epc": t["epc"], "sku": t["sku"], "lote": t["lote"], "repetida": True}
    con.execute(
        """INSERT INTO contagens (inventario_id, lote_id, quantidade, epc, origem, meio, data_hora)
           VALUES (?,?,1,?,?,'RFID',?)""", (inventario_id, t["lote_id"], t["epc"], origem, db.agora()))
    return {"epc": t["epc"], "sku": t["sku"], "lote": t["lote"], "repetida": False}


def contar_quantidade(con, inventario_id, lote_id, quantidade, origem="PC", meio="MANUAL"):
    inventario_aberto(con, inventario_id)
    l = buscar_lote(con, lote_id)
    if quantidade is None or quantidade < 0:
        raise ErroEstoque("Quantidade inválida")
    con.execute(
        """INSERT INTO contagens (inventario_id, lote_id, quantidade, origem, meio, data_hora)
           VALUES (?,?,?,?,?,?)""", (inventario_id, lote_id, quantidade, origem, meio, db.agora()))
    return {"lote": l["lote"], "quantidade": quantidade}


def confrontar(con, inventario_id):
    """Compara o contado (físico) com o saldo do sistema, lote a lote."""
    return db.linhas(con.execute(
        """SELECT l.id AS lote_id, p.sku, p.descricao, l.lote, l.validade,
                  l.quantidade AS sistema,
                  COALESCE(c.contado, 0) AS contado,
                  COALESCE(c.contado, 0) - l.quantidade AS diferenca
           FROM lotes l
           JOIN produtos p ON p.id = l.produto_id
           LEFT JOIN (SELECT lote_id, SUM(quantidade) AS contado FROM contagens
                      WHERE inventario_id=? GROUP BY lote_id) c ON c.lote_id = l.id
           WHERE l.quantidade <> 0 OR c.contado IS NOT NULL
           ORDER BY p.sku, l.validade""", (inventario_id,)))


def fechar_inventario(con, inventario_id, origem="PC"):
    """Aplica as diferenças: o saldo do sistema passa a ser o que foi contado."""
    inventario_aberto(con, inventario_id)
    ajustes = 0
    for item in confrontar(con, inventario_id):
        if item["diferenca"] != 0:
            movimentar(con, "AJUSTE", item["lote_id"], item["diferenca"], origem, "MANUAL",
                       f"Inventário {inventario_id}")
            ajustes += 1
    # Tags lidas no inventário estão fisicamente no estoque.
    con.execute("""UPDATE tags SET status='ATIVA'
                   WHERE epc IN (SELECT epc FROM contagens WHERE inventario_id=? AND epc IS NOT NULL)""",
                (inventario_id,))
    con.execute("UPDATE inventarios SET status='FECHADO', fechado_em=? WHERE id=?", (db.agora(), inventario_id))
    return {"ajustes": ajustes}
