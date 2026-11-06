import sqlite3

import pytest
import requests

from investai_meta import db
from investai_meta.dados_mercado import ClienteMercado, MercadoIndisponivel


@pytest.fixture
def caminho(tmp_path):
    return tmp_path / "teste.db"


@pytest.fixture
def conn(caminho):
    return db.conectar(caminho)


def test_conectar_cria_tabelas_do_projeto(conn):
    tabelas = {l["name"] for l in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert {"ordens", "cache_mercado"} <= tabelas


def test_ordem_e_gravada_e_listada_por_usuario(conn):
    db.inserir_ordem(conn, "ana", "tesouro-selic", "compra", 5000.0, status="aprovada", thread_id="t1")
    db.inserir_ordem(conn, "bruno", "lci", "compra", 1000.0, status="rejeitada")

    ordens_ana = db.listar_ordens(conn, "ana")

    assert len(ordens_ana) == 1
    assert ordens_ana[0]["produto_id"] == "tesouro-selic"
    assert ordens_ana[0]["status"] == "aprovada"
    assert len(db.listar_ordens(conn)) == 2


@pytest.mark.parametrize(
    "tipo, valor, status",
    [("troca", 100.0, "aprovada"), ("compra", -5.0, "aprovada"), ("compra", 100.0, "talvez")],
)
def test_banco_recusa_ordem_invalida(conn, tipo, valor, status):
    with pytest.raises(sqlite3.IntegrityError):
        db.inserir_ordem(conn, "ana", "lci", tipo, valor, status=status)


def test_store_sem_embeddings_guarda_e_le_memoria(caminho):
    store = db.abrir_store(caminho)

    store.put(("usuarios", "ana", "perfil"), "p1", {"texto": "perfil conservador"})

    assert store.get(("usuarios", "ana", "perfil"), "p1").value["texto"] == "perfil conservador"
    assert store.get(("usuarios", "bruno", "perfil"), "p1") is None  # memória isolada por usuário


def test_memoria_sobrevive_a_nova_conexao(tmp_path):
    caminho = tmp_path / "persistente.db"
    db.abrir_store(caminho).put(("x",), "k", {"texto": "lembrar"})

    novo = db.abrir_store(caminho)

    assert novo.get(("x",), "k").value["texto"] == "lembrar"


def test_cache_sqlite_grava_e_le(conn):
    cache = db.CacheSQLite(conn)

    cache.gravar("bcb:selic", {"valor": 13.75, "data": "04/11/2026"})

    assert cache.ler("bcb:selic") == {"valor": 13.75, "data": "04/11/2026"}
    assert cache.ler("inexistente") is None


class _SessaoQueFalha:
    def get(self, url, params=None, timeout=None):
        raise requests.ConnectionError("fora do ar")


def test_api_fora_do_ar_usa_valor_guardado_no_disco(conn):
    cache = db.CacheSQLite(conn)
    cache.gravar("bcb:selic", {"nome": "selic", "valor": 13.75, "data": "04/11/2026", "desatualizado": False})
    cliente = ClienteMercado(session=_SessaoQueFalha(), persistencia=cache)  # cliente novo: memória vazia

    serie = cliente.serie_bcb("selic")

    assert serie["valor"] == 13.75
    assert serie["desatualizado"] is True


def test_api_fora_do_ar_sem_nada_guardado_levanta_erro(conn):
    cliente = ClienteMercado(session=_SessaoQueFalha(), persistencia=db.CacheSQLite(conn))

    with pytest.raises(MercadoIndisponivel):
        cliente.serie_bcb("selic")
