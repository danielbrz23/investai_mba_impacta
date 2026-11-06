"""Busca os dados públicos (BCB, Focus, Tesouro, B3) e guarda o último valor bom no banco local.

Rode uma vez por dia. Se uma API cair depois, o agente usa o valor guardado, marcado como desatualizado.
"""

import os

import _caminhos  # noqa: F401
from dotenv import load_dotenv

from investai_meta import db
from investai_meta.dados_mercado import ClienteMercado, MercadoIndisponivel

if __name__ == "__main__":
    # .env da pasta do projeto; se não existir, o da raiz do repositório (onde estão as chaves).
    load_dotenv(_caminhos.RAIZ / ".env")
    load_dotenv(_caminhos.RAIZ.parent / ".env")
    conn = db.conectar()
    cliente = ClienteMercado(persistencia=db.CacheSQLite(conn))

    print("Banco Central (SGS):")
    for nome, serie in cliente.indicadores().items():
        marca = " (desatualizado)" if serie["desatualizado"] else ""
        print(f"  {nome:<10} {serie['valor']:>10}  em {serie['data']}{marca}")

    for indicador in ("Selic", "IPCA"):
        try:
            f = cliente.expectativa_focus(indicador)
            print(f"Focus {indicador} {f['ano']}: mediana {f['mediana']}% (de {f['data']})")
        except MercadoIndisponivel as erro:
            print(f"Focus {indicador}: indisponível ({erro})")

    try:
        tesouro = cliente.titulos_tesouro()
        print(f"Tesouro: {len(tesouro['titulos'])} títulos na data-base {tesouro['data_base']}")
    except MercadoIndisponivel as erro:
        print(f"Tesouro: indisponível ({erro})")

    token = "com token" if os.getenv("BRAPI_TOKEN") else "sem token (só alguns tickers)"
    print(f"B3 via brapi ({token}):")
    for ticker in ("PETR4", "BOVA11"):
        try:
            c = cliente.cotacao_b3(ticker)
            print(f"  {ticker}: R$ {c['preco']}")
        except MercadoIndisponivel as erro:
            print(f"  {ticker}: indisponível ({erro})")
