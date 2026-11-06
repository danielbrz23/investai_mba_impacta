"""Fábricas do modelo de chat e dos embeddings (Gemini). A chave vem do .env."""

import os

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

from investai_meta import config


def carregar_env() -> None:
    """.env da pasta do projeto; se não existir, o da raiz do repositório (onde estão as chaves)."""
    load_dotenv(config.RAIZ / ".env")
    load_dotenv(config.RAIZ.parent / ".env")


def criar_llm() -> ChatGoogleGenerativeAI:
    carregar_env()
    return ChatGoogleGenerativeAI(
        model=config.MODELO_LLM,
        api_key=os.environ["GEMINI_API_KEY"],
        max_retries=4,
        temperature=0.2,  # respostas mais estáveis
        timeout=60,
    )


def criar_embeddings() -> GoogleGenerativeAIEmbeddings:
    carregar_env()
    return GoogleGenerativeAIEmbeddings(model=config.MODELO_EMBEDDING, api_key=os.environ["GEMINI_API_KEY"])
