"""Cria o banco local (dados/investai_meta.db) com as tabelas do LangGraph e do projeto. Pode rodar várias vezes."""

import _caminhos  # noqa: F401  (ajusta o sys.path)

from investai_meta import config, db

if __name__ == "__main__":
    conn = db.conectar()
    db.abrir_store()  # cria as tabelas do store
    db.abrir_checkpointer()  # cria as tabelas de checkpoints
    tabelas = [l["name"] for l in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    print(f"Banco: {config.CAMINHO_DB}")
    print("Tabelas:", ", ".join(tabelas))
