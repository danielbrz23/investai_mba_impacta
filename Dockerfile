# Hugging Face Spaces (Docker). O Space expõe a porta 7860.
FROM python:3.12-slim

RUN useradd -m -u 1000 usuario
USER usuario
ENV PATH="/home/usuario/.local/bin:$PATH" \
    PYTHONUNBUFFERED=1
WORKDIR /home/usuario/app

COPY --chown=usuario requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=usuario pyproject.toml .
COPY --chown=usuario src ./src
COPY --chown=usuario app ./app
COPY --chown=usuario data ./data
COPY --chown=usuario scripts ./scripts
RUN pip install --no-cache-dir --no-deps -e .

# O servidor sobe na hora. Na primeira vez o guia é ingerido em segundo plano (cerca de 5 minutos, por causa do
# limite de embeddings do plano gratuito do Gemini); até lá a busca no guia volta vazia. Precisa de GEMINI_API_KEY
# nos Secrets do Space. O disco do container é apagado a cada rebuild: ative o Persistent Storage para manter dados.
CMD ["sh", "-c", "python scripts/init_db.py && (python scripts/ingerir_conhecimento.py --se-vazio &) && uvicorn app.api:app --host 0.0.0.0 --port 7860"]
