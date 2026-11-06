"""Clientes das APIs públicas brasileiras, com cache e fallback para o último valor.

Fontes: Banco Central (SGS e Focus), Tesouro Transparente (CSV) e brapi.dev (cotações B3).

Regra de falha: se a API cai e já existe um valor anterior, devolvemos esse valor marcado com
`desatualizado=True`. Se nunca houve valor, levantamos MercadoIndisponivel. O agente nunca
deve inventar um número no lugar.
"""

import csv
import io
import os
import re
import time
from datetime import datetime
from urllib.parse import quote

import requests

from investai_meta import config


class MercadoIndisponivel(Exception):
    """A API não respondeu e não há valor anterior guardado."""


PADRAO_TICKER = re.compile(r"^[A-Z]{4}\d{1,2}$")  # PETR4, BOVA11, MXRF11...


def _decimal(texto: str) -> float | None:
    """Converte '0,02' ou '20175,28' (vírgula decimal, formato do Tesouro) em float."""
    texto = (texto or "").strip().replace(".", "").replace(",", ".")
    return float(texto) if texto else None


class ClienteMercado:
    def __init__(self, session=None, ttl: float = config.CACHE_TTL_SEGUNDOS, agora=time.monotonic, persistencia=None):
        self._http = session or requests.Session()
        self._ttl = ttl
        self._agora = agora  # injetável: os testes avançam o relógio sem esperar
        self._persistencia = persistencia  # ex.: db.CacheSQLite; guarda o último valor bom no disco
        self._cache: dict[str, tuple[float, dict]] = {}

    def _obter(self, chave: str, buscar) -> dict:
        """Cache em memória dentro do TTL; senão busca. Se a API falha, usa o último valor (memória ou disco)."""
        momento = self._agora()
        anterior = self._cache.get(chave)
        if anterior and momento - anterior[0] < self._ttl:
            return anterior[1]
        try:
            resultado = {**buscar(), "desatualizado": False}
        except (requests.RequestException, ValueError, KeyError, IndexError) as erro:
            if anterior:
                return {**anterior[1], "desatualizado": True}
            salvo = self._persistencia.ler(chave) if self._persistencia else None
            if salvo:
                return {**salvo, "desatualizado": True}
            raise MercadoIndisponivel(f"{chave}: {erro}") from erro
        self._cache[chave] = (momento, resultado)
        if self._persistencia:
            self._persistencia.gravar(chave, resultado)
        return resultado

    def _get_json(self, url: str, params: dict | None = None):
        resposta = self._http.get(url, params=params, timeout=config.TIMEOUT_HTTP_SEGUNDOS)
        resposta.raise_for_status()
        return resposta.json()

    # --- Banco Central: séries do SGS -------------------------------------------------

    def serie_bcb(self, nome: str) -> dict:
        """Último valor de uma série do SGS. Ex.: serie_bcb('selic') -> {'valor': 13.75, 'data': ...}."""
        codigo = config.SERIES_BCB[nome]

        def buscar():
            url = config.BCB_SGS_URL.format(codigo=codigo, n=1)
            ultimo = self._get_json(url)[0]
            return {"nome": nome, "valor": float(ultimo["valor"]), "data": ultimo["data"]}

        return self._obter(f"bcb:{nome}", buscar)

    def indicadores(self) -> dict[str, dict]:
        """Todas as séries de config.SERIES_BCB, uma chamada por série (cada uma com cache)."""
        return {nome: self.serie_bcb(nome) for nome in config.SERIES_BCB}

    # --- Banco Central: Focus (projeções de mercado) ----------------------------------

    def expectativa_focus(self, indicador: str = "Selic", ano: int | None = None) -> dict:
        """Mediana das projeções do Focus para o ano, considerando todas as instituições (baseCalculo 0)."""
        ano = ano or datetime.now().year

        def buscar():
            # O OData do Focus recusa o '$' codificado (%24) que o requests gera em `params`.
            # Por isso a query string é montada à mão, com o filtro percent-encoded.
            filtro = quote(f"Indicador eq '{indicador}' and DataReferencia eq '{ano}' and baseCalculo eq 0", safe="")
            url = f"{config.BCB_FOCUS_URL}?$filter={filtro}&$orderby=Data%20desc&$top=1&$format=json"
            ultimo = self._get_json(url)["value"][0]
            return {
                "indicador": indicador,
                "ano": ano,
                "mediana": float(ultimo["Mediana"]),
                "data": ultimo["Data"],
            }

        return self._obter(f"focus:{indicador}:{ano}", buscar)

    # --- Tesouro Transparente ---------------------------------------------------------

    def titulos_tesouro(self) -> dict:
        """Títulos do Tesouro Direto na data-base mais recente do CSV oficial."""

        def buscar():
            resposta = self._http.get(config.TESOURO_CSV_URL, timeout=config.TIMEOUT_HTTP_SEGUNDOS)
            resposta.raise_for_status()
            texto = resposta.content.decode("utf-8-sig", errors="replace")
            linhas = list(csv.DictReader(io.StringIO(texto), delimiter=";"))
            base = max(linhas, key=lambda l: datetime.strptime(l["Data Base"], "%d/%m/%Y"))["Data Base"]
            titulos = [
                {
                    "tipo": l["Tipo Titulo"],
                    "vencimento": l["Data Vencimento"],
                    "taxa_compra": _decimal(l["Taxa Compra Manha"]),
                    "pu_compra": _decimal(l["PU Compra Manha"]),
                }
                for l in linhas
                if l["Data Base"] == base
            ]
            return {"data_base": base, "titulos": titulos}

        return self._obter("tesouro", buscar)

    # --- B3 via brapi.dev -------------------------------------------------------------

    def cotacao_b3(self, ticker: str) -> dict:
        """Cotação de uma ação, FII ou ETF. Ticker inválido é recusado antes de sair na rede."""
        ticker = ticker.upper().strip()
        if not PADRAO_TICKER.match(ticker):
            raise ValueError(f"Ticker inválido: {ticker!r}")

        def buscar():
            params = {"token": os.getenv("BRAPI_TOKEN")} if os.getenv("BRAPI_TOKEN") else None
            item = self._get_json(config.BRAPI_URL.format(ticker=ticker), params)["results"][0]
            return {
                "ticker": ticker,
                "nome": item.get("longName") or item.get("shortName"),
                "preco": float(item["regularMarketPrice"]),
                "variacao_pct": float(item["regularMarketChangePercent"]),
                "moeda": item.get("currency", "BRL"),
            }

        return self._obter(f"b3:{ticker}", buscar)


def formatar_para_guia(indicadores: dict[str, dict]) -> dict[str, str]:
    """Converte as séries do BCB para os placeholders do guia: {'selic': '13,75'}.

    Valor desatualizado também entra: a data de referência fica registrada no store.
    """
    return {nome: f"{serie['valor']:.2f}".replace(".", ",") for nome, serie in indicadores.items()}
