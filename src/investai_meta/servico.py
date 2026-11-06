"""Camada de serviço: o que a API e a interface chamam. Não conhece FastAPI nem Gradio."""

import io
import re
from dataclasses import dataclass

import pandas as pd
from langgraph.types import Command

from investai_meta import config, db, memoria
from investai_meta.state import Contexto

PADRAO_USER_ID = r"^[A-Za-z0-9_-]{1,64}$"  # sem ponto: o ponto separa os níveis do namespace no store
_RE_USER_ID = re.compile(PADRAO_USER_ID)


@dataclass
class Backend:
    grafo: object
    conn: object   # conexão das tabelas do projeto (ordens, feedbacks, cache)
    store: object  # memória semântica
    llm: object = None  # usado para transformar feedback negativo em lição


def backend_padrao(caminho=config.CAMINHO_DB) -> Backend:
    """Monta o backend real: SQLite local, Gemini e o grafo compilado com checkpointer e store."""
    from investai_meta import tools
    from investai_meta.graph import build_graph
    from investai_meta.llm import criar_embeddings, criar_llm

    conn = db.conectar(caminho)
    tools.definir_servicos(conn)
    store = db.abrir_store(caminho, embeddings=criar_embeddings())
    llm = criar_llm()
    return Backend(build_graph(db.abrir_checkpointer(caminho), store, llm), conn, store, llm)


def validar_user_id(user_id: str) -> str:
    if not _RE_USER_ID.match(user_id or ""):
        raise ValueError("user_id inválido: use de 1 a 64 letras, números, '_' ou '-'.")
    return user_id


def _cfg(user_id: str, thread_id: str) -> dict:
    # O user_id entra no thread_id interno: um cliente não consegue abrir a conversa de outro.
    return {"configurable": {"thread_id": f"{user_id}:{thread_id}"}, "recursion_limit": config.RECURSION_LIMIT}


def _proposta_pendente(grafo, cfg) -> dict | None:
    propostas = [i.value for t in grafo.get_state(cfg).tasks for i in t.interrupts]
    return propostas[0] if propostas else None


def _metacognicao(resultado) -> dict:
    """O que o agente 'pensou' neste turno: plano, confiança, lacunas, lições usadas e a trilha de decisões."""
    return {
        "plano": resultado.get("plano", []),
        "confianca": resultado.get("confianca"),
        "lacunas": resultado.get("lacunas", []),
        "licoes_usadas": resultado.get("licoes_usadas", []),
        "reescritas": resultado.get("tentativas_resposta", 0),
        "replanejamentos": resultado.get("replanejamentos", 0),
        "trilha": resultado.get("trilha_metacognitiva", []),
    }


def _responder(grafo, cfg, resultado) -> dict:
    ordem = _proposta_pendente(grafo, cfg)
    if ordem:
        texto = (
            f"Para registrar a ordem de {ordem['ordem']} de R$ {ordem['valor']:.2f} em {ordem['produto']}, "
            "preciso da sua confirmação."
        )
    else:
        ultima = next((m for m in reversed(resultado["messages"]) if m.type == "ai" and m.text), None)
        texto = ultima.text if ultima else ""
    return {
        "resposta": texto, "ordem_pendente": ordem, "bloqueado": bool(resultado.get("bloqueado")),
        "metacognicao": _metacognicao(resultado),
    }


def conversar(backend: Backend, user_id: str, thread_id: str, mensagem: str) -> dict:
    validar_user_id(user_id)
    cfg, contexto = _cfg(user_id, thread_id), Contexto(user_id)
    if _proposta_pendente(backend.grafo, cfg):  # nova mensagem com ordem em aberto = cliente desistiu
        backend.grafo.invoke(Command(resume={"aprovado": False}), cfg, context=contexto)
    resultado = backend.grafo.invoke({"messages": [("user", mensagem)]}, cfg, context=contexto)
    return _responder(backend.grafo, cfg, resultado)


def retomar(backend: Backend, user_id: str, thread_id: str, aprovado: bool) -> dict:
    validar_user_id(user_id)
    cfg = _cfg(user_id, thread_id)
    if not _proposta_pendente(backend.grafo, cfg):
        raise LookupError("Não há ordem aguardando confirmação nesta conversa.")
    resultado = backend.grafo.invoke(Command(resume={"aprovado": aprovado}), cfg, context=Contexto(user_id))
    return _responder(backend.grafo, cfg, resultado)


def registrar_feedback(backend: Backend, user_id: str, thread_id: str, nota: int, comentario: str | None = None) -> dict:
    """👍/👎 do cliente. O 👎 também vira uma lição (Reflexion) para o agente não repetir o erro."""
    validar_user_id(user_id)
    feedback_id = db.inserir_feedback(backend.conn, user_id, thread_id, nota, comentario)
    licao_gravada = False
    if nota == -1 and backend.llm is not None:
        from investai_meta.metacognicao import licoes
        from investai_meta.schemas import Licao

        mensagens = backend.grafo.get_state(_cfg(user_id, thread_id)).values.get("messages", [])
        pedido = next((m.text for m in reversed(mensagens) if m.type == "human"), "")
        motivo = f"o cliente reprovou a resposta (👎): {comentario or 'sem comentário'}"
        licao = licoes.gerar_licao(backend.llm.with_structured_output(Licao), pedido, motivo)
        licao_gravada = licoes.registrar(backend.store, licao) is not None
    return {"feedback_id": feedback_id, "licao_gravada": licao_gravada}


def listar_licoes(backend: Backend) -> list[dict]:
    return [{"regra": i.value["regra"], "situacao": i.value["situacao"], "erro": i.value["erro"]}
            for i in backend.store.search(config.NS_LICOES, limit=100)]


def listar_ordens(backend: Backend, user_id: str | None = None) -> list[dict]:
    return db.listar_ordens(backend.conn, validar_user_id(user_id) if user_id else None)


def ordens_em_excel(backend: Backend, user_id: str | None = None) -> bytes:
    colunas = ["id", "criado_em", "user_id", "produto_id", "tipo", "valor", "status", "thread_id"]
    quadro = pd.DataFrame(listar_ordens(backend, user_id), columns=colunas)
    buffer = io.BytesIO()
    quadro.to_excel(buffer, index=False, sheet_name="ordens", engine="openpyxl")
    return buffer.getvalue()


def ver_memoria(backend: Backend, user_id: str) -> dict:
    return {"perfil": memoria.ler_perfil(backend.store, validar_user_id(user_id))}
