"""Copia o guia já ingerido (chunks, cartões e embeddings) de outro banco, em vez de reingerir.

Reingerir leva ~5 minutos por causa do limite de embeddings do plano gratuito do Gemini. Copiar leva um segundo
e garante que as duas pastas (base e metacognição) comparem a mesma base de conhecimento.
Uso: python scripts/clonar_conhecimento.py [--de ../investai_1_base/dados/investai.db]
"""

import argparse
from pathlib import Path

import _caminhos  # noqa: F401

from investai_meta import config, db
from investai_meta.llm import criar_embeddings

PREFIXOS = ("conhecimento.%", "catalogo.%")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--de", default=str(_caminhos.RAIZ.parent / "investai_1_base" / "dados" / "investai.db"))
    origem = Path(ap.parse_args().de).resolve()
    if not origem.exists():
        raise SystemExit(f"Banco de origem não encontrado: {origem}")

    db.abrir_store(embeddings=criar_embeddings())  # cria store e store_vectors no destino
    conn = db.conectar()
    conn.execute("ATTACH DATABASE ? AS origem", (str(origem),))
    where = " OR ".join("prefix LIKE ?" for _ in PREFIXOS)
    conn.execute(
        "INSERT OR REPLACE INTO store (prefix, key, value, created_at, updated_at, expires_at, ttl_minutes) "
        f"SELECT prefix, key, value, created_at, updated_at, expires_at, ttl_minutes FROM origem.store WHERE {where}", PREFIXOS,
    )
    conn.execute(
        "INSERT OR REPLACE INTO store_vectors (prefix, key, field_name, embedding, created_at, updated_at) "
        f"SELECT prefix, key, field_name, embedding, created_at, updated_at FROM origem.store_vectors WHERE {where}", PREFIXOS,
    )
    conn.execute("DETACH DATABASE origem")
    n = conn.execute("SELECT count(*) FROM store WHERE prefix LIKE 'conhecimento.%'").fetchone()[0]
    c = conn.execute("SELECT count(*) FROM store WHERE prefix LIKE 'catalogo.%'").fetchone()[0]
    v = conn.execute("SELECT count(*) FROM store_vectors WHERE prefix LIKE 'conhecimento.%'").fetchone()[0]
    print(f"Copiado de {origem}\n{n} chunks, {v} vetores, {c} cartões em {config.CAMINHO_DB}")
