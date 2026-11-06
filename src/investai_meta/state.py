"""Estado do grafo (com metacognição) e contexto da execução."""

from dataclasses import dataclass
from typing import Annotated

from langgraph.graph import MessagesState


def acumular(atual: list | None, novo: list | None) -> list:
    """Reducer da trilha: soma as entradas; `None` zera (início de cada turno)."""
    return [] if novo is None else (atual or []) + novo


class EstadoInvestidor(MessagesState):
    # --- herdado da pasta 1 ---
    bloqueado: bool
    motivo_bloqueio: str
    contexto_memoria: str       # perfil + trechos do guia (+ lições e avisos), montado em carregar_memoria
    iteracoes_ferramenta: int
    violacoes: list[str]
    memoria_permitida: bool
    texto_memoria: str
    # --- metacognição (recomeça a cada turno, exceto perguntas_feitas) ---
    prompt_sistema: str         # prompt procedural lido do store (ou o padrão)
    plano: list[str]
    pede_recomendacao: bool
    info_faltante: list[str]
    pergunta_ao_cliente: str
    perguntas_feitas: int       # PERSISTE na conversa: limita o interrogatório
    confianca: float
    lacunas: list[str]
    replanejamentos: int
    tentativas_resposta: int    # reescritas já feitas
    historico_ferramentas: list[str]
    acao_monitor: str           # "", "replanejar" ou "forcar"
    observacao_monitor: str
    forcar_resposta: bool       # responder agora, sem novas ferramentas
    violacoes_fatos: list[str]
    licoes_usadas: list[str]
    licao_motivo: str
    trilha_metacognitiva: Annotated[list[dict], acumular]


@dataclass
class Contexto:
    """Dados da execução que NÃO vêm do LLM: o user_id sai do login da aplicação."""

    user_id: str = "anonimo"
