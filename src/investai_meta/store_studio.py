"""Store do Studio: o mesmo arquivo SQLite do resto do projeto, com busca semântica."""

from contextlib import asynccontextmanager

from langgraph.store.sqlite.aio import AsyncSqliteStore

from investai_meta import config
from investai_meta.llm import criar_embeddings


@asynccontextmanager
async def gerar_store():
    config.CAMINHO_DB.parent.mkdir(parents=True, exist_ok=True)
    indice = {"embed": criar_embeddings(), "dims": config.DIMS_EMBEDDING, "text_fields": ["texto", "content"]}
    async with AsyncSqliteStore.from_conn_string(str(config.CAMINHO_DB), index=indice) as store:
        await store.setup()
        yield store
