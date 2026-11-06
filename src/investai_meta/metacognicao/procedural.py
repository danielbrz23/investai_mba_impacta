"""Memória procedural: o prompt do assessor vive no store e melhora com o feedback dos clientes.

Segurança: o prompt otimizado é gerado por LLM a partir de texto de clientes, então só vale depois de passar
pela validação (marcadores de segurança preservados, sem padrões de injeção) e de um humano aprovar o diff.
"""

import difflib
from datetime import datetime

from langmem import create_prompt_optimizer

from investai_meta import config
from investai_meta.guardrails import injecao
from investai_meta.prompts import PROMPT_SISTEMA

# Trechos que o prompt novo precisa manter: são as regras de segurança do assessor.
MARCADORES_OBRIGATORIOS = ["dados_nao_confiaveis", "registrar_ordem", "FGC", "Nunca prometa"]


def prompt_atual(store) -> str:
    item = store.get(config.NS_PROMPT, "sistema") if store is not None else None
    return item.value["texto"] if item else PROMPT_SISTEMA


def validar(novo: str, atual: str) -> tuple[bool, str]:
    if not novo.strip():
        return False, "prompt vazio"
    if len(novo) > 2 * len(atual) + 500:
        return False, "prompt cresceu demais"
    faltando = [m for m in MARCADORES_OBRIGATORIOS if m not in novo]
    if faltando:
        return False, f"perdeu regras de segurança: {', '.join(faltando)}"
    padrao = injecao.detectar_regex(novo)
    if padrao:
        return False, f"padrão suspeito: {padrao}"
    return True, "ok"


def diff(atual: str, novo: str) -> str:
    return "\n".join(difflib.unified_diff(atual.splitlines(), novo.splitlines(), "prompt_atual", "prompt_novo", lineterm=""))


def otimizar(llm, prompt: str, trajetorias: list[tuple[list[dict], str]]) -> str:
    """LangMem (seção 3.7.3 do notebook): trajetórias = [(conversa, feedback)]."""
    otimizador = create_prompt_optimizer(llm, kind="prompt_memory")
    return otimizador.invoke({"trajectories": trajetorias, "prompt": prompt})


def aplicar(store, novo: str) -> str:
    """Guarda a versão atual no histórico (para rollback) e ativa a nova. Devolve a chave do histórico."""
    chave = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    store.put(config.NS_PROMPT_HISTORICO, chave, {"texto": prompt_atual(store)}, index=False)
    store.put(config.NS_PROMPT, "sistema", {"texto": novo}, index=False)
    return chave


def reverter(store) -> bool:
    """Volta para a versão anterior do prompt. False se não há histórico."""
    historico = sorted(store.search(config.NS_PROMPT_HISTORICO, limit=1000), key=lambda i: i.key)
    if not historico:
        return False
    ultima = historico[-1]
    store.put(config.NS_PROMPT, "sistema", {"texto": ultima.value["texto"]}, index=False)
    store.delete(config.NS_PROMPT_HISTORICO, ultima.key)
    return True


def trajetorias_de_feedback(saver, feedbacks: list[dict], limite: int = 20) -> list[tuple[list[dict], str]]:
    """Transforma os feedbacks do banco em trajetórias (conversa, feedback) para o otimizador do LangMem."""
    trajetorias = []
    for f in feedbacks[-limite:]:
        ponto = saver.get_tuple({"configurable": {"thread_id": f"{f['user_id']}:{f['thread_id']}"}})
        if ponto is None:
            continue
        conversa = [
            {"role": "user" if m.type == "human" else "assistant", "content": m.text}
            for m in ponto.checkpoint["channel_values"].get("messages", [])
            if m.type in ("human", "ai") and m.text.strip()
        ]
        texto = "👍 a resposta foi boa" if f["nota"] == 1 else "👎 a resposta foi ruim"
        if f.get("comentario"):
            texto += f": {f['comentario']}"
        if conversa:
            trajetorias.append((conversa, texto))
    return trajetorias
