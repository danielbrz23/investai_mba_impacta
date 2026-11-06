import pytest
import requests

from investai_meta import config
from investai_meta.dados_mercado import ClienteMercado, MercadoIndisponivel, formatar_para_guia


class RespostaFake:
    def __init__(self, dados=None, conteudo=b"", status=200):
        self._dados = dados
        self.content = conteudo
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._dados


class SessaoFake:
    """Simula requests.Session: a função `responder(url, params)` decide a resposta ou levanta erro."""

    def __init__(self, responder):
        self.responder = responder
        self.chamadas = []

    def get(self, url, params=None, timeout=None):
        self.chamadas.append(url)
        return self.responder(url, params)


class Relogio:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def sgs_ok(url, params):
    return RespostaFake([{"data": "27/10/2026", "valor": "13.65"}])


def test_serie_bcb_converte_valor_e_data():
    cliente = ClienteMercado(session=SessaoFake(sgs_ok))

    serie = cliente.serie_bcb("cdi")

    assert serie == {"nome": "cdi", "valor": 13.65, "data": "27/10/2026", "desatualizado": False}


def test_cache_evita_nova_chamada_dentro_do_ttl():
    sessao = SessaoFake(sgs_ok)
    relogio = Relogio()
    cliente = ClienteMercado(session=sessao, ttl=100, agora=relogio)

    cliente.serie_bcb("selic")
    cliente.serie_bcb("selic")

    assert len(sessao.chamadas) == 1


def test_cache_expira_depois_do_ttl():
    sessao = SessaoFake(sgs_ok)
    relogio = Relogio()
    cliente = ClienteMercado(session=sessao, ttl=100, agora=relogio)

    cliente.serie_bcb("selic")
    relogio.t = 101
    cliente.serie_bcb("selic")

    assert len(sessao.chamadas) == 2


def test_falha_com_valor_anterior_devolve_desatualizado():
    estado = {"ok": True}

    def responder(url, params):
        if estado["ok"]:
            return sgs_ok(url, params)
        raise requests.ConnectionError("fora do ar")

    relogio = Relogio()
    cliente = ClienteMercado(session=SessaoFake(responder), ttl=100, agora=relogio)
    cliente.serie_bcb("cdi")

    estado["ok"] = False
    relogio.t = 500
    serie = cliente.serie_bcb("cdi")

    assert serie["valor"] == 13.65
    assert serie["desatualizado"] is True


def test_falha_sem_valor_anterior_levanta_erro_claro():
    def responder(url, params):
        raise requests.ConnectionError("fora do ar")

    cliente = ClienteMercado(session=SessaoFake(responder))

    with pytest.raises(MercadoIndisponivel):
        cliente.serie_bcb("selic")


def test_formatar_para_guia_usa_virgula_decimal():
    indicadores = {"selic": {"valor": 13.75}, "ipca_12m": {"valor": 4.58}}

    assert formatar_para_guia(indicadores) == {"selic": "13,75", "ipca_12m": "4,58"}


def test_expectativa_focus_pega_mediana_do_ano_pedido():
    def responder(url, params):
        assert "baseCalculo%20eq%200" in url  # filtro vai na URL, percent-encoded
        return RespostaFake({"value": [{"Mediana": 13.25, "Data": "2026-10-23"}]})

    cliente = ClienteMercado(session=SessaoFake(responder))

    focus = cliente.expectativa_focus("Selic", ano=2026)

    assert focus["mediana"] == 13.25
    assert focus["data"] == "2026-10-23"


CSV_TESOURO = (
    "Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;PU Compra Manha;PU Venda Manha;PU Base Manha\n"
    "Tesouro Selic;01/03/2027;26/10/2026;0,02;0,03;20170,00;20160,00;20160,00\n"
    "Tesouro IPCA+;15/05/2035;27/10/2026;6,85;6,95;3500,10;3480,00;3480,00\n"
    "Tesouro Prefixado;01/01/2029;27/10/2026;;;;;\n"
).encode("utf-8")


def test_titulos_tesouro_usa_data_base_mais_recente_e_converte_decimal():
    cliente = ClienteMercado(session=SessaoFake(lambda url, params: RespostaFake(conteudo=CSV_TESOURO)))

    tesouro = cliente.titulos_tesouro()

    assert tesouro["data_base"] == "27/10/2026"
    assert len(tesouro["titulos"]) == 2  # o Selic da data 26/10 fica de fora
    ipca = next(t for t in tesouro["titulos"] if t["tipo"] == "Tesouro IPCA+")
    assert ipca["taxa_compra"] == 6.85
    assert ipca["pu_compra"] == 3500.10
    prefixado = next(t for t in tesouro["titulos"] if t["tipo"] == "Tesouro Prefixado")
    assert prefixado["taxa_compra"] is None  # campo vazio vira None, não zero


def test_cotacao_b3_recusa_ticker_invalido_sem_sair_na_rede():
    sessao = SessaoFake(sgs_ok)
    cliente = ClienteMercado(session=sessao)

    with pytest.raises(ValueError, match="Ticker inválido"):
        cliente.cotacao_b3("../admin")

    assert sessao.chamadas == []


def test_cotacao_b3_aceita_ticker_de_fii_e_etf():
    def responder(url, params):
        return RespostaFake({"results": [{"longName": "Fundo X", "regularMarketPrice": 9.5, "regularMarketChangePercent": -0.4}]})

    cliente = ClienteMercado(session=SessaoFake(responder))

    cotacao = cliente.cotacao_b3("mxrf11")

    assert cotacao["ticker"] == "MXRF11"
    assert cotacao["preco"] == 9.5


@pytest.mark.rede
def test_api_bcb_real_responde():
    cliente = ClienteMercado()

    indicadores = cliente.indicadores()

    assert set(indicadores) == set(config.SERIES_BCB)
    assert indicadores["selic"]["valor"] > 0
