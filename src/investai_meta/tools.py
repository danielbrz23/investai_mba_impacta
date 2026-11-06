"""Ferramentas do agente. Cada docstring é lida pelo LLM: ela diz quando e como usar a ferramenta.

O user_id nunca é argumento: vem do contexto da execução (login), então o LLM não consegue
consultar nem gravar dados de outro cliente.
"""

import json
from typing import Literal

from langchain.tools import ToolRuntime, tool
from langgraph.types import interrupt

from investai_meta import config, db, memoria
from investai_meta.dados_mercado import ClienteMercado, MercadoIndisponivel
from investai_meta.guardrails.injecao import envelopar
from investai_meta.guardrails.resposta import risco_maximo


class Servicos:
    """Conexão SQLite e cliente das APIs públicas, criados na primeira chamada."""

    def __init__(self, conn=None, cliente=None):
        self.conn = conn or db.conectar()
        self.cliente = cliente or ClienteMercado(persistencia=db.CacheSQLite(self.conn))


_servicos: Servicos | None = None


def servicos() -> Servicos:
    global _servicos
    if _servicos is None:
        _servicos = Servicos()
    return _servicos


def definir_servicos(conn=None, cliente=None) -> None:
    """A API e os testes injetam a própria conexão e um cliente falso."""
    global _servicos
    _servicos = Servicos(conn, cliente)


def _json(dado) -> str:
    return json.dumps(dado, ensure_ascii=False)


@tool
def buscar_conhecimento(consulta: str, runtime: ToolRuntime, risco_max: int | None = None, classe: str | None = None) -> str:
    """Busca no guia de investimentos da InvestAI (o que é, como rende, vantagens, riscos, para quem serve, tributação).
    Use sempre que precisar explicar ou comparar produtos. `consulta` é uma frase em português.
    `risco_max` (1 a 5) filtra produtos mais arriscados que o perfil do cliente. `classe` é opcional
    (ex.: renda_fixa_publica, renda_fixa_privada, fundo_renda_fixa, renda_variavel)."""
    if runtime.store is None:
        return "Base de conhecimento indisponível."
    trechos = memoria.buscar_trechos(runtime.store, consulta, limite=6, risco_max=risco_max, classe=classe)
    if not trechos:
        return "Nenhum trecho encontrado para essa consulta."
    return envelopar("\n\n".join(t["texto"] for t in trechos))


@tool
def consultar_indicadores() -> str:
    """Indicadores econômicos atuais do Brasil: Selic meta, CDI, IPCA (12 meses e mensal), dólar e rendimento da
    poupança (Banco Central), mais a projeção de Selic e IPCA do boletim Focus. Use antes de citar qualquer
    taxa ou inflação. Cada valor vem com a data de referência; `desatualizado=true` indica que a fonte estava fora do ar."""
    cliente = servicos().cliente
    resultado: dict = {}
    try:
        resultado["bcb"] = cliente.indicadores()
    except MercadoIndisponivel:
        resultado["bcb"] = "indisponível"
    for indicador in ("Selic", "IPCA"):
        try:
            resultado[f"focus_{indicador.lower()}"] = cliente.expectativa_focus(indicador)
        except MercadoIndisponivel:
            resultado[f"focus_{indicador.lower()}"] = "indisponível"
    return _json(resultado)


@tool
def consultar_tesouro(tipo: str | None = None) -> str:
    """Taxas e preços de hoje dos títulos do Tesouro Direto (taxa de compra em % ao ano e preço unitário por
    vencimento). `tipo` filtra pelo nome, ex.: 'Selic', 'IPCA+', 'Prefixado', 'Renda+'. Sem filtro, devolve um resumo."""
    try:
        dados = servicos().cliente.titulos_tesouro()
    except MercadoIndisponivel:
        return "Dados do Tesouro indisponíveis no momento."
    titulos = dados["titulos"]
    if tipo:
        titulos = [t for t in titulos if tipo.lower() in t["tipo"].lower()]
    return _json({"data_base": dados["data_base"], "desatualizado": dados["desatualizado"], "titulos": titulos[:12]})


@tool
def cotacao_b3(ticker: str) -> str:
    """Cotação atual de um ativo da B3 (ações, FIIs e ETFs como BOVA11, IVVB11, HASH11, PETR4, VALE3, ITUB4,
    MXRF11, HGLG11). Tickers fora dessa lista são recusados."""
    ticker = ticker.upper().strip()
    if ticker not in config.TICKERS_PERMITIDOS:
        return f"Ticker {ticker} fora da lista permitida: {', '.join(sorted(config.TICKERS_PERMITIDOS))}."
    try:
        return _json(servicos().cliente.cotacao_b3(ticker))
    except MercadoIndisponivel:
        return f"Cotação de {ticker} indisponível no momento."


def _aliquota_ir(dias: int) -> float:
    if dias <= 180:
        return 0.225
    if dias <= 360:
        return 0.20
    if dias <= 720:
        return 0.175
    return 0.15


@tool
def simular_rendimento(valor: float, taxa_anual: float, meses: int, isento_ir: bool = False) -> str:
    """Simula quanto rende um valor (R$) aplicado a uma taxa anual (% ao ano) por um número de meses, com juros
    compostos e imposto de renda regressivo (22,5% até 180 dias, 20% até 360, 17,5% até 720, 15% acima).
    Use `isento_ir=true` para LCI, LCA, CRI, CRA, debêntures incentivadas e poupança. Sempre use esta
    ferramenta para contas: não calcule de cabeça."""
    if valor <= 0 or meses <= 0 or taxa_anual < 0:
        return "Parâmetros inválidos: valor e meses devem ser positivos e a taxa não pode ser negativa."
    bruto = valor * (1 + taxa_anual / 100) ** (meses / 12)
    rendimento = bruto - valor
    aliquota = 0.0 if isento_ir else _aliquota_ir(meses * 30)
    imposto = rendimento * aliquota
    return _json({
        "valor_inicial": round(valor, 2), "meses": meses, "taxa_anual_pct": taxa_anual,
        "rendimento_bruto": round(rendimento, 2), "aliquota_ir_pct": round(aliquota * 100, 1),
        "imposto": round(imposto, 2), "valor_liquido_final": round(valor + rendimento - imposto, 2),
        "obs": "Simulação com taxa constante; não considera mudanças futuras de juros.",
    })


@tool
def ver_perfil(runtime: ToolRuntime) -> str:
    """Perfil de investidor do cliente que está conversando (objetivo, prazo, tolerância a risco...), se já
    foi informado. Consulte antes de recomendar produtos."""
    perfil = memoria.ler_perfil(runtime.store, runtime.context.user_id)
    return _json(perfil) if perfil else "Perfil ainda não informado."


@tool
def ver_carteira(runtime: ToolRuntime) -> str:
    """Posição atual do cliente (valor aplicado por produto, em R$) e as últimas ordens registradas."""
    conn, user_id = servicos().conn, runtime.context.user_id
    return _json({"posicoes": db.posicoes(conn, user_id), "ultimas_ordens": db.listar_ordens(conn, user_id)[-5:]})


@tool
def registrar_ordem(produto_id: str, tipo: Literal["compra", "venda"], valor: float, runtime: ToolRuntime) -> str:
    """Propõe uma ordem de compra ou venda e pede a confirmação do cliente; só grava depois que ele aprova.
    Use APENAS quando o cliente pedir a ordem de forma explícita, uma por vez. `produto_id` é o identificador do
    produto no guia (ex.: tesouro-selic, lci, bova11); `valor` é em reais."""
    user_id, store = runtime.context.user_id, runtime.store
    cartao = store.get(config.NS_CARTOES, produto_id) if store else None
    if cartao is None:
        return f"Produto '{produto_id}' não existe no catálogo. Use buscar_conhecimento para achar o identificador correto."
    produto = cartao.value
    if valor <= 0:
        return "O valor da ordem deve ser positivo."
    if tipo == "compra" and valor < produto["minimo"]:
        return f"Valor abaixo do mínimo de R$ {produto['minimo']:.2f} para {produto['nome']}."
    maximo = risco_maximo(memoria.ler_perfil(store, user_id))
    if tipo == "compra" and produto["risco"] > (maximo if maximo is not None else 2):
        return (
            f"{produto['nome']} (risco {produto['risco']}) não é compatível com o perfil do cliente"
            + ("." if maximo is not None else ", que ainda não foi informado. Pergunte o perfil antes.")
        )
    if tipo == "venda" and valor > db.posicoes(servicos().conn, user_id).get(produto_id, 0.0):
        return "O cliente não tem posição suficiente neste produto para vender esse valor."

    # A execução PARA aqui até o cliente responder. Ao retomar, a função roda de novo do início:
    # por isso tudo acima só valida e não grava nada.
    decisao = interrupt({
        "tipo": "confirmar_ordem", "produto_id": produto_id, "produto": produto["nome"],
        "ordem": tipo, "valor": valor, "risco": produto["risco"],
    })
    aprovado = bool(decisao.get("aprovado")) if isinstance(decisao, dict) else bool(decisao)
    db.inserir_ordem(
        servicos().conn, user_id, produto_id, tipo, valor,
        status="aprovada" if aprovado else "rejeitada",
        thread_id=(runtime.config.get("configurable") or {}).get("thread_id"),
    )
    return (
        f"Ordem de {tipo} de R$ {valor:.2f} em {produto['nome']} registrada."
        if aprovado else "Ordem cancelada pelo cliente. Nada foi registrado como execução."
    )


FERRAMENTAS = [
    buscar_conhecimento, consultar_indicadores, consultar_tesouro, cotacao_b3,
    simular_rendimento, ver_perfil, ver_carteira, registrar_ordem,
]
