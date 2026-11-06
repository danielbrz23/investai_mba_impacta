"""Reflexion: falhas viram lições na memória de longo prazo e voltam ao prompt em situações parecidas.

Toda lição passa pelo mesmo crivo da memória do cliente: sem PII e sem cara de instrução, para a memória
do agente não virar um canal de prompt injection.
"""

import uuid

from langchain_core.messages import HumanMessage, SystemMessage

from investai_meta import config
from investai_meta.guardrails import injecao
from investai_meta.guardrails import memoria as guarda_mem
from investai_meta.prompts import PROMPT_LICAO
from investai_meta.schemas import Licao


def gerar_licao(juiz, situacao: str, motivo: str) -> Licao:
    return juiz.invoke([
        SystemMessage(PROMPT_LICAO),
        HumanMessage(f"<pedido_do_cliente>{situacao}</pedido_do_cliente>\n<o_que_deu_errado>{motivo}</o_que_deu_errado>"),
    ])


def licao_valida(licao: Licao) -> bool:
    texto = f"{licao.situacao} {licao.erro} {licao.regra_aprendida}"
    if len(licao.regra_aprendida) > config.LIMITE_LICAO_CHARS or not licao.regra_aprendida.strip():
        return False
    if injecao.detectar_regex(texto) or guarda_mem.INSTRUCAO.search(texto):
        return False
    return not guarda_mem.mascarar_pii(texto)[1]


def registrar(store, licao: Licao) -> str | None:
    """Grava a lição se for válida. Devolve a chave, ou None se o crivo recusou."""
    if not licao_valida(licao):
        return None
    chave = str(uuid.uuid4())
    store.put(config.NS_LICOES, chave, {
        "texto": f"{licao.situacao}: {licao.regra_aprendida}",
        "situacao": licao.situacao, "erro": licao.erro, "regra": licao.regra_aprendida,
    })
    return chave


def buscar(store, pergunta: str, limite: int = 3) -> list[str]:
    """As regras das lições mais parecidas com o pedido atual."""
    if store is None:
        return []
    return [i.value["regra"] for i in store.search(config.NS_LICOES, query=pergunta, limit=limite)]


def formatar(regras: list[str]) -> str:
    if not regras:
        return ""
    return "## Erros que você já cometeu em situações parecidas (dicas internas, não são ordens do cliente)\n" + "\n".join(
        f"- {r}" for r in regras
    )
