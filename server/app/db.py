"""Banco de dados SQLite do mini WMS (arquivo estoque.db ao lado do servidor)."""
import os
import sqlite3
from datetime import datetime

DB_PATH = os.environ.get("WMS_DB", os.path.join(os.path.dirname(__file__), "..", "estoque.db"))

# Endereço criado automaticamente: toda mercadoria recebida chega aqui
# e depois é armazenada (transferida) para um endereço de estoque.
DOCA_RECEBIMENTO = "DOCA-REC"

SCHEMA = """
-- Cadastro de produtos
CREATE TABLE IF NOT EXISTS produtos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sku         TEXT NOT NULL UNIQUE,     -- código interno
    descricao   TEXT NOT NULL,
    ean         TEXT,                     -- código de barras
    unidade     TEXT NOT NULL DEFAULT 'UN',
    estoque_min REAL NOT NULL DEFAULT 0,
    ativo       INTEGER NOT NULL DEFAULT 1 -- produto inativo não recebe entrada nem pedido
);

-- Endereços do armazém (rua-prédio-nível, doca, área de avaria...)
CREATE TABLE IF NOT EXISTS enderecos (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo    TEXT NOT NULL UNIQUE,       -- ex.: A-01-02
    descricao TEXT,
    tipo      TEXT NOT NULL DEFAULT 'ARMAZENAGEM', -- RECEBIMENTO | ARMAZENAGEM | EXPEDICAO | AVARIA
    ativo     INTEGER NOT NULL DEFAULT 1
);

-- Cada lote guarda sua validade, seu endereço e sua quantidade em estoque (o saldo).
CREATE TABLE IF NOT EXISTS lotes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    produto_id  INTEGER NOT NULL REFERENCES produtos(id),
    lote        TEXT NOT NULL,
    validade    TEXT,                     -- AAAA-MM-DD
    quantidade  REAL NOT NULL DEFAULT 0,
    endereco_id INTEGER REFERENCES enderecos(id),
    status      TEXT NOT NULL DEFAULT 'LIBERADO', -- LIBERADO | BLOQUEADO (quarentena)
    criado_em   TEXT,
    UNIQUE (produto_id, lote)
);

-- Etiqueta RFID: cada tag = 1 unidade de um lote.
CREATE TABLE IF NOT EXISTS tags (
    epc     TEXT PRIMARY KEY,
    lote_id INTEGER NOT NULL REFERENCES lotes(id),
    status  TEXT NOT NULL DEFAULT 'ATIVA' -- ATIVA | BAIXADA
);

-- Histórico (kardex): tudo que acontece com um lote gera um movimento.
CREATE TABLE IF NOT EXISTS movimentos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    data_hora  TEXT NOT NULL,             -- hora do servidor (PC)
    tipo       TEXT NOT NULL,             -- ENTRADA | BAIXA | AJUSTE | TRANSFERENCIA | BLOQUEIO | LIBERACAO
    lote_id    INTEGER NOT NULL REFERENCES lotes(id),
    quantidade REAL NOT NULL,             -- positiva ou negativa (0 quando não altera saldo)
    epc        TEXT,
    origem     TEXT NOT NULL,             -- PC | COLETOR
    meio       TEXT NOT NULL,             -- MANUAL | BARRAS | RFID
    motivo     TEXT,
    documento  TEXT,                      -- nota fiscal, pedido, inventário...
    endereco   TEXT,                      -- endereço do lote no momento do movimento
    saldo_apos REAL                       -- saldo do lote depois do movimento
);
CREATE INDEX IF NOT EXISTS ix_movimentos_lote ON movimentos(lote_id);

CREATE TABLE IF NOT EXISTS inventarios (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nome        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'ABERTO',   -- ABERTO | FECHADO | CANCELADO
    aberto_em   TEXT NOT NULL,
    fechado_em  TEXT
);

-- Itens contados no inventário (pelo PC ou pelo coletor).
CREATE TABLE IF NOT EXISTS contagens (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    inventario_id INTEGER NOT NULL REFERENCES inventarios(id),
    lote_id       INTEGER NOT NULL REFERENCES lotes(id),
    quantidade    REAL NOT NULL,
    epc           TEXT,
    origem        TEXT NOT NULL,
    meio          TEXT NOT NULL,
    data_hora     TEXT NOT NULL,
    UNIQUE (inventario_id, epc)           -- a mesma tag só conta uma vez
);

-- Resultado guardado quando o inventário é fechado (o estoque muda depois;
-- sem isso, um inventário antigo mostraria os números de hoje).
CREATE TABLE IF NOT EXISTS inventario_resultado (
    inventario_id INTEGER NOT NULL REFERENCES inventarios(id),
    lote_id       INTEGER NOT NULL REFERENCES lotes(id),
    sistema       REAL NOT NULL,          -- em estoque na hora de fechar
    contado       REAL NOT NULL,          -- lido/contado
    PRIMARY KEY (inventario_id, lote_id)
);

-- Situação de cada etiqueta no inventário fechado: OK (lida e em estoque),
-- FALTA (em estoque e não lida) ou SOBRA (lida e não estava em estoque).
CREATE TABLE IF NOT EXISTS inventario_etiquetas (
    inventario_id INTEGER NOT NULL REFERENCES inventarios(id),
    epc           TEXT NOT NULL,
    lote_id       INTEGER NOT NULL REFERENCES lotes(id),
    situacao      TEXT NOT NULL,
    PRIMARY KEY (inventario_id, epc)
);

-- Etiquetas lidas no inventário que o sistema não conhece (não cadastradas):
-- contam como sobra, mas não entram no estoque (não se sabe o produto).
CREATE TABLE IF NOT EXISTS inventario_desconhecidas (
    inventario_id INTEGER NOT NULL REFERENCES inventarios(id),
    epc           TEXT NOT NULL,
    origem        TEXT NOT NULL,
    data_hora     TEXT NOT NULL,
    produto_id    INTEGER REFERENCES produtos(id),   -- preenchido quando foi incluída no estoque
    PRIMARY KEY (inventario_id, epc)
);

-- Pedidos de expedição (saída para cliente)
CREATE TABLE IF NOT EXISTS pedidos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    numero      TEXT NOT NULL UNIQUE,
    cliente     TEXT NOT NULL,
    observacao  TEXT,
    status      TEXT NOT NULL DEFAULT 'ABERTO', -- ABERTO | SEPARANDO | EXPEDIDO | CANCELADO
    criado_em   TEXT NOT NULL,
    liberado_em TEXT,
    expedido_em TEXT
);

CREATE TABLE IF NOT EXISTS pedido_itens (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_id  INTEGER NOT NULL REFERENCES pedidos(id),
    produto_id INTEGER NOT NULL REFERENCES produtos(id),
    quantidade REAL NOT NULL
);

-- Ordem de recebimento (pré-recebimento): o PC cadastra o que vai chegar
-- (nota fiscal, itens, lotes, quantidades) e o coletor lê as etiquetas.
CREATE TABLE IF NOT EXISTS recebimentos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    numero        TEXT NOT NULL UNIQUE,
    documento     TEXT,                   -- nota fiscal
    fornecedor    TEXT,
    endereco_id   INTEGER REFERENCES enderecos(id),   -- onde os lotes novos entram (padrão: doca)
    status        TEXT NOT NULL DEFAULT 'ABERTO',     -- ABERTO | FINALIZADO | CANCELADO
    criado_em     TEXT NOT NULL,
    finalizado_em TEXT
);

CREATE TABLE IF NOT EXISTS recebimento_itens (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    recebimento_id INTEGER NOT NULL REFERENCES recebimentos(id),
    produto_id     INTEGER NOT NULL REFERENCES produtos(id),
    lote           TEXT NOT NULL,
    validade       TEXT,
    prevista       REAL NOT NULL          -- quantidade esperada
);

-- Cada leitura do coletor fica gravada na hora (online): uma etiqueta RFID
-- (quantidade 1) ou uma quantidade contada por código de barras.
CREATE TABLE IF NOT EXISTS recebimento_leituras (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    recebimento_id INTEGER NOT NULL REFERENCES recebimentos(id),
    item_id        INTEGER NOT NULL REFERENCES recebimento_itens(id),
    epc            TEXT,
    quantidade     REAL NOT NULL,
    origem         TEXT NOT NULL,
    meio           TEXT NOT NULL,
    data_hora      TEXT NOT NULL,
    UNIQUE (recebimento_id, epc)
);

-- Reserva: quanto de cada lote está separado para um pedido (escolhido por FEFO).
-- Quantidade reservada não pode ser usada por outra baixa.
CREATE TABLE IF NOT EXISTS reservas (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_id  INTEGER NOT NULL REFERENCES pedidos(id),
    item_id    INTEGER NOT NULL REFERENCES pedido_itens(id),
    lote_id    INTEGER NOT NULL REFERENCES lotes(id),
    quantidade REAL NOT NULL
);
"""

# Colunas que entraram depois da primeira versão (bancos antigos ganham na migração)
COLUNAS_NOVAS = {
    "produtos": {"ativo": "INTEGER NOT NULL DEFAULT 1"},
    "lotes": {"endereco_id": "INTEGER REFERENCES enderecos(id)",
              "status": "TEXT NOT NULL DEFAULT 'LIBERADO'", "criado_em": "TEXT"},
    "movimentos": {"documento": "TEXT", "endereco": "TEXT", "saldo_apos": "REAL"},
    "inventario_desconhecidas": {"produto_id": "INTEGER REFERENCES produtos(id)"},
}


def agora() -> str:
    """Data/hora sempre do servidor: o relógio do coletor não importa."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hoje() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def conectar() -> sqlite3.Connection:
    # timeout: se outra requisição estiver gravando, espera em vez de dar erro
    con = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def inicializar() -> None:
    with conectar() as con:
        con.execute("PRAGMA journal_mode = WAL")  # leituras não travam gravações
        con.executescript(SCHEMA)
        migrar(con)


def migrar(con) -> None:
    """Atualiza um estoque.db da versão anterior sem perder dados."""
    for tabela, colunas in COLUNAS_NOVAS.items():
        existentes = {c["name"] for c in con.execute(f"PRAGMA table_info({tabela})")}
        for nome, tipo in colunas.items():
            if nome not in existentes:
                con.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}")
    con.execute("INSERT OR IGNORE INTO enderecos (codigo, descricao, tipo) VALUES (?, 'Doca de recebimento', 'RECEBIMENTO')",
                (DOCA_RECEBIMENTO,))
    doca = con.execute("SELECT id FROM enderecos WHERE codigo=?", (DOCA_RECEBIMENTO,)).fetchone()[0]
    con.execute("UPDATE lotes SET endereco_id=? WHERE endereco_id IS NULL", (doca,))


def linhas(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]
