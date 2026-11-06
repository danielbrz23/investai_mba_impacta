"""Chunking do guia de investimentos, em duas etapas.

1. Estrutural: cada produto (`##`) é um bloco; dentro dele, cada seção (`###`) vira um chunk.
2. Tamanho: seções longas são cortadas em pedaços de CHUNK_TAMANHO caracteres, com sobreposição.

Cada chunk recebe um prefixo com produto e seção ("Produto: ... | Seção: ..."). Assim a busca
semântica sabe de quem o trecho fala, mesmo quando o pedaço não repete o nome do produto.
"""

import re
from dataclasses import dataclass

from langgraph.store.base import PutOp
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from investai_meta.config import CHUNK_SOBREPOSICAO, CHUNK_TAMANHO, NS_CARTOES, NS_CONHECIMENTO

PADRAO_META = re.compile(r"<!--\s*(id:.*?)-->", re.S)
PADRAO_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@dataclass
class Produto:
    id: str
    nome: str
    meta: dict
    corpo: str  # texto do produto, sem título e sem comentário de metadados


@dataclass
class Chunk:
    chave: str
    texto: str  # já com o prefixo "Produto | Seção": é o que vira embedding
    produto_id: str
    produto: str
    secao: str
    classe: str
    risco: int
    liquidez: str
    minimo: float
    fonte: str


def preencher_placeholders(markdown: str, valores: dict[str, str]) -> str:
    """Troca {selic}, {cdi} etc. pelos valores reais. Chave desconhecida vira 'indisponível'."""
    return PADRAO_PLACEHOLDER.sub(lambda m: valores.get(m.group(1), "indisponível"), markdown)


def _ler_meta(texto: str) -> dict:
    meta = {}
    for par in texto.split("|"):
        chave, _, valor = par.partition(":")
        meta[chave.strip()] = valor.strip()
    meta["risco"] = int(meta["risco"])
    meta["minimo"] = float(meta["minimo"])
    return meta


def ler_produtos(markdown: str) -> list[Produto]:
    """Separa o guia em produtos. Cada `##` precisa ter um comentário <!-- id: ... -->."""
    blocos = re.split(r"^## ", markdown, flags=re.M)[1:]  # [0] é o título geral do documento
    produtos = []
    for bloco in blocos:
        titulo, _, resto = bloco.partition("\n")
        casamento = PADRAO_META.search(resto)
        if not casamento:
            raise ValueError(f"Produto sem metadados: {titulo.strip()}")
        meta = _ler_meta(casamento.group(1))
        corpo = resto[: casamento.start()] + resto[casamento.end():]
        produtos.append(Produto(id=meta["id"], nome=titulo.strip(), meta=meta, corpo=corpo.strip()))
    return produtos


def dividir_produto(produto: Produto, fonte: str) -> list[Chunk]:
    """Etapa 1 (por seção ###) e etapa 2 (por tamanho). Seções sem título ficam como 'Resumo'."""
    divisor_estrutural = MarkdownHeaderTextSplitter(headers_to_split_on=[("###", "secao")], strip_headers=True)
    secoes = divisor_estrutural.split_text(produto.corpo)

    divisor_tamanho = RecursiveCharacterTextSplitter(chunk_size=CHUNK_TAMANHO, chunk_overlap=CHUNK_SOBREPOSICAO)
    partes = divisor_tamanho.split_documents(secoes)

    contagem: dict[str, int] = {}
    chunks = []
    for parte in partes:
        secao = parte.metadata.get("secao", "Resumo")
        n = contagem.get(secao, 0)
        contagem[secao] = n + 1
        chunks.append(
            Chunk(
                chave=f"{produto.id}:{secao}:{n}",
                texto=f"Produto: {produto.nome} | Seção: {secao}\n{parte.page_content}",
                produto_id=produto.id,
                produto=produto.nome,
                secao=secao,
                classe=produto.meta["classe"],
                risco=produto.meta["risco"],
                liquidez=produto.meta["liquidez"],
                minimo=produto.meta["minimo"],
                fonte=fonte,
            )
        )
    return chunks


def gerar_chunks(markdown: str, valores: dict[str, str] | None = None, fonte: str = "guia_investimentos.md") -> list[Chunk]:
    """Função principal: guia (texto) -> lista de chunks prontos para o store."""
    texto = preencher_placeholders(markdown, valores or {})
    chunks = []
    for produto in ler_produtos(texto):
        chunks.extend(dividir_produto(produto, fonte))
    return chunks


def resumo_produtos(markdown: str) -> list[dict]:
    """Um cartão por produto (sem texto longo). Serve para validar suitability e valor mínimo."""
    return [
        {"produto_id": p.id, "nome": p.nome, **{k: v for k, v in p.meta.items() if k != "id"}}
        for p in ler_produtos(markdown)
    ]


def montar_ops(chunks: list[Chunk], cartoes: list[dict], data_referencia: str = "") -> tuple[list[PutOp], list[PutOp]]:
    """Operações de gravação no store: (chunks com embedding, cartões sem embedding)."""
    ops_chunks = [
        PutOp(
            NS_CONHECIMENTO,
            c.chave,
            {
                "texto": c.texto, "produto_id": c.produto_id, "produto": c.produto, "secao": c.secao,
                "classe": c.classe, "risco": c.risco, "liquidez": c.liquidez, "minimo": c.minimo,
                "fonte": c.fonte, "data_referencia": data_referencia,
            },
        )
        for c in chunks
    ]
    ops_cartoes = [PutOp(NS_CARTOES, card["produto_id"], card, index=False) for card in cartoes]
    return ops_chunks, ops_cartoes
