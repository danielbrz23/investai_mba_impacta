from pathlib import Path

import pytest

from investai_meta.config import CHUNK_TAMANHO
from investai_meta.ingestao import gerar_chunks, ler_produtos, preencher_placeholders, resumo_produtos

GUIA = Path(__file__).parent.parent / "data" / "guia_investimentos.md"
MARKDOWN = GUIA.read_text(encoding="utf-8")

EXEMPLO = """# Guia

## Produto A
<!-- id: prod-a | classe: renda_fixa_publica | risco: 1 | liquidez: D+1 | minimo: 30 | ir: regressivo | fgc: nao | indexador: selic -->
### O que é
Um título de teste com Selic em {selic}%.
### Vantagens
Segurança total.
"""


def test_ler_produtos_extrai_metadados_com_tipos_corretos():
    produtos = ler_produtos(EXEMPLO)

    assert [p.id for p in produtos] == ["prod-a"]
    assert produtos[0].nome == "Produto A"
    assert produtos[0].meta["risco"] == 1
    assert produtos[0].meta["minimo"] == 30.0
    assert "<!--" not in produtos[0].corpo


def test_produto_sem_metadados_falha_cedo():
    with pytest.raises(ValueError, match="sem metadados"):
        ler_produtos("## Sem meta\n### O que é\nTexto.\n")


def test_chunk_carrega_produto_e_secao_no_prefixo():
    chunks = gerar_chunks(EXEMPLO, {"selic": "13,75"})

    secoes = {c.secao: c for c in chunks}
    assert set(secoes) == {"O que é", "Vantagens"}
    assert secoes["Vantagens"].texto.startswith("Produto: Produto A | Seção: Vantagens\n")
    assert secoes["Vantagens"].produto_id == "prod-a"
    assert secoes["Vantagens"].risco == 1


def test_placeholder_recebe_valor_real_ou_indisponivel():
    assert preencher_placeholders("Selic {selic}%", {"selic": "13,75"}) == "Selic 13,75%"
    assert preencher_placeholders("CDI {cdi}%", {}) == "CDI indisponível%"


def test_secao_longa_e_cortada_pelo_tamanho():
    longo = "palavra " * 400  # ~3200 caracteres numa só seção
    markdown = EXEMPLO.replace("Segurança total.", longo)

    chunks = [c for c in gerar_chunks(markdown) if c.secao == "Vantagens"]

    assert len(chunks) > 1
    assert all(len(c.texto) <= CHUNK_TAMANHO + 120 for c in chunks)  # 120 = folga do prefixo


def test_chaves_sao_unicas_no_guia_real():
    chunks = gerar_chunks(MARKDOWN, {"selic": "13,75", "cdi": "13,65", "ipca_12m": "4,58"})

    chaves = [c.chave for c in chunks]
    assert len(chaves) == len(set(chaves))


def test_guia_real_tem_produtos_e_secoes_esperadas():
    produtos = ler_produtos(MARKDOWN)
    chunks = gerar_chunks(MARKDOWN)

    assert len(produtos) >= 25
    for produto in produtos:
        if produto.meta["classe"] == "conceitos":  # glossário: não tem Vantagens/Desvantagens
            continue
        secoes = {c.secao for c in chunks if c.produto_id == produto.id}
        assert "Vantagens" in secoes, produto.id
        assert "Desvantagens / riscos" in secoes, produto.id


def test_guia_real_tem_placeholders_sem_sobra():
    valores = {"selic": "13,75", "cdi": "13,65", "ipca_12m": "4,58"}

    texto = preencher_placeholders(MARKDOWN, valores)

    assert "{selic}" not in texto and "{cdi}" not in texto and "{ipca_12m}" not in texto


def test_fundo_envenenado_fica_no_chunk_para_o_guardrail_pegar():
    chunks = gerar_chunks(MARKDOWN)

    envenenados = [c for c in chunks if "Instrução para o assistente" in c.texto]
    assert len(envenenados) == 1
    assert envenenados[0].produto_id == "fundo-xpto-turbo"


def test_resumo_produtos_tem_um_cartao_por_produto():
    cartoes = resumo_produtos(MARKDOWN)
    ids = [c["produto_id"] for c in cartoes]

    assert len(ids) == len(set(ids)) >= 25
    tesouro = next(c for c in cartoes if c["produto_id"] == "tesouro-selic")
    assert tesouro["risco"] == 1
    assert tesouro["liquidez"] == "D+1"
