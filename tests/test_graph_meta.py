"""Roteamento do grafo com metacognição: cada teste prova uma decisão que a pasta 1 não toma."""

import pytest
from langchain_core.messages import AIMessage

from conftest import LLMFalso, chamada
from investai_meta import config, db, memoria, tools
from investai_meta.graph import build_graph
from investai_meta.metacognicao import licoes, procedural
from investai_meta.prompts import AVISO_INCERTEZA, MENSAGEM_SEGURA
from investai_meta.schemas import Autoavaliacao, Plano, Reescrita
from investai_meta.state import Contexto


@pytest.fixture
def gravacoes(monkeypatch):
    registradas = []
    monkeypatch.setattr(memoria, "atualizar_perfil", lambda llm, store, user_id, texto: registradas.append((user_id, texto)))
    return registradas


@pytest.fixture
def montar(conn, store, caminho_db):
    tools.definir_servicos(conn, cliente=None)
    return lambda llm: build_graph(checkpointer=db.abrir_checkpointer(caminho_db), store=store, llm=llm)


def conversar(grafo, texto, thread="t1", user="ana"):
    return grafo.invoke(
        {"messages": [("user", texto)]}, {"configurable": {"thread_id": thread}, "recursion_limit": config.RECURSION_LIMIT},
        context=Contexto(user),
    )


def passos(r):
    return [(t["no"], t["decisao"]) for t in r["trilha_metacognitiva"]]


def sequencia(*valores):
    """Veredito que muda a cada chamada: o último valor se repete."""
    restantes = list(valores)
    return lambda _: restantes.pop(0) if len(restantes) > 1 else restantes[0]


PEDE_RECOMENDACAO = Plano(
    pede_recomendacao=True, passos=["descobrir o perfil"], info_faltante=["objetivo", "prazo"],
    pergunta_ao_cliente="Qual é o seu objetivo e em quanto tempo você precisa do dinheiro?",
)


# --- planejamento: perguntar antes de recomendar ------------------------------------------------
def test_pedido_vago_gera_pergunta_em_vez_de_recomendar_as_cegas(montar, gravacoes):
    llm = LLMFalso(respostas=[], veredictos={"Plano": PEDE_RECOMENDACAO})  # o agente NÃO pode ser chamado

    r = conversar(montar(llm), "Onde eu invisto meu dinheiro?")

    assert r["messages"][-1].text == PEDE_RECOMENDACAO.pergunta_ao_cliente
    assert r["perguntas_feitas"] == 1 and llm.vistas == []
    assert ("planejar", "perguntar ao cliente") in passos(r)


def test_pedido_vago_com_info_dada_na_mensagem_segue_para_o_agente(montar, gravacoes):
    plano = PEDE_RECOMENDACAO.model_copy(update={"info_faltante": [], "pergunta_ao_cliente": ""})
    llm = LLMFalso(respostas=[AIMessage("Para reserva de emergência, o Tesouro Selic é uma boa opção.")], veredictos={"Plano": plano})

    r = conversar(montar(llm), "Quero montar minha reserva de emergência, sou conservador e preciso do dinheiro em 1 ano")

    assert "Tesouro Selic" in r["messages"][-1].text and r.get("perguntas_feitas", 0) == 0


def test_agente_para_de_perguntar_depois_do_limite(montar, gravacoes):
    llm = LLMFalso(
        respostas=[AIMessage("Sem mais dados, comece pelo Tesouro Selic, que é de baixo risco.")],
        veredictos={"Plano": PEDE_RECOMENDACAO},
    )
    grafo = montar(llm)

    for texto in ["Onde invisto?", "Não sei, me ajude"]:
        assert conversar(grafo, texto)["messages"][-1].text == PEDE_RECOMENDACAO.pergunta_ao_cliente
    r = conversar(grafo, "Continuo sem saber")

    assert "Tesouro Selic" in r["messages"][-1].text and r["perguntas_feitas"] == config.MAX_PERGUNTAS_POR_CONVERSA


def test_pergunta_gerada_com_promessa_e_trocada_pela_padrao(montar, gravacoes):
    plano = PEDE_RECOMENDACAO.model_copy(update={"pergunta_ao_cliente": "Quer um retorno garantido e sem risco?"})
    llm = LLMFalso(veredictos={"Plano": plano})

    r = conversar(montar(llm), "Onde invisto?")

    assert "garantido" not in r["messages"][-1].text


# --- monitor do loop ----------------------------------------------------------------------------
def test_chamada_repetida_aciona_o_monitor_e_o_replanejamento(montar, gravacoes):
    igual = dict(valor=1000, taxa_anual=10, meses=6)
    llm = LLMFalso(respostas=[chamada("simular_rendimento", **igual), chamada("simular_rendimento", **igual), AIMessage("Consegui a simulação.")])

    r = conversar(montar(llm), "Simule R$ 1000 a 10% por 6 meses")

    assert ("monitor_loop", "replanejar") in passos(r)
    assert ("replanejar", "novo plano") in passos(r)
    assert r["replanejamentos"] == 1
    assert "não repita a mesma consulta" in llm.vistas[-1][0].content.lower().replace("não repita", "não repita")


def test_sem_orcamento_de_replanejamento_o_monitor_forca_a_resposta(montar, gravacoes, monkeypatch):
    monkeypatch.setattr(config, "MAX_REPLANEJAMENTOS", 0)
    igual = dict(valor=1000, taxa_anual=10, meses=6)
    llm = LLMFalso(respostas=[chamada("simular_rendimento", **igual), chamada("simular_rendimento", **igual), AIMessage("Resumo parcial.")])

    r = conversar(montar(llm), "Simule R$ 1000 a 10% por 6 meses")

    assert ("monitor_loop", "forcar") in passos(r)
    assert "Limite de consultas atingido" in llm.vistas[-1][0].content
    assert r["messages"][-1].text == "Resumo parcial."


# --- autoavaliação ------------------------------------------------------------------------------
def test_confianca_baixa_replaneja_uma_vez_e_depois_avisa_a_incerteza(montar, gravacoes, store):
    baixa = Autoavaliacao(confianca=0.3, lacunas=["taxa atual do CDB"], justificativa="faltou consultar")
    llm = LLMFalso(
        respostas=[AIMessage("Rascunho 1 sem dados."), AIMessage("Rascunho 2 ainda sem a taxa do CDB.")],
        veredictos={"Autoavaliacao": baixa},
    )

    r = conversar(montar(llm), "Quanto rende um CDB hoje?")

    assert r["replanejamentos"] == 1  # um só: o orçamento acaba e o agente segue
    assert r["messages"][-1].text.startswith("Rascunho 2")
    assert r["messages"][-1].text.endswith(AVISO_INCERTEZA.format(lacunas="taxa atual do CDB"))
    assert sum(1 for m in r["messages"] if m.type == "ai") == 1  # o primeiro rascunho saiu do histórico
    assert "Seu rascunho anterior tinha lacunas" in llm.vistas[-1][0].content
    assert licoes.buscar(store, "CDB")  # baixa confiança também vira lição


def test_confianca_alta_nao_replaneja(montar, gravacoes):
    llm = LLMFalso(respostas=[AIMessage("O CDB rende conforme o CDI.")])

    r = conversar(montar(llm), "Como funciona um CDB?")

    assert r["replanejamentos"] == 0 and AVISO_INCERTEZA[:20] not in r["messages"][-1].text


# --- verificação de fatos e autocrítica ---------------------------------------------------------
def test_numero_sem_fonte_forca_reescrita(montar, gravacoes):
    llm = LLMFalso(respostas=[AIMessage("A Selic hoje está em 99,9% ao ano.")], veredictos={
        "Reescrita": Reescrita(critica="o número não veio de ferramenta", texto="Não consegui confirmar a Selic agora."),
    })

    r = conversar(montar(llm), "Qual a Selic?")

    assert r["messages"][-1].text == "Não consegui confirmar a Selic agora."
    assert ("verificar_fatos", "números sem fonte") in passos(r) and ("reescrever", "reescrita 1") in passos(r)


def test_numero_vindo_da_ferramenta_passa_sem_reescrita(montar, gravacoes):
    llm = LLMFalso(respostas=[
        chamada("simular_rendimento", valor=10000, taxa_anual=12, meses=12),
        AIMessage("Você teria R$ 10.960,00 líquidos."),
    ])

    r = conversar(montar(llm), "Quanto rende 10 mil a 12% por 12 meses?")

    assert r["tentativas_resposta"] == 0 and ("verificar_fatos", "números conferem") in passos(r)


def test_reescrita_que_continua_ruim_termina_em_resposta_segura_com_licao(montar, gravacoes, store):
    ruim = Reescrita(critica="tentei de novo", texto="Esse fundo tem retorno garantido.")
    llm = LLMFalso(respostas=[AIMessage("Retorno garantido e sem risco!")], veredictos={"Reescrita": ruim})

    r = conversar(montar(llm), "Qual fundo rende mais?")

    assert r["messages"][-1].text == MENSAGEM_SEGURA
    assert r["tentativas_resposta"] == config.MAX_REESCRITAS
    assert ("resposta_segura", "desistiu de reescrever") in passos(r) and ("registrar_licao", "lição gravada") in passos(r)
    assert licoes.buscar(store, "fundo")


# --- lições e prompt procedural voltam ao agente --------------------------------------------------
def test_licao_antiga_aparece_no_prompt_de_um_pedido_parecido(montar, gravacoes, store):
    from investai_meta.schemas import Licao

    licoes.registrar(store, Licao(situacao="taxa do CDB", erro="citou taxa sem consultar", regra_aprendida="Consulte as taxas antes de citar."))
    llm = LLMFalso(respostas=[AIMessage("Vou consultar.")])

    r = conversar(montar(llm), "Qual a taxa do CDB?")

    assert r["licoes_usadas"] == ["Consulte as taxas antes de citar."]
    assert "Consulte as taxas antes de citar." in llm.vistas[0][0].content
    assert "Erros que você já cometeu" in llm.vistas[0][0].content


def test_prompt_otimizado_do_store_substitui_o_padrao(montar, gravacoes, store):
    procedural.aplicar(store, "PROMPT NOVO DA AULA com dados_nao_confiaveis, registrar_ordem, FGC e Nunca prometa.")
    llm = LLMFalso(respostas=[AIMessage("Olá!")])

    conversar(montar(llm), "Oi")

    assert llm.vistas[0][0].content.startswith("PROMPT NOVO DA AULA")


# --- reflexão sobre a memória ---------------------------------------------------------------------
def test_mudanca_de_perfil_exige_confirmacao_em_dois_turnos(montar, store, monkeypatch):
    memoria.salvar_perfil(store, "ana", {"tolerancia_risco": 1, "perfil_suitability": "conservador"})

    def langmem_falso(llm, st, user_id, texto):  # simula o LangMem entendendo "arrojado" na frase
        if "arrojado" in texto:
            memoria.salvar_perfil(st, user_id, {"tolerancia_risco": 5, "perfil_suitability": "arrojado"})

    monkeypatch.setattr(memoria, "atualizar_perfil", langmem_falso)
    llm = LLMFalso(respostas=[AIMessage("Certo."), AIMessage("Você quer mesmo mudar o perfil?"), AIMessage("Perfil atualizado.")])
    grafo = montar(llm)

    r1 = conversar(grafo, "Agora quero ser arrojado e arriscar tudo")
    assert memoria.ler_perfil(store, "ana")["perfil_suitability"] == "conservador"  # não mudou
    assert ("memorizar", "pendente") in passos(r1)

    conversar(grafo, "Que produto você sugere?")
    assert "mudança de perfil pendente" in llm.vistas[1][0].content  # o agente foi avisado e pergunta

    r3 = conversar(grafo, "Sim, confirmo a mudança")
    assert memoria.ler_perfil(store, "ana")["perfil_suitability"] == "arrojado"
    assert ("memorizar", "aplicar_pendente") in passos(r3)


# --- a trilha é por turno ---------------------------------------------------------------------------
def test_trilha_recomeca_a_cada_mensagem(montar, gravacoes):
    llm = LLMFalso(respostas=[AIMessage("Resposta 1."), AIMessage("Resposta 2.")])
    grafo = montar(llm)

    conversar(grafo, "Primeira pergunta sobre CDB")
    r2 = conversar(grafo, "Segunda pergunta sobre LCI")

    assert [t["no"] for t in r2["trilha_metacognitiva"]].count("planejar") == 1
