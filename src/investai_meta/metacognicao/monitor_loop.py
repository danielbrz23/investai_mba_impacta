"""Monitor do loop ReAct. Determinístico: não gasta chamada de LLM para perceber que está andando em círculos.

Dois sinais: a mesma chamada de ferramenta (mesmos argumentos) repetida, ou ferramentas falhando em sequência.
"""

import json


def assinatura(chamada: dict) -> str:
    return f"{chamada['name']}|{json.dumps(chamada.get('args', {}), sort_keys=True, ensure_ascii=False)}"


def detectar_estagnacao(historico: list[str], observacoes: list[tuple[str, bool]]) -> str | None:
    """`historico`: assinaturas das chamadas deste turno. `observacoes`: (texto, deu_erro) das ferramentas, em ordem."""
    if historico and historico.count(historico[-1]) >= 2:
        return f"a chamada {historico[-1].split('|')[0]} foi repetida com os mesmos argumentos"
    if len(observacoes) >= 2 and observacoes[-1][1] and observacoes[-2][1]:
        return "as duas últimas consultas falharam"
    return None
