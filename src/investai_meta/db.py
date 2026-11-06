"""Banco local (SQLite). Um arquivo guarda memória semântica, checkpoints, ordens e cache de mercado.

Tudo roda em processo, sem serviço externo. Os objetos LangGraph (`SqliteStore`, `SqliteSaver`)
usam o mesmo arquivo; as tabelas próprias do projeto (`ordens`, `cache_mercado`) ficam ao lado.
"""

import json
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.sqlite import SqliteStore

from investai_meta import config

DDL = """
CREATE TABLE IF NOT EXISTS ordens (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    produto_id  TEXT NOT NULL,
    tipo        TEXT NOT NULL CHECK (tipo IN ('compra', 'venda')),
    valor       REAL NOT NULL CHECK (valor > 0),
    preco_ref   TEXT,
    status      TEXT NOT NULL CHECK (status IN ('pendente', 'aprovada', 'rejeitada')),
    criado_em   TEXT NOT NULL,
    thread_id   TEXT
);
CREATE TABLE IF NOT EXISTS feedbacks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    thread_id   TEXT NOT NULL,
    nota        INTEGER NOT NULL CHECK (nota IN (-1, 1)),
    comentario  TEXT,
    criado_em   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cache_mercado (
    chave       TEXT PRIMARY KEY,
    json        TEXT NOT NULL,
    obtido_em   TEXT NOT NULL
);
"""


def _nova_conexao(caminho: Path) -> sqlite3.Connection:
    """Conexão própria. O SQLite não aguenta duas transações ao mesmo tempo na MESMA conexão (e o
    LangGraph usa threads), então store, checkpointer e tabelas do projeto abrem uma conexão cada."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(caminho, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # leitores não bloqueiam o escritor
    conn.execute("PRAGMA busy_timeout=5000")  # várias conexões no mesmo arquivo
    return conn


def conectar(caminho: Path = config.CAMINHO_DB) -> sqlite3.Connection:
    """Conexão para as tabelas do projeto (`ordens`, `cache_mercado`); cria o arquivo e o DDL se preciso."""
    conn = _nova_conexao(caminho)
    conn.executescript(DDL)
    return conn


def abrir_store(caminho: Path = config.CAMINHO_DB, embeddings=None, dims: int = config.DIMS_EMBEDDING) -> SqliteStore:
    """Memória de longo prazo. Com `embeddings`, os campos 'texto' e 'content' (LangMem) viram vetor."""
    index = None
    if embeddings is not None:
        index = {"embed": embeddings, "dims": dims, "text_fields": ["texto", "content"]}
    store = SqliteStore(_nova_conexao(caminho), index=index)
    store.setup()
    return store


def abrir_checkpointer(caminho: Path = config.CAMINHO_DB) -> SqliteSaver:
    """Memória de curto prazo: estado de cada thread do grafo."""
    saver = SqliteSaver(_nova_conexao(caminho))
    saver.setup()
    return saver


def inserir_ordem(
    conn: sqlite3.Connection,
    user_id: str,
    produto_id: str,
    tipo: str,
    valor: float,
    status: str,
    preco_ref: str | None = None,
    thread_id: str | None = None,
) -> str:
    ordem_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO ordens (id, user_id, produto_id, tipo, valor, preco_ref, status, criado_em, thread_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ordem_id, user_id, produto_id, tipo, valor, preco_ref, status, datetime.now().isoformat(timespec="seconds"), thread_id),
    )
    return ordem_id


def listar_ordens(conn: sqlite3.Connection, user_id: str | None = None) -> list[dict]:
    if user_id is None:
        linhas = conn.execute("SELECT * FROM ordens ORDER BY criado_em").fetchall()
    else:
        linhas = conn.execute("SELECT * FROM ordens WHERE user_id = ? ORDER BY criado_em", (user_id,)).fetchall()
    return [dict(l) for l in linhas]


def inserir_feedback(conn: sqlite3.Connection, user_id: str, thread_id: str, nota: int, comentario: str | None = None) -> int:
    cursor = conn.execute(
        "INSERT INTO feedbacks (user_id, thread_id, nota, comentario, criado_em) VALUES (?, ?, ?, ?, ?)",
        (user_id, thread_id, nota, comentario, datetime.now().isoformat(timespec="seconds")),
    )
    return cursor.lastrowid


def listar_feedbacks(conn: sqlite3.Connection, nota: int | None = None) -> list[dict]:
    if nota is None:
        linhas = conn.execute("SELECT * FROM feedbacks ORDER BY id").fetchall()
    else:
        linhas = conn.execute("SELECT * FROM feedbacks WHERE nota = ? ORDER BY id", (nota,)).fetchall()
    return [dict(l) for l in linhas]


def posicoes(conn: sqlite3.Connection, user_id: str) -> dict[str, float]:
    """Saldo por produto: compras aprovadas menos vendas aprovadas."""
    saldo: dict[str, float] = {}
    for o in listar_ordens(conn, user_id):
        if o["status"] == "aprovada":
            sinal = 1 if o["tipo"] == "compra" else -1
            saldo[o["produto_id"]] = saldo.get(o["produto_id"], 0.0) + sinal * o["valor"]
    return {k: v for k, v in saldo.items() if v > 0}


class CacheSQLite:
    """Último valor de cada API, guardado no SQLite. Usado só quando a API falha."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def gravar(self, chave: str, valor: dict) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO cache_mercado (chave, json, obtido_em) VALUES (?, ?, ?)",
            (chave, json.dumps(valor, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")),
        )

    def ler(self, chave: str) -> dict | None:
        linha = self._conn.execute("SELECT json FROM cache_mercado WHERE chave = ?", (chave,)).fetchone()
        return json.loads(linha["json"]) if linha else None
