"""Exemplo de cliente da API (com metacognição): chat -> como o agente pensou -> ordem -> confirmação -> feedback -> planilha.

Uso:  python scripts/testar_endpoint.py --url http://localhost:7860 --api-key SUA_CHAVE
      (ou defina API_KEY no ambiente). Para a API publicada: --url https://SEU-USUARIO-investai-meta.hf.space
"""

import argparse
import json
import os
import uuid

import requests


def chamar(url, chave, caminho, corpo):
    resposta = requests.post(f"{url}{caminho}", json=corpo, headers={"X-API-Key": chave}, timeout=120)
    resposta.raise_for_status()
    return resposta.json()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:7860")
    ap.add_argument("--api-key", default=os.getenv("API_KEY", ""))
    ap.add_argument("--user-id", default="ana")
    args = ap.parse_args()
    thread = f"{args.user_id}-{uuid.uuid4().hex[:6]}"
    base = {"user_id": args.user_id, "thread_id": thread}

    # 1) Payload de entrada do POST /chat (é exatamente este JSON que a API recebe):
    entrada = {**base, "mensagem": "Tenho 35 anos e quero uma reserva de emergência. O que você recomenda?"}
    print("POST /chat\n", json.dumps(entrada, ensure_ascii=False, indent=2))
    saida = chamar(args.url, args.api_key, "/chat", entrada)
    print("->", json.dumps({**saida, "resposta": saida["resposta"][:300] + "..."}, ensure_ascii=False, indent=2))
    meta = saida.get("metacognicao") or {}
    print("\nComo o agente pensou:", f"confiança={meta.get('confianca')}")
    for passo in meta.get("trilha", []):
        print(f"  - {passo['no']}: {passo['decisao']} ({passo['motivo'][:80]})")

    # 2) Pedido de ordem: a API responde com `ordem_pendente` e NÃO grava nada ainda.
    saida = chamar(args.url, args.api_key, "/chat", {**base, "mensagem": "Quero comprar R$ 500 de Tesouro Selic."})
    print("\nOrdem pendente:", saida["ordem_pendente"])

    # 3) Confirmação do cliente: só agora a ordem é gravada.
    if saida["ordem_pendente"]:
        saida = chamar(args.url, args.api_key, "/chat/resume", {**base, "aprovado": True})
        print("Depois de aprovar:", saida["resposta"][:200])

    # 4) Feedback do cliente: o 👎 vira uma lição para o agente.
    fb = chamar(args.url, args.api_key, "/feedback", {**base, "nota": -1, "comentario": "Faltou dizer a data da taxa"})
    print("\nFeedback:", fb)

    # 5) Ordens do cliente (JSON) e planilha Excel.
    ordens = requests.get(f"{args.url}/ordens", params={"user_id": args.user_id}, headers={"X-API-Key": args.api_key}, timeout=30).json()
    print("\nOrdens:", json.dumps(ordens[-1:], ensure_ascii=False))
    xlsx = requests.get(f"{args.url}/ordens.xlsx", params={"user_id": args.user_id}, headers={"X-API-Key": args.api_key}, timeout=30)
    with open("ordens.xlsx", "wb") as f:
        f.write(xlsx.content)
    print(f"Planilha salva em ordens.xlsx ({len(xlsx.content)} bytes)")
