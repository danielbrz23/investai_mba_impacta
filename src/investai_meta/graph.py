"""Grafo do assessor de investimentos com METACOGNIÇÃO (pasta 2).

Mesmo esqueleto da pasta 1, mais os nós ★ em que o agente pensa sobre o próprio trabalho:

START → guarda_entrada → carregar_memoria(★lições, ★prompt procedural) → ★planejar ─┬─ ★perguntar_cliente → guarda_memoria
                                                                                     └→ agente ⇄ ferramentas → ★monitor_loop ─→ ★replanejar
agente → ★autoavaliar ─(confiança baixa)→ ★replanejar → agente
              ↓
        ★verificar_fatos → guarda_resposta ─(reprovada)→ ★reescrever → ★verificar_fatos
              ↓                          └─(esgotou)→ resposta_segura → ★registrar_licao
        guarda_memoria → memorizar (★com reflexão sobre contradições) → END
"""

import logging

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.runtime import Runtime
from langgraph.types import RetryPolicy

from investai_meta import config, memoria
from investai_meta.guardrails import injecao, resposta
from investai_meta.guardrails import memoria as guarda_mem
from investai_meta.llm import criar_llm
from investai_meta.metacognicao import autocritica, autoavaliacao, licoes, monitor_loop, planejador, procedural, reflexao_memoria, verificacao
from investai_meta.prompts import (
    DISCLAIMER, MENSAGEM_BLOQUEIO, MENSAGEM_INDISPONIVEL, MENSAGEM_SEGURA, MENSAGEM_VAZIA, PERGUNTA_PADRAO,
)
from investai_meta.schemas import (
    Autoavaliacao, Licao, Plano, Reescrita, Replano, VeredictoInjecao, VeredictoMemoria, VeredictoResposta,
)
from investai_meta.state import Contexto, EstadoInvestidor
from investai_meta.tools import FERRAMENTAS

logger = logging.getLogger("investai_meta")


def _ultima_humana(estado) -> HumanMessage | None:
    return next((m for m in reversed(estado["messages"]) if m.type == "human"), None)


def _ultima_ia(estado) -> AIMessage | None:
    return next((m for m in reversed(estado["messages"]) if m.type == "ai"), None)


def _ferramentas_do_turno(estado) -> list[ToolMessage]:
    saidas = []
    for m in reversed(estado["messages"]):
        if m.type == "human":
            break
        if isinstance(m, ToolMessage):
            saidas.append(m)
    return list(reversed(saidas))


def _evidencias(estado) -> str:
    return "\n".join(str(m.content) for m in _ferramentas_do_turno(estado))


def _passo(no: str, decisao: str, motivo: str = "") -> list[dict]:
    """Uma entrada da trilha metacognitiva (aparece na API, na interface e no trace)."""
    return [{"no": no, "decisao": decisao, "motivo": motivo}]


def build_graph(checkpointer=None, store=None, llm=None):
    """Monta e compila o grafo. Sem argumentos serve ao Studio, que injeta store e checkpointer."""
    llm = llm or criar_llm()
    llm_com_ferramentas = llm.bind_tools(FERRAMENTAS)
    juiz_injecao = llm.with_structured_output(VeredictoInjecao)
    juiz_resposta = llm.with_structured_output(VeredictoResposta)
    juiz_memoria = llm.with_structured_output(VeredictoMemoria)
    juiz_plano = llm.with_structured_output(Plano)
    juiz_replano = llm.with_structured_output(Replano)
    juiz_auto = llm.with_structured_output(Autoavaliacao)
    juiz_reescrita = llm.with_structured_output(Reescrita)
    juiz_licao = llm.with_structured_output(Licao)
    tentar_de_novo = RetryPolicy(max_attempts=3, initial_interval=2.0)

    # --- Guardrail de entrada (igual à pasta 1) + reset dos campos do turno -------------------
    def guarda_entrada(estado: EstadoInvestidor, runtime: Runtime[Contexto]):
        zerar = {
            "bloqueado": False, "motivo_bloqueio": "", "iteracoes_ferramenta": 0, "violacoes": [],
            "memoria_permitida": False, "texto_memoria": "", "contexto_memoria": "",
            # metacognição: tudo recomeça a cada mensagem (menos perguntas_feitas, que vale pela conversa)
            "prompt_sistema": "", "plano": [], "pede_recomendacao": False, "info_faltante": [], "pergunta_ao_cliente": "",
            "confianca": 1.0, "lacunas": [], "replanejamentos": 0, "tentativas_resposta": 0, "historico_ferramentas": [],
            "acao_monitor": "", "observacao_monitor": "", "forcar_resposta": False, "violacoes_fatos": [],
            "licoes_usadas": [], "licao_motivo": "", "trilha_metacognitiva": None,
        }
        humana = _ultima_humana(estado)
        texto = (humana.text if humana else "").strip()
        if not texto:
            return {**zerar, "bloqueado": True, "motivo_bloqueio": "vazio"}
        if len(texto) > config.MAX_CHARS_ENTRADA:
            return {**zerar, "bloqueado": True, "motivo_bloqueio": "mensagem muito longa"}
        try:
            veredito = injecao.verificar_entrada(texto, juiz_injecao)
        except Exception:
            logger.exception("juiz de injeção indisponível; mensagem recusada por precaução")
            return {**zerar, "bloqueado": True, "motivo_bloqueio": "verificação indisponível"}
        if veredito.e_injecao or veredito.categoria != "ok":
            logger.warning("entrada bloqueada: %s (%s)", veredito.categoria, veredito.motivo)
            return {**zerar, "bloqueado": True, "motivo_bloqueio": f"{veredito.categoria}: {veredito.motivo}"}
        return zerar

    def resposta_bloqueada(estado: EstadoInvestidor):
        motivo = estado.get("motivo_bloqueio", "")
        texto = {"vazio": MENSAGEM_VAZIA, "verificação indisponível": MENSAGEM_INDISPONIVEL}.get(motivo, MENSAGEM_BLOQUEIO)
        mensagens = [AIMessage(texto)]
        humana = _ultima_humana(estado)
        if humana and motivo != "vazio":
            mensagens.insert(0, RemoveMessage(id=humana.id))
        return {"messages": mensagens}

    # --- Memória (★ lições, ★ prompt procedural, ★ mudança de perfil pendente) ---------------
    def carregar_memoria(estado: EstadoInvestidor, runtime: Runtime[Contexto]):
        pergunta = _ultima_humana(estado).text
        user_id, st = runtime.context.user_id, runtime.store
        contexto = memoria.montar_contexto(st, user_id, pergunta)
        regras = licoes.buscar(st, pergunta)
        extras = [licoes.formatar(regras), reflexao_memoria.aviso_para_o_agente(reflexao_memoria.ler_pendente(st, user_id))]
        contexto = "\n\n".join(p for p in [contexto, *extras] if p)
        return {
            "contexto_memoria": contexto, "prompt_sistema": procedural.prompt_atual(st), "licoes_usadas": regras,
            "trilha_metacognitiva": _passo("carregar_memoria", f"{len(regras)} lição(ões) aplicada(s)") if regras else [],
        }

    # --- ★ Planejamento -----------------------------------------------------------------------
    def planejar(estado: EstadoInvestidor, runtime: Runtime[Contexto]):
        perfil = memoria.ler_perfil(runtime.store, runtime.context.user_id)
        plano = planejador.planejar(juiz_plano, _ultima_humana(estado).text, perfil, licoes.formatar(estado.get("licoes_usadas", [])))
        perguntar = planejador.deve_perguntar(plano, estado.get("perguntas_feitas", 0))
        return {
            "plano": plano.passos, "pede_recomendacao": plano.pede_recomendacao, "info_faltante": plano.info_faltante,
            "pergunta_ao_cliente": plano.pergunta_ao_cliente if perguntar else "",
            "trilha_metacognitiva": _passo(
                "planejar", "perguntar ao cliente" if perguntar else "executar",
                ("falta: " + ", ".join(plano.info_faltante)) if plano.info_faltante else "; ".join(plano.passos),
            ),
        }

    def perguntar_cliente(estado: EstadoInvestidor):
        pergunta = estado["pergunta_ao_cliente"]
        if resposta.validar_resposta(pergunta, None, []):  # a pergunta vem de LLM: mesma cautela de qualquer saída
            pergunta = PERGUNTA_PADRAO
        return {
            "messages": [AIMessage(pergunta)], "perguntas_feitas": estado.get("perguntas_feitas", 0) + 1,
            "trilha_metacognitiva": _passo("perguntar_cliente", "pergunta enviada", pergunta),
        }

    # --- Loop ReAct (+ ★ monitor) ---------------------------------------------------------------
    def agente(estado: EstadoInvestidor):
        voltas = estado.get("iteracoes_ferramenta", 0)
        pode_usar_ferramentas = voltas < config.MAX_ITER and not estado.get("forcar_resposta")
        sistema = (estado.get("prompt_sistema") or "") + "\n\n" + estado.get("contexto_memoria", "")
        if estado.get("plano"):
            sistema += "\n\n## Seu plano para este pedido\n" + "\n".join(f"{i}. {p}" for i, p in enumerate(estado["plano"], 1))
        if estado.get("observacao_monitor"):
            sistema += f"\n\n## Atenção\n{estado['observacao_monitor']}"
        if not pode_usar_ferramentas:
            sistema += "\n\nLimite de consultas atingido. Responda agora com o que já obteve, sem inventar dados, e diga o que não conseguiu obter."
        modelo = llm_com_ferramentas if pode_usar_ferramentas else llm
        resultado = modelo.invoke([SystemMessage(sistema), *estado["messages"]])
        atualizacao = {"messages": [resultado]}
        chamadas = getattr(resultado, "tool_calls", None) or []
        if chamadas:
            atualizacao["iteracoes_ferramenta"] = voltas + 1
            atualizacao["historico_ferramentas"] = estado.get("historico_ferramentas", []) + [monitor_loop.assinatura(c) for c in chamadas]
        return atualizacao

    def monitor(estado: EstadoInvestidor):
        observacoes = [(str(m.content), m.status == "error") for m in _ferramentas_do_turno(estado)]
        motivo = monitor_loop.detectar_estagnacao(estado.get("historico_ferramentas", []), observacoes)
        if not motivo:
            return {"acao_monitor": ""}
        acao = "replanejar" if estado.get("replanejamentos", 0) < config.MAX_REPLANEJAMENTOS else "forcar"
        logger.warning("monitor do loop: %s -> %s", motivo, acao)
        return {
            "acao_monitor": acao,
            "observacao_monitor": f"A estratégia atual não está progredindo: {motivo}. Não repita a mesma consulta.",
            "forcar_resposta": acao == "forcar",
            "trilha_metacognitiva": _passo("monitor_loop", acao, motivo),
        }

    def replanejar(estado: EstadoInvestidor):
        """Chamado pelo monitor (loop travado) ou pela autoavaliação (confiança baixa)."""
        motivo = estado.get("observacao_monitor") or ("lacunas: " + "; ".join(estado.get("lacunas", [])))
        novo = planejador.replanejar(juiz_replano, estado.get("plano", []), _evidencias(estado), motivo)
        atualizacao = {
            "plano": novo.novos_passos, "replanejamentos": estado.get("replanejamentos", 0) + 1, "acao_monitor": "",
            "forcar_resposta": novo.desistir,
            "observacao_monitor": motivo,  # o agente lê o motivo na próxima volta
            "trilha_metacognitiva": _passo("replanejar", "responder com o que há" if novo.desistir else "novo plano", motivo),
        }
        ultima = _ultima_ia(estado)
        if ultima is not None and not ultima.tool_calls and estado["messages"][-1].type == "ai":
            atualizacao["messages"] = [RemoveMessage(id=ultima.id)]  # o rascunho insatisfatório sai; o histórico volta a terminar em dado
        return atualizacao

    # --- ★ Autoavaliação e ★ verificação de fatos -------------------------------------------------
    def autoavaliar(estado: EstadoInvestidor, runtime: Runtime[Contexto]):
        perfil = memoria.ler_perfil(runtime.store, runtime.context.user_id)
        avaliacao = autoavaliacao.autoavaliar(
            juiz_auto, _ultima_humana(estado).text, perfil, estado.get("plano", []), _evidencias(estado), _ultima_ia(estado).text,
        )
        baixa = avaliacao.confianca < config.LIMIAR_CONFIANCA
        replanejar_agora = baixa and estado.get("replanejamentos", 0) < config.MAX_REPLANEJAMENTOS
        return {
            "confianca": avaliacao.confianca, "lacunas": avaliacao.lacunas,
            "acao_monitor": "replanejar" if replanejar_agora else "",
            "observacao_monitor": ("Seu rascunho anterior tinha lacunas: " + "; ".join(avaliacao.lacunas) + ". Use as ferramentas para preenchê-las.")
            if replanejar_agora else estado.get("observacao_monitor", ""),
            "trilha_metacognitiva": _passo(
                "autoavaliar", f"confiança {avaliacao.confianca:.2f}" + (" → replanejar" if replanejar_agora else ""),
                "; ".join(avaliacao.lacunas) or avaliacao.justificativa,
            ),
        }

    def verificar_fatos(estado: EstadoInvestidor, runtime: Runtime[Contexto]):
        fontes = [
            _evidencias(estado), estado.get("contexto_memoria", ""), DISCLAIMER,
            *[m.text for m in estado["messages"] if m.type == "human"],
        ]
        violacoes = verificacao.verificar(_ultima_ia(estado).text, fontes)
        return {
            "violacoes_fatos": violacoes,
            "trilha_metacognitiva": _passo("verificar_fatos", "números sem fonte" if violacoes else "números conferem", "; ".join(violacoes)),
        }

    # --- Guardrail de resposta (+ ★ aviso de incerteza) -------------------------------------------
    def guarda_resposta(estado: EstadoInvestidor, runtime: Runtime[Contexto]):
        ultima = _ultima_ia(estado)
        texto = ultima.text
        perfil = memoria.ler_perfil(runtime.store, runtime.context.user_id)
        cartoes = memoria.carregar_cartoes(runtime.store)
        violacoes = list(estado.get("violacoes_fatos", [])) + resposta.validar_resposta(texto, perfil, cartoes)
        if not violacoes:
            violacoes = resposta.julgar_resposta(texto, perfil, _evidencias(estado), juiz_resposta)
        if violacoes:
            logger.warning("resposta reprovada: %s | texto: %.300s", violacoes, texto)
            return {"violacoes": violacoes}
        final = resposta.garantir_disclaimer(texto, cartoes)
        atualizacao: dict = {"violacoes": []}
        if estado.get("confianca", 1.0) < config.LIMIAR_CONFIANCA:
            final = f"{final.rstrip()}\n\n{autoavaliacao.aviso_de_incerteza(estado.get('lacunas', []))}"
            atualizacao["licao_motivo"] = "baixa confiança: " + "; ".join(estado.get("lacunas", []))
        if final != texto:
            atualizacao["messages"] = [RemoveMessage(id=ultima.id), AIMessage(final)]
        return atualizacao

    def reescrever(estado: EstadoInvestidor, runtime: Runtime[Contexto]):
        perfil = memoria.ler_perfil(runtime.store, runtime.context.user_id)
        ultima = _ultima_ia(estado)
        nova = autocritica.reescrever(
            juiz_reescrita, _ultima_humana(estado).text, ultima.text, estado["violacoes"], _evidencias(estado), perfil,
        )
        return {
            "messages": [RemoveMessage(id=ultima.id), AIMessage(nova.texto)],
            "tentativas_resposta": estado.get("tentativas_resposta", 0) + 1,
            "trilha_metacognitiva": _passo("reescrever", f"reescrita {estado.get('tentativas_resposta', 0) + 1}", nova.critica),
        }

    def resposta_segura(estado: EstadoInvestidor):
        return {
            "messages": [RemoveMessage(id=_ultima_ia(estado).id), AIMessage(MENSAGEM_SEGURA)],
            "licao_motivo": "resposta reprovada pelos guardrails: " + "; ".join(estado.get("violacoes", [])),
            "trilha_metacognitiva": _passo("resposta_segura", "desistiu de reescrever", "; ".join(estado.get("violacoes", []))),
        }

    # --- ★ Reflexion: transformar a falha em lição -------------------------------------------------
    def registrar_licao(estado: EstadoInvestidor, runtime: Runtime[Contexto]):
        if runtime.store is None or not estado.get("licao_motivo"):
            return {}
        try:
            licao = licoes.gerar_licao(juiz_licao, _ultima_humana(estado).text, estado["licao_motivo"])
            chave = licoes.registrar(runtime.store, licao)
        except Exception:
            logger.exception("não foi possível registrar a lição")
            return {}
        return {"trilha_metacognitiva": _passo("registrar_licao", "lição gravada" if chave else "lição recusada pelo crivo", licao.regra_aprendida)}

    # --- Guardrail de memória e gravação (★ com reflexão) ------------------------------------------
    def guarda_memoria(estado: EstadoInvestidor, runtime: Runtime[Contexto]):
        texto = _ultima_humana(estado).text
        veredito, mascarado, pii = guarda_mem.decidir_memoria(texto, juiz_memoria)
        if pii:
            logger.info("PII mascarada antes da memória: %s", pii)
        # Um "sim, confirmo" não fala do cliente, mas é o que libera a mudança de perfil pendente.
        confirmando = bool(reflexao_memoria.ler_pendente(runtime.store, runtime.context.user_id)) and bool(reflexao_memoria.CONFIRMA.search(texto))
        permitido = veredito.persistir and (guarda_mem.parece_informacao_pessoal(mascarado) or confirmando)
        return {"memoria_permitida": permitido, "texto_memoria": mascarado if permitido else ""}

    def memorizar(estado: EstadoInvestidor, runtime: Runtime[Contexto]):
        if not estado.get("memoria_permitida") or runtime.store is None:
            return {}
        user_id, st = runtime.context.user_id, runtime.store
        try:
            antigo = memoria.ler_perfil(st, user_id)
            pendente = reflexao_memoria.ler_pendente(st, user_id)
            memoria.atualizar_perfil(llm, st, user_id, estado["texto_memoria"])
            novo = memoria.ler_perfil(st, user_id)
            acao, motivo = reflexao_memoria.decidir(antigo, novo, estado["texto_memoria"], pendente)
            if acao != "ok":
                logger.warning("reflexão sobre a memória: %s (%s)", acao, motivo)
                reflexao_memoria.executar(st, user_id, acao, motivo, antigo, novo, pendente)
                return {"trilha_metacognitiva": _passo("memorizar", acao, motivo)}
        except Exception:
            logger.exception("falha ao atualizar a memória; a resposta ao cliente não é afetada")
        return {}

    # --- Roteamento ---------------------------------------------------------------------------------
    def apos_planejar(estado):
        return "perguntar_cliente" if estado.get("pergunta_ao_cliente") else "agente"

    def apos_monitor(estado):
        return "replanejar" if estado.get("acao_monitor") == "replanejar" else "agente"

    def apos_autoavaliar(estado):
        return "replanejar" if estado.get("acao_monitor") == "replanejar" else "verificar_fatos"

    def apos_guarda_resposta(estado):
        if estado.get("violacoes"):
            return "reescrever" if estado.get("tentativas_resposta", 0) < config.MAX_REESCRITAS else "resposta_segura"
        return "registrar_licao" if estado.get("licao_motivo") else "guarda_memoria"

    construtor = StateGraph(EstadoInvestidor, context_schema=Contexto)
    for nome, funcao in [
        ("guarda_entrada", guarda_entrada), ("carregar_memoria", carregar_memoria), ("planejar", planejar),
        ("agente", agente), ("autoavaliar", autoavaliar), ("verificar_fatos", verificar_fatos),
        ("guarda_resposta", guarda_resposta), ("reescrever", reescrever), ("replanejar", replanejar),
        ("registrar_licao", registrar_licao), ("guarda_memoria", guarda_memoria),
    ]:
        construtor.add_node(nome, funcao, retry_policy=tentar_de_novo)
    construtor.add_node("resposta_bloqueada", resposta_bloqueada)
    construtor.add_node("perguntar_cliente", perguntar_cliente)
    construtor.add_node("ferramentas", ToolNode(FERRAMENTAS, handle_tool_errors=True))
    construtor.add_node("monitor_loop", monitor)
    construtor.add_node("resposta_segura", resposta_segura)
    construtor.add_node("memorizar", memorizar)

    construtor.add_edge(START, "guarda_entrada")
    construtor.add_conditional_edges(
        "guarda_entrada", lambda e: "resposta_bloqueada" if e["bloqueado"] else "carregar_memoria",
        ["resposta_bloqueada", "carregar_memoria"],
    )
    construtor.add_edge("resposta_bloqueada", END)
    construtor.add_edge("carregar_memoria", "planejar")
    construtor.add_conditional_edges("planejar", apos_planejar, ["perguntar_cliente", "agente"])
    construtor.add_edge("perguntar_cliente", "guarda_memoria")
    construtor.add_conditional_edges("agente", tools_condition, {"tools": "ferramentas", END: "autoavaliar"})
    construtor.add_edge("ferramentas", "monitor_loop")
    construtor.add_conditional_edges("monitor_loop", apos_monitor, ["replanejar", "agente"])
    construtor.add_edge("replanejar", "agente")
    construtor.add_conditional_edges("autoavaliar", apos_autoavaliar, ["replanejar", "verificar_fatos"])
    construtor.add_edge("verificar_fatos", "guarda_resposta")
    construtor.add_conditional_edges(
        "guarda_resposta", apos_guarda_resposta, ["reescrever", "resposta_segura", "registrar_licao", "guarda_memoria"],
    )
    construtor.add_edge("reescrever", "verificar_fatos")
    construtor.add_edge("resposta_segura", "registrar_licao")
    construtor.add_edge("registrar_licao", "guarda_memoria")
    construtor.add_edge("guarda_memoria", "memorizar")
    construtor.add_edge("memorizar", END)
    return construtor.compile(checkpointer=checkpointer, store=store)
