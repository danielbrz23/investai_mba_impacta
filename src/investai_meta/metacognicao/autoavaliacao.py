"""Autoavaliação: o agente estima a própria confiança e aponta o que não sabe."""

import json

from langchain_core.messages import HumanMessage, SystemMessage

from investai_meta.prompts import AVISO_INCERTEZA, PROMPT_AUTOAVALIACAO
from investai_meta.schemas import Autoavaliacao


def autoavaliar(juiz, pergunta: str, perfil: dict | None, plano: list[str], evidencias: str, rascunho: str) -> Autoavaliacao:
    try:
        resultado = juiz.invoke([
            SystemMessage(PROMPT_AUTOAVALIACAO),
            HumanMessage(
                f"<pedido>{pergunta}</pedido>\n<perfil>{json.dumps(perfil, ensure_ascii=False) if perfil else 'não informado'}</perfil>\n"
                f"<plano>{json.dumps(plano, ensure_ascii=False)}</plano>\n<evidencias>{evidencias[:4000] or 'nenhuma'}</evidencias>\n"
                f"<rascunho>\n{rascunho}\n</rascunho>"
            ),
        ])
        return resultado.model_copy(update={"confianca": min(1.0, max(0.0, resultado.confianca))})
    except Exception:
        return Autoavaliacao(confianca=1.0, justificativa="autoavaliação indisponível")


def aviso_de_incerteza(lacunas: list[str]) -> str:
    return AVISO_INCERTEZA.format(lacunas="; ".join(lacunas) if lacunas else "alguns dados não puderam ser verificados")
