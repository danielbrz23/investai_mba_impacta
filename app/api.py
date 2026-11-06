"""API HTTP do assessor. Rodar: uvicorn app.api:app --port 7860   (docs em /docs, interface em /ui)"""

import hmac
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field

from investai_meta import servico
from investai_meta.llm import carregar_env

logger = logging.getLogger("investai_meta.api")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ChatIn(BaseModel):
    user_id: str = Field(pattern=servico.PADRAO_USER_ID, examples=["ana"], description="Identifica o cliente (vem do login)")
    thread_id: str = Field(min_length=1, max_length=64, examples=["ana-001"], description="Identifica a conversa")
    mensagem: str = Field(min_length=1, max_length=2000, examples=["Tenho 35 anos e quero montar uma reserva de emergência."])


class ResumeIn(BaseModel):
    user_id: str = Field(pattern=servico.PADRAO_USER_ID, examples=["ana"])
    thread_id: str = Field(min_length=1, max_length=64, examples=["ana-001"])
    aprovado: bool = Field(description="true grava a ordem; false cancela")


class FeedbackIn(BaseModel):
    user_id: str = Field(pattern=servico.PADRAO_USER_ID, examples=["ana"])
    thread_id: str = Field(min_length=1, max_length=64, examples=["ana-001"])
    nota: int = Field(description="1 = 👍, -1 = 👎 (o 👎 vira uma lição para o agente)", examples=[-1])
    comentario: str | None = Field(None, max_length=500, examples=["Citou uma taxa que não vi em lugar nenhum"])


class ChatOut(BaseModel):
    resposta: str
    ordem_pendente: dict | None = Field(None, description="Proposta aguardando confirmação (chame /chat/resume)")
    bloqueado: bool = Field(description="true se um guardrail recusou a mensagem")
    metacognicao: dict | None = Field(
        None, description="Como o agente pensou: plano, confiança, lacunas, lições usadas, reescritas e trilha de decisões"
    )


def criar_app(backend_factory=servico.backend_padrao, api_key: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        carregar_env()
        app.state.backend = backend_factory()
        app.state.api_key = api_key if api_key is not None else os.getenv("API_KEY")
        if not app.state.api_key:
            logger.warning("API_KEY não definida: a API está ABERTA. Defina API_KEY antes de expor na internet.")
        yield

    app = FastAPI(title="InvestAI", version="1.0", lifespan=ciclo_de_vida)

    def exigir_chave(x_api_key: str | None = Header(None)):
        esperada = app.state.api_key
        if esperada and not hmac.compare_digest(x_api_key or "", esperada):
            raise HTTPException(401, "X-API-Key ausente ou inválida.")

    def backend() -> servico.Backend:
        return app.state.backend

    def executar(funcao, *args):
        try:
            return funcao(backend(), *args)
        except ValueError as erro:
            raise HTTPException(422, str(erro))
        except LookupError as erro:
            raise HTTPException(409, str(erro))
        except Exception:
            logger.exception("falha ao atender a requisição")
            raise HTTPException(503, "Serviço temporariamente indisponível. Tente novamente em instantes.")

    @app.get("/health")
    def health():
        return {"status": "ok", "auth": bool(app.state.api_key)}

    @app.post("/chat", response_model=ChatOut, dependencies=[Depends(exigir_chave)])
    def chat(corpo: ChatIn):
        return executar(servico.conversar, corpo.user_id, corpo.thread_id, corpo.mensagem)

    @app.post("/chat/resume", response_model=ChatOut, dependencies=[Depends(exigir_chave)])
    def chat_resume(corpo: ResumeIn):
        return executar(servico.retomar, corpo.user_id, corpo.thread_id, corpo.aprovado)

    @app.post("/feedback", dependencies=[Depends(exigir_chave)])
    def feedback(corpo: FeedbackIn):
        if corpo.nota not in (-1, 1):
            raise HTTPException(422, "nota deve ser 1 ou -1.")
        return executar(servico.registrar_feedback, corpo.user_id, corpo.thread_id, corpo.nota, corpo.comentario)

    @app.get("/licoes", dependencies=[Depends(exigir_chave)])
    def licoes():
        return executar(servico.listar_licoes)

    @app.get("/ordens", dependencies=[Depends(exigir_chave)])
    def ordens(user_id: str | None = Query(None, pattern=servico.PADRAO_USER_ID)):
        return executar(servico.listar_ordens, user_id)

    @app.get("/ordens.xlsx", dependencies=[Depends(exigir_chave)])
    def ordens_xlsx(user_id: str | None = Query(None, pattern=servico.PADRAO_USER_ID)):
        conteudo = executar(servico.ordens_em_excel, user_id)
        return Response(conteudo, media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="ordens.xlsx"'})

    @app.get("/memoria/{user_id}", dependencies=[Depends(exigir_chave)])
    def memoria_do_usuario(user_id: str):
        return executar(servico.ver_memoria, user_id)

    @app.get("/", include_in_schema=False)
    def raiz():
        return RedirectResponse("/ui")

    from app.ui import montar_ui  # a interface fica por último: ela chama o backend direto, sem passar pela rede

    return montar_ui(app, lambda: app.state.backend)


app = criar_app()
