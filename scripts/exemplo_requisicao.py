"""Uma requisição de exemplo à API: POST /chat.

Suba a API antes:  API_KEY=minha-chave uvicorn app.api:app --port 7860
Depois rode:       python scripts/exemplo_requisicao.py
"""

import requests

resposta = requests.post(
    "http://localhost:7860/chat",
    headers={"X-API-Key": "minha-chave"},
    json={
        "user_id": "ana",
        "thread_id": "ana-001",
        "mensagem": "Tenho 35 anos e quero montar uma reserva de emergência.",
    },
    timeout=120,
)

print(resposta.status_code)
print(resposta.json())
