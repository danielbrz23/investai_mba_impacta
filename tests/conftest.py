"""Fixtures compartilhadas: LLM falso, embeddings falsos e um store com o guia real."""

import re
import shutil
import zlib
from pathlib import Path

import pytest
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import Field

from investai_meta import db
from investai_meta.ingestao import gerar_chunks, montar_ops, resumo_produtos
from investai_meta.schemas import (
    Autoavaliacao, Licao, Plano, Reescrita, Replano, VeredictoInjecao, VeredictoMemoria, VeredictoResposta,
)

GUIA = Path(__file__).parent.parent / "data" / "guia_investimentos.md"
DIMS = 1024


class EmbeddingsFalsos(Embeddings):
    """Saco de palavras com hash: duas frases com palavras em comum ficam próximas. Sem rede."""

    def _vetor(self, texto: str) -> list[float]:
        v = [0.0] * DIMS
        for palavra in re.findall(r"\w+", texto.lower()):
            v[zlib.crc32(palavra.encode()) % DIMS] += 1.0
        norma = sum(x * x for x in v) ** 0.5 or 1.0
        return [x / norma for x in v]

    def embed_documents(self, textos):
        return [self._vetor(t) for t in textos]

    def embed_query(self, texto):
        return self._vetor(texto)


class LLMFalso(BaseChatModel):
    """Chat model roteirizado: `respostas` são devolvidas na ordem; juízes devolvem 'tudo ok' por padrão."""

    respostas: list = Field(default_factory=list)
    veredictos: dict = Field(default_factory=dict)  # nome do schema -> veredito (ou função)
    vistas: list = Field(default_factory=list)      # listas de mensagens recebidas, para inspeção

    @property
    def _llm_type(self) -> str:
        return "falso"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.vistas.append(messages)
        if not self.respostas:
            raise AssertionError("o agente chamou o LLM mais vezes do que o roteiro previa")
        return ChatResult(generations=[ChatGeneration(message=self.respostas.pop(0))])

    def bind_tools(self, tools, **kwargs):
        return self

    def with_structured_output(self, schema, **kwargs):
        padrao = {
            "VeredictoInjecao": VeredictoInjecao(e_injecao=False, categoria="ok", motivo="ok"),
            "VeredictoResposta": VeredictoResposta(aprovada=True),
            "VeredictoMemoria": VeredictoMemoria(persistir=True, motivo="ok"),
            "Plano": Plano(pede_recomendacao=False, passos=["responder ao cliente"]),
            "Replano": Replano(novos_passos=["tentar outra consulta"], desistir=False),
            "Autoavaliacao": Autoavaliacao(confianca=0.9, lacunas=[], justificativa="ok"),
            "Reescrita": Reescrita(critica="faltou cuidado", texto="Resposta corrigida sobre o Tesouro Selic."),
            "Licao": Licao(situacao="pedido de recomendação", erro="resposta reprovada", regra_aprendida="Confirme os números nas ferramentas antes de citar."),
        }

        def responder(entrada):
            veredito = self.veredictos.get(schema.__name__, padrao[schema.__name__])
            return veredito(entrada) if callable(veredito) else veredito

        return RunnableLambda(responder)


def chamada(nome: str, **args) -> AIMessage:
    """Mensagem do 'modelo' pedindo uma ferramenta."""
    return AIMessage(content="", tool_calls=[{"name": nome, "args": args, "id": f"call_{nome}"}])


@pytest.fixture(scope="session")
def banco_modelo(tmp_path_factory):
    """Banco com o guia já ingerido, criado UMA vez por sessão; cada teste trabalha numa cópia."""
    caminho = tmp_path_factory.mktemp("modelo") / "modelo.db"
    conexao = db.conectar(caminho)
    store = db.abrir_store(caminho, EmbeddingsFalsos(), dims=DIMS)
    markdown = GUIA.read_text(encoding="utf-8")
    ops, ops_cartoes = montar_ops(
        gerar_chunks(markdown, {"selic": "13,75", "cdi": "13,65", "ipca_12m": "4,58"}), resumo_produtos(markdown)
    )
    store.batch(ops + ops_cartoes)
    conexao.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conexao.close()
    return caminho


@pytest.fixture
def caminho_db(banco_modelo, tmp_path):
    copia = tmp_path / "teste.db"
    shutil.copy(banco_modelo, copia)
    return copia


@pytest.fixture
def conn(caminho_db):
    return db.conectar(caminho_db)


@pytest.fixture
def store(caminho_db):
    return db.abrir_store(caminho_db, EmbeddingsFalsos(), dims=DIMS)


@pytest.fixture
def cartoes():
    return resumo_produtos(GUIA.read_text(encoding="utf-8"))
