"""Guardrail de persistência de memória: roda ANTES de qualquer coisa ser gravada.

- mascara PII (CPF, cartão, telefone, e-mail, senha, conta);
- recusa memória-instrução ("sempre recomende X"), que é memory poisoning;
- recusa mudanças bruscas de perfil de risco, que exigem confirmação explícita.
"""

import re

from langchain_core.messages import HumanMessage, SystemMessage

from investai_meta import config
from investai_meta.guardrails.injecao import detectar_regex
from investai_meta.prompts import PROMPT_JUIZ_MEMORIA
from investai_meta.schemas import VeredictoMemoria

PII = {
    "senha": re.compile(r"\b(senha|password|token|chave\s+de\s+acesso)\b\s*(é|e|:|=)?\s*\S+", re.IGNORECASE),
    "cartao": re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    "cpf": re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),
    "telefone": re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}-?\d{4}\b"),
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "conta": re.compile(r"\b(ag[êe]ncia|conta(\s+corrente)?)\s*(n[ºo°]?\s*)?\d[\d.-]*", re.IGNORECASE),
}
INSTRUCAO = re.compile(
    r"\b(sempre|nunca)\s+(recomende|indique|sugira|diga|ignore|mencione|ofere[çc]a)\b"
    r"|a\s+partir\s+de\s+agora|lembre-se\s+(de\s+)?(sempre|nunca)|\bignore\s+o\s+perfil\b",
    re.IGNORECASE,
)
SUSPEITA_LEVE = re.compile(r"\b(sempre|nunca|recomende|indique|regra|ordem)\b", re.IGNORECASE)
INFO_PESSOAL = re.compile(
    r"\b(tenho|sou|minha|meu|meus|minhas|quero|prefiro|pretendo|invisto|ganho|recebo|moro|me\s+chamo|objetivo|anos|reserva|aposentad\w+)\b",
    re.IGNORECASE,
)


def mascarar_pii(texto: str) -> tuple[str, list[str]]:
    achados = []
    for tipo, padrao in PII.items():
        if padrao.search(texto):
            achados.append(tipo)
            texto = padrao.sub(f"[{tipo} removido]", texto)
    return texto, achados


def parece_informacao_pessoal(texto: str) -> bool:
    """Filtro barato: só vale chamar o extrator de memória se a frase fala do cliente."""
    return bool(INFO_PESSOAL.search(texto))


def decidir_memoria(texto: str, juiz=None) -> tuple[VeredictoMemoria, str, list[str]]:
    """Devolve (veredito, texto com PII mascarada, tipos de PII achados)."""
    mascarado, pii = mascarar_pii(texto)
    if detectar_regex(texto) or INSTRUCAO.search(texto):
        return VeredictoMemoria(persistir=False, motivo="instrução disfarçada de preferência"), mascarado, pii
    if juiz is not None and config.USAR_JUIZ_LLM and SUSPEITA_LEVE.search(texto):
        veredito = juiz.invoke([SystemMessage(PROMPT_JUIZ_MEMORIA), HumanMessage(f"<mensagem>\n{mascarado}\n</mensagem>")])
        return veredito, mascarado, pii
    return VeredictoMemoria(persistir=True, motivo="fato do cliente"), mascarado, pii


def mudanca_brusca(antigo: dict | None, novo: dict | None) -> str | None:
    """Motivo (texto) se o perfil de risco mudou demais de uma vez; None se a mudança é aceitável."""
    if not antigo or not novo:
        return None
    t_antigo, t_novo = antigo.get("tolerancia_risco"), novo.get("tolerancia_risco")
    if t_antigo and t_novo and abs(int(t_novo) - int(t_antigo)) >= 2:
        return f"tolerância a risco foi de {t_antigo} para {t_novo}"
    s_antigo, s_novo = antigo.get("perfil_suitability"), novo.get("perfil_suitability")
    if {s_antigo, s_novo} == {"conservador", "arrojado"}:
        return f"perfil foi de {s_antigo} para {s_novo}"
    return None
