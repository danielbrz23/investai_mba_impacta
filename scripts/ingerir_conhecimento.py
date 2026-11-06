"""Ingestão do guia no store semântico: guia .md -> chunks -> embeddings (Gemini) -> SqliteStore.

Idempotente: apaga o namespace do conhecimento antes de gravar. Os placeholders do guia
({selic}, {cdi}, {ipca_12m}) são preenchidos com os dados do Banco Central lidos na hora.
Os embeddings usam a chave GEMINI_API_KEY do .env (a mesma do agente).
"""

import os
import sys
import time

import _caminhos  # noqa: F401
from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langgraph.store.base import PutOp

from investai_meta import config, db
from investai_meta.config import NS_CONHECIMENTO
from investai_meta.dados_mercado import ClienteMercado, formatar_para_guia
from investai_meta.ingestao import gerar_chunks, montar_ops, resumo_produtos

# Plano gratuito do Gemini: 100 pedidos de embedding por minuto. Gravamos em lotes com pausa.
LOTE_EMBEDDING = 50
PAUSA_ENTRE_LOTES_S = 65
TENTATIVAS_POR_LOTE = 5

CONSULTAS_SANIDADE = [
    "o que perco se resgatar o Tesouro IPCA+ antes do vencimento?",
    "investimento isento de IR com garantia do FGC",
    "qual o melhor lugar para a reserva de emergência?",
    "fundo com retorno garantido e sem risco",
    "quanto a poupança rende hoje?",
]

if __name__ == "__main__":
    # .env da pasta do projeto; se não existir, o da raiz do repositório (onde estão as chaves).
    load_dotenv(_caminhos.RAIZ / ".env")
    load_dotenv(_caminhos.RAIZ.parent / ".env")
    conn = db.conectar()
    if "--se-vazio" in sys.argv:  # usado no deploy: só ingere na primeira subida
        existente = db.abrir_store().search(NS_CONHECIMENTO, limit=1)
        if existente:
            print("Conhecimento já ingerido; nada a fazer.")
            sys.exit(0)
    embeddings = GoogleGenerativeAIEmbeddings(model=config.MODELO_EMBEDDING, api_key=os.environ["GEMINI_API_KEY"])
    store = db.abrir_store(embeddings=embeddings)

    indicadores = ClienteMercado(persistencia=db.CacheSQLite(conn)).indicadores()
    valores = formatar_para_guia(indicadores)
    datas = ", ".join(f"{n} de {s['data']}" for n, s in indicadores.items())
    markdown = (_caminhos.RAIZ / "data" / "guia_investimentos.md").read_text(encoding="utf-8")

    chunks = gerar_chunks(markdown, valores)
    cartoes = resumo_produtos(markdown)

    # Idempotente: apaga o conhecimento anterior e grava de novo, em lote (um só pedido de embeddings).
    antigos = store.search(NS_CONHECIMENTO, limit=10_000)
    store.batch([PutOp(NS_CONHECIMENTO, item.key, None) for item in antigos])
    ops, ops_cartoes = montar_ops(chunks, cartoes, datas)
    for inicio in range(0, len(ops), LOTE_EMBEDDING):
        lote = ops[inicio : inicio + LOTE_EMBEDDING]
        for tentativa in range(1, TENTATIVAS_POR_LOTE + 1):
            if inicio or tentativa > 1:
                print(f"Pausa de {PAUSA_ENTRE_LOTES_S}s (limite de embeddings por minuto)...", flush=True)
                time.sleep(PAUSA_ENTRE_LOTES_S)
            try:
                store.batch(lote)
                break
            except Exception as erro:  # o langchain embrulha o 429 do Gemini em outra exceção
                if "RESOURCE_EXHAUSTED" not in str(erro) or tentativa == TENTATIVAS_POR_LOTE:
                    raise
                print(f"Limite de cota atingido (tentativa {tentativa}); repetindo o lote.", flush=True)
        print(f"Gravados {min(inicio + LOTE_EMBEDDING, len(ops))}/{len(ops)} chunks", flush=True)
    store.batch(ops_cartoes)

    print(f"Dados do BCB usados: {datas}\n")
    print(f"{'produto':<40} chunks")
    contagem = {}
    for c in chunks:
        contagem[c.produto] = contagem.get(c.produto, 0) + 1
    for nome, n in contagem.items():
        print(f"{nome:<40} {n}")
    print(f"\nTotal: {len(chunks)} chunks, {len(cartoes)} cartões.\n")

    print("Perguntas de sanidade (top 3):")
    for pergunta in CONSULTAS_SANIDADE:
        print(f"\n? {pergunta}")
        for item in store.search(NS_CONHECIMENTO, query=pergunta, limit=3):
            print(f"  {item.score:.3f}  {item.value['produto']} › {item.value['secao']}")
