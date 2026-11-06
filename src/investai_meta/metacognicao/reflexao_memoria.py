"""Reflexão sobre a memória: um fato novo contradiz o que o agente já sabe sobre o cliente?

Mudança brusca de perfil de risco não sobrescreve o perfil. Ela fica PENDENTE, o agente pergunta se o cliente
quer mesmo mudar, e só um "sim" explícito num turno seguinte aplica a mudança.
"""

import re

from investai_meta.guardrails.memoria import mudanca_brusca
from investai_meta.memoria import salvar_perfil

CONFIRMA = re.compile(r"\b(sim|confirmo|confirmado|isso mesmo|pode mudar|quero mudar)\b", re.IGNORECASE)


def ns_pendente(user_id: str) -> tuple[str, ...]:
    return ("usuarios", user_id, "pendente")


def ler_pendente(store, user_id: str) -> dict | None:
    item = store.get(ns_pendente(user_id), "perfil") if store is not None else None
    return item.value if item else None


def decidir(antigo: dict | None, novo: dict | None, texto_usuario: str, pendente: dict | None) -> tuple[str, str]:
    """Devolve (acao, motivo). acao: 'ok', 'pendente' ou 'aplicar_pendente'."""
    if pendente and CONFIRMA.search(texto_usuario):
        return "aplicar_pendente", "cliente confirmou a mudança de perfil"
    motivo = mudanca_brusca(antigo, novo)
    if motivo:
        return "pendente", motivo
    return "ok", ""


def executar(store, user_id: str, acao: str, motivo: str, antigo: dict | None, novo: dict | None, pendente: dict | None) -> None:
    if acao == "aplicar_pendente":
        salvar_perfil(store, user_id, pendente["proposto"])
        store.delete(ns_pendente(user_id), "perfil")
    elif acao == "pendente":
        store.put(ns_pendente(user_id), "perfil", {"proposto": novo, "motivo": motivo}, index=False)
        if antigo is not None:
            salvar_perfil(store, user_id, antigo)  # o perfil antigo continua valendo até a confirmação


def aviso_para_o_agente(pendente: dict | None) -> str:
    if not pendente:
        return ""
    return (
        "## Atenção: mudança de perfil pendente\n"
        f"O cliente disse algo que muda bastante o perfil de risco ({pendente['motivo']}). O perfil salvo NÃO foi alterado. "
        "Antes de recomendar, pergunte de forma direta se ele quer mesmo mudar o perfil."
    )
