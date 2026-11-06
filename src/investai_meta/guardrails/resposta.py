"""Guardrail de resposta: confere o texto do assessor antes de ele chegar ao cliente.

As checagens determinísticas rodam sempre. O juiz LLM é opcional (config.USAR_JUIZ_LLM) e olha
o que regra nenhuma enxerga, como número que contradiz as evidências das ferramentas.
"""

import re

from langchain_core.messages import HumanMessage, SystemMessage

from investai_meta import config
from investai_meta.guardrails.injecao import detectar_regex
from investai_meta.prompts import DISCLAIMER, PROMPT_JUIZ_RESPOSTA
from investai_meta.schemas import VeredictoResposta

# O modelo às vezes escreve o próprio aviso legal; reconhecemos as variantes para não duplicar.
TEM_AVISO = re.compile(r"n[ãa]o\s+(?:é|e|constitui)\s+(?:uma\s+)?recomenda|aviso\s+legal", re.IGNORECASE)
_ALVO = r"(?:retorno|rentabilidade|rendimento|lucro|ganho)s?"
_PALAVRA = r"[^\s.,;:!?()]+\s+"  # uma palavra sem pontuação: o padrão não atravessa vírgula nem parêntese
PROMESSAS = re.compile(
    rf"\b{_ALVO}\s+(?:{_PALAVRA}){{0,6}}garantid\w+"   # "retorno garantido", "rentabilidade de 20% ao ano é garantida"
    rf"|\bgarantid\w+\s+(?:{_PALAVRA}){{0,2}}{_ALVO}"   # "garantido o retorno"
    r"|\bgarantimos\b|\bsem\s+risco\b|\brisco\s+zero\b|\bn[ãa]o\s+tem\s+risco\b"
    r"|\bretorno\s+certo\b|\blucro\s+certo\b|\bvai\s+subir\b|\b(?:100%|totalmente)\s+seguro\b",
    re.IGNORECASE,
)
# Contextos em que a palavra é legítima: negação, FGC, "sem garantia"...
CONTEXTO_LEGITIMO = re.compile(
    r"\b(n[ãa]o|nunca|nem|nenhum\w*|evite|FGC|sem\s+garantia|cobertur\w+|governo|Tesouro\s+Nacional)\b", re.IGNORECASE
)
NEGACAO_SUITABILITY = re.compile(
    r"\b(n[ãa]o|evite|evitar|nunca|fora\s+d[oe]|acima\s+d[oe]|incompat\w+|inadequad\w+)\b", re.IGNORECASE
)


def _sentencas(texto: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", texto) if s.strip()]


def checar_promessas(texto: str) -> list[str]:
    violacoes = []
    for sentenca in _sentencas(texto):
        achado = PROMESSAS.search(sentenca)
        if achado and not CONTEXTO_LEGITIMO.search(sentenca):
            violacoes.append(f"promessa de retorno: '{achado.group(0)}'")
    return violacoes


def aliases(nome: str) -> set[str]:
    """Formas curtas pelas quais o texto costuma citar um produto: 'LCI', 'BOVA11', 'CRI', 'CRA'."""
    base = nome.split(" (")[0]
    nomes = {base}
    if base.startswith("ETF "):
        nomes.add(base[4:])
    if " e " in base:
        partes = base.split(" e ")
        if all(p.isupper() and len(p) <= 4 for p in partes):
            nomes.update(partes)
    return nomes


def produtos_citados(texto: str, cartoes: list[dict]) -> list[dict]:
    citados = []
    for cartao in cartoes:
        for alias in aliases(cartao["nome"]):
            if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", texto, re.IGNORECASE):
                citados.append(cartao)
                break
    return citados


def risco_maximo(perfil: dict | None) -> int | None:
    """Risco (1-5) que o perfil suporta, ou None se o perfil ainda não diz nada."""
    if not perfil:
        return None
    if perfil.get("tolerancia_risco"):
        return int(perfil["tolerancia_risco"])
    return config.RISCO_MAXIMO_POR_PERFIL.get(perfil.get("perfil_suitability") or "")


def checar_suitability(texto: str, perfil: dict | None, cartoes: list[dict]) -> list[str]:
    maximo = risco_maximo(perfil)
    if maximo is None:
        return []
    violacoes = []
    for sentenca in _sentencas(texto):
        for cartao in produtos_citados(sentenca, cartoes):
            if cartao["risco"] > maximo and not NEGACAO_SUITABILITY.search(sentenca):
                violacoes.append(f"suitability: {cartao['nome']} (risco {cartao['risco']}) acima do perfil (máx. {maximo})")
    return list(dict.fromkeys(violacoes))


def checar_contaminacao(texto: str) -> list[str]:
    """A resposta repete instruções de ataque? Sinal de que uma injeção indireta passou."""
    padrao = detectar_regex(texto)
    return [f"saída contaminada: {padrao}"] if padrao else []


def garantir_disclaimer(texto: str, cartoes: list[dict]) -> str:
    """Se a resposta cita produtos e esqueceu o aviso legal, o guardrail acrescenta."""
    if produtos_citados(texto, cartoes) and not TEM_AVISO.search(texto):
        return f"{texto.rstrip()}\n\n{DISCLAIMER}"
    return texto


def validar_resposta(texto: str, perfil: dict | None, cartoes: list[dict]) -> list[str]:
    return checar_promessas(texto) + checar_suitability(texto, perfil, cartoes) + checar_contaminacao(texto)


def julgar_resposta(texto: str, perfil: dict | None, evidencias: str, juiz) -> list[str]:
    """Juiz LLM. `evidencias` são as saídas recentes das ferramentas, para ele conferir os números."""
    if juiz is None or not config.USAR_JUIZ_LLM:
        return []
    veredito: VeredictoResposta = juiz.invoke([
        SystemMessage(PROMPT_JUIZ_RESPOSTA),
        HumanMessage(
            f"<perfil>{perfil or 'não informado'}</perfil>\n<evidencias>{evidencias[:4000] or 'nenhuma'}</evidencias>\n"
            f"<resposta>\n{texto}\n</resposta>"
        ),
    ])
    return [] if veredito.aprovada else (veredito.violacoes or ["reprovada pelo juiz"])
