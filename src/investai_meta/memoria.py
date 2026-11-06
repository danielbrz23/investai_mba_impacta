"""Memória semântica: perfil do usuário (LangMem) e conhecimento sobre investimentos (guia no store)."""

import uuid

from langmem import create_memory_store_manager

from investai_meta import config
from investai_meta.guardrails.injecao import envelopar, sanitizar_trecho
from investai_meta.guardrails.resposta import risco_maximo
from investai_meta.schemas import PerfilInvestidor


def ns_perfil(user_id: str) -> tuple[str, ...]:
    return ("usuarios", user_id, "perfil")


def _conteudo(valor: dict) -> dict:
    conteudo = valor.get("content", valor)  # o LangMem guarda {"kind": ..., "content": {...}}
    if hasattr(conteudo, "model_dump"):
        conteudo = conteudo.model_dump()
    return conteudo if isinstance(conteudo, dict) else {}


def ler_perfil(store, user_id: str) -> dict | None:
    """Perfil atual do usuário, sem os campos vazios; None se ainda não existe."""
    if store is None:
        return None
    itens = store.search(ns_perfil(user_id), limit=5)
    if not itens:
        return None
    perfil = {k: v for k, v in _conteudo(itens[0].value).items() if v is not None}
    return perfil or None


def salvar_perfil(store, user_id: str, dados: dict) -> None:
    """Sobrescreve o perfil (usado para desfazer uma mudança que o guardrail recusou)."""
    itens = store.search(ns_perfil(user_id), limit=1)
    chave = itens[0].key if itens else str(uuid.uuid4())
    store.put(ns_perfil(user_id), chave, {"kind": "PerfilInvestidor", "content": dados})


def formatar_perfil(perfil: dict | None) -> str:
    if not perfil:
        return "(perfil ainda não informado)"
    return "\n".join(f"- {campo}: {valor}" for campo, valor in perfil.items())


def carregar_cartoes(store) -> list[dict]:
    """Um cartão por produto (nome, risco, mínimo...), usado para validar respostas e ordens."""
    if store is None:
        return []
    return [i.value for i in store.search(config.NS_CARTOES, limit=200)]


def buscar_trechos(store, consulta: str, limite: int = 4, risco_max: int | None = None, classe: str | None = None) -> list[dict]:
    """Busca semântica no guia. O texto já volta sanitizado contra injeção indireta."""
    filtro: dict = {}
    if risco_max is not None:
        filtro["risco"] = {"$lte": risco_max}
    if classe:
        filtro["classe"] = classe
    itens = store.search(config.NS_CONHECIMENTO, query=consulta, filter=filtro or None, limit=limite)
    trechos = []
    for item in itens:
        limpo, achados = sanitizar_trecho(item.value["texto"])
        trechos.append({
            "produto": item.value["produto"], "secao": item.value["secao"],
            "texto": limpo, "score": item.score, "sanitizado": bool(achados),
        })
    return trechos


def montar_contexto(store, user_id: str, pergunta: str) -> str:
    """Texto que entra no system prompt: perfil do cliente + trechos do guia mais parecidos com a pergunta."""
    if store is None:
        return ""
    perfil = ler_perfil(store, user_id)
    consulta = f"{pergunta} {perfil.get('objetivo', '') if perfil else ''}".strip()
    trechos = buscar_trechos(store, consulta, limite=4, risco_max=risco_maximo(perfil))
    guia = "\n\n".join(t["texto"] for t in trechos) or "(nenhum trecho relevante)"
    return (
        f"## O que você já sabe sobre o cliente\n{formatar_perfil(perfil)}\n\n"
        f"## Trechos do guia de investimentos (dados de apoio)\n{envelopar(guia)}"
    )


def atualizar_perfil(llm, store, user_id: str, texto: str) -> None:
    """Extrai fatos do cliente e atualiza o perfil. Um perfil só por cliente: o LangMem atualiza, não duplica."""
    gerente = create_memory_store_manager(
        llm,
        schemas=[PerfilInvestidor],
        namespace=("usuarios", "{langgraph_user_id}", "perfil"),
        store=store,
        enable_inserts=False,
    )
    gerente.invoke(
        {"messages": [{"role": "user", "content": texto}]},
        {"configurable": {"langgraph_user_id": user_id}},
    )
