"""Planejamento (Plan-and-Execute, seção 2.11 do notebook) e replanejamento."""

import json

from langchain_core.messages import HumanMessage, SystemMessage

from investai_meta import config
from investai_meta.prompts import PROMPT_PLANEJADOR, PROMPT_REPLANEJADOR
from investai_meta.schemas import Plano, Replano


def plano_padrao() -> Plano:
    """Se o planejador falhar, o agente segue sem plano: metacognição nunca derruba o atendimento."""
    return Plano(pede_recomendacao=False, passos=["responder ao pedido do cliente"])


def planejar(juiz, pergunta: str, perfil: dict | None, licoes: str = "") -> Plano:
    try:
        return juiz.invoke([
            SystemMessage(PROMPT_PLANEJADOR),
            HumanMessage(
                f"<perfil_salvo>{json.dumps(perfil, ensure_ascii=False) if perfil else 'nenhum'}</perfil_salvo>\n"
                f"<licoes>{licoes or 'nenhuma'}</licoes>\n"
                f"<mensagem_do_cliente>\n{pergunta}\n</mensagem_do_cliente>"
            ),
        ])
    except Exception:
        return plano_padrao()


def deve_perguntar(plano: Plano, perguntas_feitas: int) -> bool:
    """Pergunta ao cliente só quando é pedido de recomendação, falta algo essencial e ainda não houve interrogatório demais."""
    return bool(
        plano.pede_recomendacao
        and plano.info_faltante
        and plano.pergunta_ao_cliente.strip()
        and perguntas_feitas < config.MAX_PERGUNTAS_POR_CONVERSA
    )


def replanejar(juiz, plano: list[str], evidencias: str, motivo: str) -> Replano:
    try:
        return juiz.invoke([
            SystemMessage(PROMPT_REPLANEJADOR),
            HumanMessage(
                f"<plano_atual>{json.dumps(plano, ensure_ascii=False)}</plano_atual>\n"
                f"<motivo>{motivo}</motivo>\n<evidencias>{evidencias[:3000] or 'nenhuma'}</evidencias>"
            ),
        ])
    except Exception:
        return Replano(novos_passos=plano, desistir=True)  # sem replanejador, o mais seguro é responder com o que há
