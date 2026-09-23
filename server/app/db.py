"""Banco de dados SQLite do mini WMS (arquivo estoque.db ao lado do servidor)."""
import os
import sqlite3
from datetime import datetime

DB_PATH = os.environ.get("WMS_DB", os.path.join(os.path.dirname(__file__), "..", "estoque.db"))

SCHEMA = """
-- Cadastro de produtos
CREATE TABLE IF NOT EXISTS produtos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sku         TEXT NOT NULL UNIQUE,     -- código interno
    descricao   TEXT NOT NULL,
    ean         TEXT,                     -- código de barras
    unidade     TEXT NOT NULL DEFAULT 'UN',
    estoque_min REAL NOT NULL DEFAULT 0
);

-- Cada lote guarda sua validade e sua quantidade em estoque (o saldo).
CREATE TABLE IF NOT EXISTS lotes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    produto_id INTEGER NOT NULL REFERENCES produtos(id),
    lote       TEXT NOT NULL,
    validade   TEXT,                      -- AAAA-MM-DD
    quantidade REAL NOT NULL DEFAULT 0,
    UNIQUE (produto_id, lote)
);

-- Etiqueta RFID: cada tag = 1 unidade de um lote.
CREATE TABLE IF NOT EXISTS tags (
    epc     TEXT PRIMARY KEY,
    lote_id INTEGER NOT NULL REFERENCES lotes(id),
    status  TEXT NOT NULL DEFAULT 'ATIVA' -- ATIVA | BAIXADA
);

-- Histórico: toda alteração de saldo gera um movimento.
CREATE TABLE IF NOT EXISTS movimentos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    data_hora  TEXT NOT NULL,             -- hora do servidor (PC)
    tipo       TEXT NOT NULL,             -- ENTRADA | BAIXA | AJUSTE
    lote_id    INTEGER NOT NULL REFERENCES lotes(id),
    quantidade REAL NOT NULL,             -- positiva ou negativa
    epc        TEXT,
    origem     TEXT NOT NULL,             -- PC | COLETOR
    meio       TEXT NOT NULL,             -- MANUAL | BARRAS | RFID
    motivo     TEXT
);

CREATE TABLE IF NOT EXISTS inventarios (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nome        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'ABERTO',   -- ABERTO | FECHADO
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
"""


def agora() -> str:
    """Data/hora sempre do servidor: o relógio do coletor não importa."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hoje() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def conectar() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def inicializar() -> None:
    with conectar() as con:
        con.executescript(SCHEMA)


def linhas(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]
