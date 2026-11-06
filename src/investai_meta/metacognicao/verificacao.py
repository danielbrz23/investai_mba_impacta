"""Autoverificação dos números (chain-of-verification), sem LLM.

Extrai da resposta os valores em % e em R$ e confere se cada um aparece nas fontes: saídas das ferramentas,
mensagens do cliente, perfil e trechos do guia. Número sem fonte é o sinal clássico de alucinação.
"""

import re

# Constantes do guia que o assistente pode citar mesmo sem tê-las buscado (IR regressivo, FGC, PGBL...).
CONSTANTES_CONHECIDAS = {250000.0, 22.5, 20.0, 17.5, 15.0, 12.0, 100.0, 8.5, 0.5}
MULTIPLICADOR = {"mil": 1_000.0, "milhão": 1_000_000.0, "milhões": 1_000_000.0}

_NUM = r"\d[\d.]*(?:,\d+)?"
RE_REAIS = re.compile(rf"R\$\s*({_NUM})(?:\s*(mil|milhões|milhão))?", re.IGNORECASE)
RE_PERCENTUAL = re.compile(rf"({_NUM})\s*%")
RE_QUALQUER = re.compile(r"\d+(?:[.,]\d+)*")
RE_MILHAR = re.compile(r"^\d{1,3}(\.\d{3})+$")


def para_numero(texto: str) -> float:
    """'13,75' -> 13.75 · '11.100,00' -> 11100.0 · '10.960' -> 10960.0 · '13.75' -> 13.75"""
    texto = texto.strip(".")
    if "," in texto:
        return float(texto.replace(".", "").replace(",", "."))
    if RE_MILHAR.match(texto):
        return float(texto.replace(".", ""))
    return float(texto)


def extrair_citados(resposta: str) -> list[tuple[str, float]]:
    """(trecho, valor) dos valores em R$ e em % que a resposta cita."""
    achados = []
    for m in RE_REAIS.finditer(resposta):
        valor = para_numero(m.group(1)) * MULTIPLICADOR.get((m.group(2) or "").lower(), 1.0)
        achados.append((m.group(0).strip(), valor))
    for m in RE_PERCENTUAL.finditer(resposta):
        achados.append((m.group(0).strip(), para_numero(m.group(1))))
    return achados


def numeros_das_fontes(fontes: list[str]) -> list[float]:
    valores = []
    for fonte in fontes:
        for token in RE_QUALQUER.findall(fonte):
            try:
                valores.append(para_numero(token))
            except ValueError:
                continue
    return valores


def _proximo(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.011, 0.01 * abs(b))  # 1% de tolerância: "cerca de R$ 11 mil" para 11.100


def verificar(resposta: str, fontes: list[str], maximo: int = 3) -> list[str]:
    """Violações `numero_nao_verificado` para cada valor citado que nenhuma fonte sustenta."""
    das_fontes = numeros_das_fontes(fontes)
    orfaos = []
    for trecho, valor in extrair_citados(resposta):
        e_constante = any(abs(valor - c) <= 0.011 for c in CONSTANTES_CONHECIDAS)  # constantes: valor exato, sem tolerância
        if not e_constante and not any(_proximo(valor, c) for c in das_fontes):
            orfaos.append(f"número não verificado: {trecho}")
    return list(dict.fromkeys(orfaos))[:maximo]
