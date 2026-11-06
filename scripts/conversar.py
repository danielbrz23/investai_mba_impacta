"""Conversa com o agente no terminal (usa o Gemini de verdade). Uso: python scripts/conversar.py [user_id]

Mostra as ferramentas chamadas e, quando o agente propõe uma ordem, pergunta se você aprova.
"""

import sys
import uuid

import _caminhos  # noqa: F401
from langgraph.types import Command

from investai_meta import config, db, tools
from investai_meta.graph import build_graph
from investai_meta.llm import criar_embeddings
from investai_meta.state import Contexto


def imprimir_passos(grafo, entrada, cfg, contexto):
    """Roda o grafo mostrando cada chamada de ferramenta; devolve o estado final."""
    for modo, dado in grafo.stream(entrada, cfg, context=contexto, stream_mode=["updates", "values"]):
        if modo == "updates":
            for no, atualizacao in dado.items():
                for msg in (atualizacao or {}).get("messages", []) if isinstance(atualizacao, dict) else []:
                    for chamada in getattr(msg, "tool_calls", None) or []:
                        print(f"  [ferramenta] {chamada['name']}({chamada['args']})")
        else:
            ultimo = dado
    return ultimo


if __name__ == "__main__":
    user_id = sys.argv[1] if len(sys.argv) > 1 else "demo"
    conn = db.conectar()
    tools.definir_servicos(conn)
    grafo = build_graph(db.abrir_checkpointer(), db.abrir_store(embeddings=criar_embeddings()))
    thread = f"{user_id}-{uuid.uuid4().hex[:6]}"
    cfg = {"configurable": {"thread_id": thread}, "recursion_limit": config.RECURSION_LIMIT}
    contexto = Contexto(user_id)
    print(f"Cliente: {user_id} | conversa: {thread} | Ctrl+D para sair\n")
    while True:
        try:
            texto = input("Você: ").strip()
        except EOFError:
            break
        entrada = {"messages": [("user", texto)]}
        while True:
            estado = imprimir_passos(grafo, entrada, cfg, contexto)
            pendente = grafo.get_state(cfg).tasks
            propostas = [i.value for t in pendente for i in t.interrupts]
            if not propostas:
                break
            p = propostas[0]
            resposta = input(f"  >> Confirmar {p['ordem']} de R$ {p['valor']:.2f} em {p['produto']}? [s/N] ").strip().lower()
            entrada = Command(resume={"aprovado": resposta == "s"})
        print(f"\nAssessor: {estado['messages'][-1].text}\n")
        print(f"  [confiança {estado.get('confianca', 1):.2f}] [plano] {' → '.join(estado.get('plano') or [])}")
        for t in estado.get("trilha_metacognitiva", []):
            print(f"  [metacognição] {t['no']}: {t['decisao']}" + (f" ({t['motivo'][:90]})" if t["motivo"] else ""))
        print()
