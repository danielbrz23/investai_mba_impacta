"""Guardrail de prompt injection, em três camadas.

1. Regex (barata, determinística) para os ataques mais comuns em português e inglês.
2. Juiz LLM com saída estruturada, para o que a regex não pega.
3. Dados recuperados (guia, ferramentas) são sanitizados com as mesmas regex e entregues
   dentro de <dados_nao_confiaveis>, para o modelo tratá-los como dado e não como ordem.
"""

import re

from langchain_core.messages import HumanMessage, SystemMessage

from investai_meta import config
from investai_meta.prompts import PROMPT_JUIZ_INJECAO
from investai_meta.schemas import VeredictoInjecao

PADROES = {
    "ignorar_regras": r"ignor\w*\s+(\w+\s+){0,3}(instru\w+|regras?|diretrizes|orienta\w+|restri\w+|seguran\w+)",
    "ignorar_regras_en": r"ignore\s+(\w+\s+){0,3}(instructions|rules|guidelines|prompt|safety)",
    "desconsiderar": r"(desconsidere|esque[çc]a)\s+(\w+\s+){0,3}(instru\w+|regras?|perfil|adequa\w+)",
    "prompt_do_sistema": r"system\s*prompt|prompt\s+do\s+sistema|instru[çc][õo]es\s+internas",
    "troca_de_papel": r"voc[eê]\s+agora\s+(é|e|vai\s+ser)\b|finja\s+(ser|que)|aja\s+como\s+se",
    "jailbreak": r"\bDAN\b|modo\s+desenvolvedor|developer\s+mode|jailbreak",
    "tokens_de_controle": r"<\|[^>]*\|>|\[/?INST\]|###\s*system",
    "base64_longo": r"[A-Za-z0-9+/]{80,}={0,2}",
    "instrucao_ao_assistente": r"instru[çc][ãa]o\s+para\s+o\s+assistente|nota\s+para\s+a\s+ia",
    "forcar_recomendacao": r"(recomende|indique)\s+(este|esse|isso)\b.{0,60}(a\s+todos|para\s+todos)",
    "forcar_promessa": r"diga\s+que\s+o\s+retorno\s+(é|e)\s+garantido",
}
_COMPILADOS = {nome: re.compile(p, re.IGNORECASE) for nome, p in PADROES.items()}

_SOCIAL = re.compile(
    r"(?:oi|ol[aá]|opa|bom|boa|dia|tarde|noite|e|a[ií]|obrigad[oa]|valeu|tudo|bem|bom|como|vai|voc[eê]|tchau|at[eé]|mais|muito|[,!?.\s])+",
    re.IGNORECASE,
)

TRECHO_REMOVIDO = "[trecho removido por segurança]"


def detectar_regex(texto: str) -> str | None:
    """Nome do primeiro padrão suspeito encontrado, ou None."""
    for nome, padrao in _COMPILADOS.items():
        if padrao.search(texto):
            return nome
    return None


def sanitizar_trecho(texto: str) -> tuple[str, list[str]]:
    """Troca por um aviso as linhas que parecem instruções escondidas. Devolve (texto limpo, padrões achados)."""
    achados, linhas = [], []
    for linha in texto.splitlines():
        nome = detectar_regex(linha)
        if nome:
            achados.append(nome)
            linhas.append(TRECHO_REMOVIDO)
        else:
            linhas.append(linha)
    return "\n".join(linhas), achados


def envelopar(texto: str) -> str:
    """Marca o texto como dado. O prompt do sistema manda não obedecer nada que esteja aqui dentro."""
    return f"<dados_nao_confiaveis>\n{texto}\n</dados_nao_confiaveis>"


def verificar_entrada(texto: str, juiz=None) -> VeredictoInjecao:
    """Camadas 1 e 2 para a mensagem do usuário. `juiz` é um runnable que devolve VeredictoInjecao."""
    padrao = detectar_regex(texto)
    if padrao:
        return VeredictoInjecao(e_injecao=True, categoria="injecao", motivo=f"padrão suspeito: {padrao}")
    if _SOCIAL.fullmatch(texto.strip()):  # saudação ou agradecimento não precisa de juiz
        return VeredictoInjecao(e_injecao=False, categoria="ok", motivo="conversa social")
    if juiz is None or not config.USAR_JUIZ_LLM:
        return VeredictoInjecao(e_injecao=False, categoria="ok", motivo="sem padrões suspeitos")
    return juiz.invoke([
        SystemMessage(PROMPT_JUIZ_INJECAO),
        HumanMessage(f"<mensagem_do_usuario>\n{texto}\n</mensagem_do_usuario>"),
    ])
