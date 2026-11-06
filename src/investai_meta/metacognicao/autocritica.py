"""Autocrítica e reescrita (Reflection, seção 2.12 do notebook): o agente corrige a própria resposta reprovada."""

import json

from langchain_core.messages import HumanMessage, SystemMessage

from investai_meta.prompts import PROMPT_REESCRITA
from investai_meta.schemas import Reescrita


def reescrever(juiz, pedido: str, rascunho: str, violacoes: list[str], evidencias: str, perfil: dict | None) -> Reescrita:
    return juiz.invoke([
        SystemMessage(PROMPT_REESCRITA),
        HumanMessage(
            f"<pedido>{pedido}</pedido>\n<perfil>{json.dumps(perfil, ensure_ascii=False) if perfil else 'não informado'}</perfil>\n"
            f"<violacoes>\n- " + "\n- ".join(violacoes) + f"\n</violacoes>\n<evidencias>{evidencias[:4000] or 'nenhuma'}</evidencias>\n"
            f"<rascunho_reprovado>\n{rascunho}\n</rascunho_reprovado>"
        ),
    ])
