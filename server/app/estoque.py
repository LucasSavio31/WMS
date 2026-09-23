"""Regras do estoque. Toda a lógica fica aqui, no servidor.

O PC e o coletor chamam as mesmas funções, então uma baixa feita
no coletor se comporta igual a uma baixa feita no PC.

Saldo disponível de um lote (o que a baixa por quantidade pode usar):
    saldo - unidades com etiqueta RFID - quantidade reservada para pedidos
e o lote precisa estar LIBERADO (lote BLOQUEADO fica em quarentena).
"""
from datetime import datetime

from . import db

# Unidades que não aceitam quantidade fracionada (1,5 caixa não existe)
UNIDADES_INTEIRAS = {"UN", "CX", "PC", "PCT", "FD", "DZ"}

MOTIVOS_BAIXA = ["CONSUMO", "VENDA", "AVARIA", "PERDA", "VENCIMENTO", "DEVOLUCAO"]
# Motivos de descarte: podem tirar mercadoria de lote bloqueado
MOTIVOS_DESCARTE = {"AVARIA", "PERDA", "VENCIMENTO"}


class ErroEstoque(Exception):
    """Erro de regra de negócio (mensagem mostrada ao usuário)."""


def fmt(q) -> str:
    return f"{q:g}"


# ----------------------------------------------------------------- validações
def normalizar_data(texto):
    """Aceita AAAA-MM-DD (tela web) ou DD/MM/AAAA (digitado no coletor)."""
    if not texto or not str(texto).strip():
        return None
    texto = str(texto).strip()
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto, formato).strftime("%Y-%m-%d")
        except ValueError:
            pass
    raise ErroEstoque(f"Validade inválida: {texto} (use DD/MM/AAAA)")


def validar_quantidade(produto, quantidade, aceita_zero=False):
    if quantidade is None or quantidade < 0 or (quantidade == 0 and not aceita_zero):
        raise ErroEstoque("Quantidade deve ser maior que zero")
    if produto["unidade"].upper() in UNIDADES_INTEIRAS and quantidade != int(quantidade):
        raise ErroEstoque(f"{produto['sku']} é controlado em {produto['unidade']}: use quantidade inteira")


# ----------------------------------------------------------------- buscas
def buscar_produto(con, produto_id=None, codigo=None):
    """Acha o produto pelo id ou por um código lido (EAN do código de barras ou SKU)."""
    if produto_id:
        p = con.execute("SELECT * FROM produtos WHERE id=?", (produto_id,)).fetchone()
    elif codigo and codigo.strip():
        codigo = codigo.strip()
        p = con.execute("SELECT * FROM produtos WHERE ean=? OR UPPER(sku)=UPPER(?)", (codigo, codigo)).fetchone()
    else:
        raise ErroEstoque("Informe o produto")
    if not p:
        raise ErroEstoque(f"Produto não encontrado: {codigo or produto_id}")
    return p


def produto_ativo(con, produto_id=None, codigo=None):
    p = buscar_produto(con, produto_id, codigo)
    if not p["ativo"]:
        raise ErroEstoque(f"Produto {p['sku']} está inativo")
    return p


def buscar_lote(con, lote_id):
    l = con.execute(
        """SELECT l.*, e.codigo AS endereco FROM lotes l LEFT JOIN enderecos e ON e.id=l.endereco_id
           WHERE l.id=?""", (lote_id,)).fetchone()
    if not l:
        raise ErroEstoque("Lote não encontrado")
    return l


def buscar_endereco(con, endereco_id=None, codigo=None):
    if endereco_id:
        e = con.execute("SELECT * FROM enderecos WHERE id=?", (endereco_id,)).fetchone()
    else:
        e = con.execute("SELECT * FROM enderecos WHERE codigo=?", ((codigo or db.DOCA_RECEBIMENTO).strip().upper(),)).fetchone()
    if not e:
        raise ErroEstoque(f"Endereço não encontrado: {codigo or endereco_id}")
    if not e["ativo"]:
        raise ErroEstoque(f"Endereço {e['codigo']} está inativo")
    return e


def buscar_tag(con, epc):
    t = con.execute(
        """SELECT t.epc, t.status, l.id AS lote_id, l.lote, l.validade, l.status AS status_lote,
                  p.id AS produto_id, p.sku, p.descricao, e.codigo AS endereco
           FROM tags t JOIN lotes l ON l.id=t.lote_id JOIN produtos p ON p.id=l.produto_id
           LEFT JOIN enderecos e ON e.id=l.endereco_id
           WHERE t.epc=?""", (epc.strip().upper(),)).fetchone()
    if not t:
        raise ErroEstoque(f"Tag {epc} não cadastrada")
    return t


def lotes_fefo(con, produto_id):
    """Lotes liberados com saldo, do que vence primeiro para o que vence por último (FEFO)."""
    return con.execute(
        """SELECT l.*, e.codigo AS endereco FROM lotes l LEFT JOIN enderecos e ON e.id=l.endereco_id
           WHERE l.produto_id=? AND l.quantidade > 0 AND l.status='LIBERADO'
           ORDER BY l.validade IS NULL, l.validade, l.id""", (produto_id,)).fetchall()


def qtd_etiquetada(con, lote_id):
    return con.execute("SELECT COUNT(*) FROM tags WHERE lote_id=? AND status='ATIVA'", (lote_id,)).fetchone()[0]


def qtd_reservada(con, lote_id):
    return con.execute("SELECT COALESCE(SUM(quantidade), 0) FROM reservas WHERE lote_id=?", (lote_id,)).fetchone()[0]


def vencido(lote) -> bool:
    return bool(lote["validade"]) and lote["validade"] < db.hoje()


def avisos_validade(lotes):
    return [f"Lote {l['lote']} VENCIDO em {l['validade']}" for l in lotes if vencido(l)]


def excluir_produto(con, produto_id):
    """Apaga o produto mesmo com movimentação (o histórico dele também é apagado).

    Pedidos que ficarem sem nenhum item são apagados junto.
    """
    p = buscar_produto(con, produto_id)
    lotes = "SELECT id FROM lotes WHERE produto_id=?"
    itens = "SELECT id FROM pedido_itens WHERE produto_id=?"
    args = (produto_id,)
    con.execute(f"DELETE FROM reservas WHERE lote_id IN ({lotes}) OR item_id IN ({itens})", args * 2)
    con.execute(f"DELETE FROM contagens WHERE lote_id IN ({lotes})", args)
    con.execute(f"DELETE FROM movimentos WHERE lote_id IN ({lotes})", args)
    con.execute(f"DELETE FROM tags WHERE lote_id IN ({lotes})", args)
    n_lotes = con.execute("DELETE FROM lotes WHERE produto_id=?", args).rowcount
    con.execute("DELETE FROM pedido_itens WHERE produto_id=?", args)
    con.execute("DELETE FROM pedidos WHERE id NOT IN (SELECT pedido_id FROM pedido_itens)")
    con.execute("DELETE FROM produtos WHERE id=?", args)
    return {"ok": True, "sku": p["sku"], "lotes": n_lotes}


def limpar_tudo(con, manter_cadastros=False):
    """Zera o banco (projeto didático: recomeçar do zero para uma nova aula).

    Com manter_cadastros, apaga só a movimentação e deixa produtos e endereços.
    """
    tabelas = ["reservas", "pedido_itens", "pedidos", "contagens", "inventarios", "movimentos", "tags", "lotes"]
    if not manter_cadastros:
        tabelas += ["produtos", "enderecos"]
    for tabela in tabelas:
        con.execute(f"DELETE FROM {tabela}")
    # Os códigos (id) voltam a começar do 1
    con.execute(f"DELETE FROM sqlite_sequence WHERE name IN ({','.join('?' * len(tabelas))})", tabelas)
    db.migrar(con)   # recria a doca de recebimento padrão
    return {"ok": True, "cadastros_mantidos": manter_cadastros}


# ----------------------------------------------------------------- movimento
def registrar(con, tipo, lote_id, quantidade, origem, meio, motivo=None, epc=None, documento=None):
    """Grava uma linha no histórico com o saldo e o endereço do lote naquele momento."""
    lote = buscar_lote(con, lote_id)
    con.execute(
        """INSERT INTO movimentos (data_hora, tipo, lote_id, quantidade, epc, origem, meio, motivo,
                                   documento, endereco, saldo_apos)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (db.agora(), tipo, lote_id, quantidade, epc, origem, meio, motivo,
         (documento or "").strip() or None, lote["endereco"], lote["quantidade"]))


def movimentar(con, tipo, lote_id, quantidade, origem, meio, motivo=None, epc=None, documento=None):
    """Altera o saldo de um lote e grava o histórico."""
    lote = buscar_lote(con, lote_id)
    if lote["quantidade"] + quantidade < 0:
        raise ErroEstoque(f"Saldo insuficiente no lote {lote['lote']} (saldo {fmt(lote['quantidade'])})")
    con.execute("UPDATE lotes SET quantidade = quantidade + ? WHERE id=?", (quantidade, lote_id))
    registrar(con, tipo, lote_id, quantidade, origem, meio, motivo, epc, documento)


# ----------------------------------------------------------------- entrada (recebimento)
def entrada(con, produto_id, lote, validade, quantidade=0, epcs=(), origem="PC", meio="MANUAL",
            endereco_id=None, documento=None):
    """Entrada de estoque. Com tags RFID, cada EPC lido vale 1 unidade.

    Lote novo vai para o endereço informado ou, sem endereço, para a doca de recebimento.
    """
    p = produto_ativo(con, produto_id)
    lote = (lote or "").strip().upper() or "SEM-LOTE"
    validade = normalizar_data(validade)
    epcs = sorted({e.strip().upper() for e in epcs if e and e.strip()})
    if epcs:
        quantidade = len(epcs)
    validar_quantidade(p, quantidade)

    existente = con.execute("SELECT * FROM lotes WHERE produto_id=? AND lote=?", (p["id"], lote)).fetchone()
    if existente:
        lote_id = existente["id"]
        if validade and existente["validade"] and validade != existente["validade"]:
            raise ErroEstoque(f"Lote {lote} já existe com validade {existente['validade']}")
        if validade and not existente["validade"]:
            con.execute("UPDATE lotes SET validade=? WHERE id=?", (validade, lote_id))
        if endereco_id and existente["endereco_id"] != endereco_id:
            atual = buscar_lote(con, lote_id)["endereco"]
            raise ErroEstoque(f"Lote {lote} já está no endereço {atual}. Dê entrada lá e transfira depois.")
    else:
        endereco = buscar_endereco(con, endereco_id)
        lote_id = con.execute(
            "INSERT INTO lotes (produto_id, lote, validade, endereco_id, criado_em) VALUES (?,?,?,?,?)",
            (p["id"], lote, validade, endereco["id"], db.agora())).lastrowid

    for epc in epcs:
        t = con.execute("SELECT status FROM tags WHERE epc=?", (epc,)).fetchone()
        if t and t["status"] == "ATIVA":
            raise ErroEstoque(f"Tag {epc} já está em estoque")
        con.execute("INSERT OR REPLACE INTO tags (epc, lote_id, status) VALUES (?,?,'ATIVA')", (epc, lote_id))
        movimentar(con, "ENTRADA", lote_id, 1, origem, "RFID", epc=epc, documento=documento)
    if not epcs:
        movimentar(con, "ENTRADA", lote_id, quantidade, origem, meio, documento=documento)

    l = buscar_lote(con, lote_id)
    avisos = avisos_validade([l])
    if l["status"] == "BLOQUEADO":
        avisos.append(f"Lote {lote} está BLOQUEADO: não sai na baixa até ser liberado")
    return {"sku": p["sku"], "lote": lote, "lote_id": lote_id, "quantidade": quantidade,
            "endereco": l["endereco"], "saldo": l["quantidade"], "avisos": avisos}


# ----------------------------------------------------------------- baixa
def sugerir_fefo(con, produto_id, quantidade, usar_vencidos=False):
    """Quanto tirar de cada lote, começando pelo que vence primeiro.

    Ficam de fora: lotes bloqueados, lotes vencidos (a não ser na baixa por
    VENCIMENTO), unidades com etiqueta RFID (saem lendo a tag) e o que já
    está reservado para pedidos.
    """
    p = buscar_produto(con, produto_id)
    validar_quantidade(p, quantidade)
    falta, plano = quantidade, []
    for l in lotes_fefo(con, produto_id):
        if vencido(l) != usar_vencidos:
            continue
        livre = l["quantidade"] - qtd_etiquetada(con, l["id"]) - qtd_reservada(con, l["id"])
        if livre <= 0:
            continue
        tirar = min(livre, falta)
        plano.append({"lote_id": l["id"], "lote": l["lote"], "validade": l["validade"],
                      "endereco": l["endereco"], "quantidade": tirar})
        falta -= tirar
        if falta <= 0:
            return plano
    tipo = "vencido" if usar_vencidos else "disponível"
    raise ErroEstoque(f"Estoque {tipo} insuficiente de {p['sku']}: "
                      f"disponível {fmt(quantidade - falta)}, pedido {fmt(quantidade)}")


def baixa_quantidade(con, produto_id, quantidade, motivo, origem="PC", meio="MANUAL", documento=None):
    """Baixa por quantidade (PC ou código de barras): o sistema escolhe os lotes por FEFO."""
    plano = sugerir_fefo(con, produto_id, quantidade, usar_vencidos=(motivo == "VENCIMENTO"))
    for item in plano:
        movimentar(con, "BAIXA", item["lote_id"], -item["quantidade"], origem, meio, motivo, documento=documento)
    return {"lotes": plano, "avisos": []}


def baixa_lote(con, lote_id, quantidade, motivo, origem="PC", meio="MANUAL", documento=None):
    """Baixa de um lote escolhido (fora do FEFO), ex.: descarte de lote avariado ou bloqueado."""
    l = buscar_lote(con, lote_id)
    validar_quantidade(buscar_produto(con, l["produto_id"]), quantidade)
    if l["status"] == "BLOQUEADO" and motivo not in MOTIVOS_DESCARTE:
        raise ErroEstoque(f"Lote {l['lote']} está BLOQUEADO (só sai por AVARIA, PERDA ou VENCIMENTO)")
    livre = l["quantidade"] - qtd_etiquetada(con, lote_id) - qtd_reservada(con, lote_id)
    if quantidade > livre:
        raise ErroEstoque(f"Lote {l['lote']}: disponível {fmt(max(livre, 0))} "
                          "(unidades com tag RFID saem lendo a tag; reservas de pedido não podem sair)")
    movimentar(con, "BAIXA", lote_id, -quantidade, origem, meio, motivo, documento=documento)
    return {"lotes": [{"lote_id": lote_id, "lote": l["lote"], "validade": l["validade"],
                       "endereco": l["endereco"], "quantidade": quantidade}], "avisos": []}


def baixa_tag(con, epc, motivo, origem="COLETOR", documento=None):
    """Baixa por RFID: a tag diz exatamente qual lote está saindo."""
    t = buscar_tag(con, epc)
    if t["status"] != "ATIVA":
        raise ErroEstoque(f"Tag {t['epc']} já foi baixada")
    if t["status_lote"] == "BLOQUEADO" and motivo not in MOTIVOS_DESCARTE:
        raise ErroEstoque(f"Lote {t['lote']} está BLOQUEADO (só sai por AVARIA, PERDA ou VENCIMENTO)")
    con.execute("UPDATE tags SET status='BAIXADA' WHERE epc=?", (t["epc"],))
    movimentar(con, "BAIXA", t["lote_id"], -1, origem, "RFID", motivo, t["epc"], documento)
    avisos = avisos_validade([dict(t)])
    # FEFO: existe outro lote (ainda válido) que vence antes deste?
    validos = [l for l in lotes_fefo(con, t["produto_id"]) if not vencido(l)]
    if validos and validos[0]["validade"] and t["validade"] and validos[0]["validade"] < t["validade"]:
        avisos.append(f"FEFO: o lote {validos[0]['lote']} vence antes ({validos[0]['validade']})")
    return {"epc": t["epc"], "sku": t["sku"], "lote": t["lote"], "avisos": avisos}


# ----------------------------------------------------------------- armazenagem
def transferir(con, lote_id, endereco_id, origem="PC", meio="MANUAL"):
    """Muda o lote inteiro de endereço (ex.: da doca de recebimento para a prateleira)."""
    l = buscar_lote(con, lote_id)
    destino = buscar_endereco(con, endereco_id)
    if l["endereco_id"] == destino["id"]:
        raise ErroEstoque(f"Lote {l['lote']} já está no endereço {destino['codigo']}")
    if l["quantidade"] <= 0:
        raise ErroEstoque(f"Lote {l['lote']} está sem saldo")
    con.execute("UPDATE lotes SET endereco_id=? WHERE id=?", (destino["id"], lote_id))
    registrar(con, "TRANSFERENCIA", lote_id, 0, origem, meio,
              f"{fmt(l['quantidade'])} un.: {l['endereco'] or '-'} → {destino['codigo']}")
    return {"lote": l["lote"], "de": l["endereco"], "para": destino["codigo"]}


def bloquear_lote(con, lote_id, motivo, origem="PC"):
    """Quarentena: o lote não sai na baixa por quantidade nem entra em pedidos."""
    l = buscar_lote(con, lote_id)
    if l["status"] == "BLOQUEADO":
        raise ErroEstoque(f"Lote {l['lote']} já está bloqueado")
    if qtd_reservada(con, lote_id) > 0:
        raise ErroEstoque(f"Lote {l['lote']} tem reserva de pedido. Cancele o pedido antes")
    motivo = (motivo or "").strip()
    if not motivo:
        raise ErroEstoque("Informe o motivo do bloqueio")
    con.execute("UPDATE lotes SET status='BLOQUEADO' WHERE id=?", (lote_id,))
    registrar(con, "BLOQUEIO", lote_id, 0, origem, "MANUAL", motivo)
    return {"lote": l["lote"], "status": "BLOQUEADO"}


def liberar_lote(con, lote_id, origem="PC"):
    l = buscar_lote(con, lote_id)
    if l["status"] != "BLOQUEADO":
        raise ErroEstoque(f"Lote {l['lote']} não está bloqueado")
    con.execute("UPDATE lotes SET status='LIBERADO' WHERE id=?", (lote_id,))
    registrar(con, "LIBERACAO", lote_id, 0, origem, "MANUAL", "Lote liberado")
    return {"lote": l["lote"], "status": "LIBERADO"}


# ----------------------------------------------------------------- inventário
def inventario_aberto(con, inventario_id):
    inv = con.execute("SELECT * FROM inventarios WHERE id=?", (inventario_id,)).fetchone()
    if not inv:
        raise ErroEstoque("Inventário não encontrado")
    if inv["status"] != "ABERTO":
        raise ErroEstoque(f"Inventário já está {inv['status']}")
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
    """Contagem manual de um lote. Várias contagens do mesmo lote são somadas."""
    inventario_aberto(con, inventario_id)
    if not lote_id:
        raise ErroEstoque("Escolha o lote contado")
    l = buscar_lote(con, lote_id)
    validar_quantidade(buscar_produto(con, l["produto_id"]), quantidade, aceita_zero=True)
    con.execute(
        """INSERT INTO contagens (inventario_id, lote_id, quantidade, origem, meio, data_hora)
           VALUES (?,?,?,?,?,?)""", (inventario_id, lote_id, quantidade, origem, meio, db.agora()))
    return {"lote": l["lote"], "quantidade": quantidade}


def confrontar(con, inventario_id):
    """Compara o contado (físico) com o saldo do sistema, lote a lote."""
    return db.linhas(con.execute(
        """SELECT l.id AS lote_id, p.sku, p.descricao, l.lote, l.validade, e.codigo AS endereco,
                  l.quantidade AS sistema,
                  COALESCE(c.contado, 0) AS contado,
                  COALESCE(c.contado, 0) - l.quantidade AS diferenca,
                  c.contado IS NOT NULL AS foi_contado
           FROM lotes l
           JOIN produtos p ON p.id = l.produto_id
           LEFT JOIN enderecos e ON e.id = l.endereco_id
           LEFT JOIN (SELECT lote_id, SUM(quantidade) AS contado FROM contagens
                      WHERE inventario_id=? GROUP BY lote_id) c ON c.lote_id = l.id
           WHERE l.quantidade <> 0 OR c.contado IS NOT NULL
           ORDER BY e.codigo, p.sku, l.validade""", (inventario_id,)))


def fechar_inventario(con, inventario_id, origem="PC"):
    """Aplica as diferenças: o saldo do sistema passa a ser o que foi contado."""
    inventario_aberto(con, inventario_id)
    ajustes = 0
    for item in confrontar(con, inventario_id):
        if item["diferenca"] != 0:
            movimentar(con, "AJUSTE", item["lote_id"], item["diferenca"], origem, "MANUAL",
                       "Sobra no inventário" if item["diferenca"] > 0 else "Falta no inventário",
                       documento=f"INV-{inventario_id}")
            ajustes += 1
    # Tags lidas no inventário estão fisicamente no estoque.
    con.execute("""UPDATE tags SET status='ATIVA'
                   WHERE epc IN (SELECT epc FROM contagens WHERE inventario_id=? AND epc IS NOT NULL)""",
                (inventario_id,))
    con.execute("UPDATE inventarios SET status='FECHADO', fechado_em=? WHERE id=?", (db.agora(), inventario_id))
    return {"ajustes": ajustes}


def cancelar_inventario(con, inventario_id):
    """Descarta as contagens: nada muda no estoque."""
    inventario_aberto(con, inventario_id)
    con.execute("UPDATE inventarios SET status='CANCELADO', fechado_em=? WHERE id=?", (db.agora(), inventario_id))
    return {"ok": True}


# ----------------------------------------------------------------- pedidos (expedição)
def buscar_pedido(con, pedido_id, status=None):
    ped = con.execute("SELECT * FROM pedidos WHERE id=?", (pedido_id,)).fetchone()
    if not ped:
        raise ErroEstoque("Pedido não encontrado")
    if status and ped["status"] not in status:
        raise ErroEstoque(f"Pedido {ped['numero']} está {ped['status']}")
    return ped


def criar_pedido(con, cliente, itens, numero=None, observacao=None):
    """Pedido com um ou mais itens. Itens do mesmo produto são somados."""
    cliente = (cliente or "").strip()
    if not cliente:
        raise ErroEstoque("Informe o cliente")
    if not itens:
        raise ErroEstoque("Inclua pelo menos um item no pedido")
    somados = {}
    for item in itens:
        p = produto_ativo(con, item.get("produto_id"), item.get("codigo"))
        validar_quantidade(p, item.get("quantidade"))
        somados[p["id"]] = somados.get(p["id"], 0) + item["quantidade"]
    numero = (numero or "").strip().upper()
    if numero and con.execute("SELECT 1 FROM pedidos WHERE numero=?", (numero,)).fetchone():
        raise ErroEstoque(f"Já existe o pedido {numero}")
    pedido_id = con.execute(
        "INSERT INTO pedidos (numero, cliente, observacao, criado_em) VALUES (?,?,?,?)",
        (numero or f"TMP-{db.agora()}", cliente, (observacao or "").strip() or None, db.agora())).lastrowid
    if not numero:
        numero = f"PED-{pedido_id:05d}"
        con.execute("UPDATE pedidos SET numero=? WHERE id=?", (numero, pedido_id))
    for produto_id, qtd in somados.items():
        con.execute("INSERT INTO pedido_itens (pedido_id, produto_id, quantidade) VALUES (?,?,?)",
                    (pedido_id, produto_id, qtd))
    return {"id": pedido_id, "numero": numero}


def liberar_pedido(con, pedido_id):
    """Libera para separação: reserva os lotes por FEFO e gera a lista de separação."""
    ped = buscar_pedido(con, pedido_id, ("ABERTO",))
    itens = con.execute("SELECT * FROM pedido_itens WHERE pedido_id=?", (pedido_id,)).fetchall()
    for item in itens:
        for parte in sugerir_fefo(con, item["produto_id"], item["quantidade"]):
            con.execute("INSERT INTO reservas (pedido_id, item_id, lote_id, quantidade) VALUES (?,?,?,?)",
                        (pedido_id, item["id"], parte["lote_id"], parte["quantidade"]))
    con.execute("UPDATE pedidos SET status='SEPARANDO', liberado_em=? WHERE id=?", (db.agora(), pedido_id))
    return {"numero": ped["numero"], "status": "SEPARANDO"}


def expedir_pedido(con, pedido_id, origem="PC"):
    """Confirma a separação: baixa os lotes reservados e fecha o pedido."""
    ped = buscar_pedido(con, pedido_id, ("SEPARANDO",))
    reservas = con.execute("SELECT * FROM reservas WHERE pedido_id=?", (pedido_id,)).fetchall()
    con.execute("DELETE FROM reservas WHERE pedido_id=?", (pedido_id,))
    for r in reservas:
        movimentar(con, "BAIXA", r["lote_id"], -r["quantidade"], origem, "MANUAL", "VENDA", documento=ped["numero"])
    con.execute("UPDATE pedidos SET status='EXPEDIDO', expedido_em=? WHERE id=?", (db.agora(), pedido_id))
    return {"numero": ped["numero"], "status": "EXPEDIDO", "lotes": len(reservas)}


def cancelar_pedido(con, pedido_id):
    """Cancela e devolve as reservas para o estoque disponível."""
    ped = buscar_pedido(con, pedido_id, ("ABERTO", "SEPARANDO"))
    con.execute("DELETE FROM reservas WHERE pedido_id=?", (pedido_id,))
    con.execute("UPDATE pedidos SET status='CANCELADO' WHERE id=?", (pedido_id,))
    return {"numero": ped["numero"], "status": "CANCELADO"}
