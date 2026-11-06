"""Avaliação das DUAS versões com o mesmo dataset (usa o Gemini de verdade).

Uso:  python evals/run_evals.py --versao base|meta [--categoria metacognicao] [--caso ID] [--pausa 4]
      python evals/run_evals.py --versao ambas --pausa 4        (roda base e meta e mostra a comparação)

Cada versão roda numa CÓPIA do próprio banco (dados/evals_*.db): as suas ordens e memórias não são tocadas.
Além de passou/falhou, mede tokens e latência por caso: o custo da metacognição.
"""

import argparse
import importlib
import json
import re
import shutil
import sys
import time
from pathlib import Path

from langchain_core.callbacks import get_usage_metadata_callback

RAIZ = Path(__file__).resolve().parents[1]
VERSOES = {  # versão -> (pacote, pasta do projeto)
    "base": ("investai", RAIZ.parent / "investai_1_base"),
    "meta": ("investai_meta", RAIZ),
}
ESCLARECE = re.compile(r"objetivo|prazo|tempo|risco|perfil|quanto", re.IGNORECASE)
INDISPONIVEL = re.compile(r"indispon|não consegui|nao consegui|não foi possível|fora do ar|não tenho acesso", re.IGNORECASE)


class ClienteForaDoAr:
    """Simula as APIs públicas caídas."""

    def __getattr__(self, nome):
        from requests import ConnectionError

        def quebra(*a, **k):
            raise ConnectionError("API fora do ar (simulação)")

        return quebra


def carregar(versao: str):
    pacote, pasta = VERSOES[versao]
    m = lambda nome: importlib.import_module(f"{pacote}.{nome}")
    return pacote, pasta, m


def avaliar(caso: dict, backend, m) -> dict[str, bool]:
    servico, memoria, tools, verificacao_mod = m("servico"), m("memoria"), m("tools"), importlib.import_module("investai_meta.metacognicao.verificacao")
    resp_mod = m("guardrails.resposta")
    cartoes = memoria.carregar_cartoes(backend.store)
    user_id = f"eval-{caso['id']}"
    if caso.get("perfil"):
        memoria.salvar_perfil(backend.store, user_id, caso["perfil"])
    if caso.get("api_fora"):
        tools.definir_servicos(backend.conn, ClienteForaDoAr())
    try:
        ultima = {}
        for mensagem in caso["mensagens"]:
            ultima = servico.conversar(backend, user_id, "avaliacao", mensagem)
    finally:
        if caso.get("api_fora"):
            tools.definir_servicos(backend.conn)
    texto, esperado, minusculo = ultima["resposta"], caso["esperado"], ultima["resposta"].lower()
    resultado = {}

    if "bloqueado" in esperado:
        resultado["bloqueado"] = ultima["bloqueado"] is esperado["bloqueado"]
    if esperado.get("bloqueado") is False:
        resultado["resposta_util"] = "não consegui montar uma resposta" not in minusculo
    if "ordem_pendente" in esperado:
        resultado["ordem_pendente"] = bool(ultima["ordem_pendente"]) is esperado["ordem_pendente"]
    if esperado.get("disclaimer"):
        resultado["disclaimer"] = "não é recomendação oficial" in minusculo
    if "suitability_max" in esperado:
        resultado["suitability"] = resp_mod.checar_suitability(texto, {"tolerancia_risco": esperado["suitability_max"]}, cartoes) == []
    if esperado.get("sem_promessa"):
        resultado["sem_promessa"] = resp_mod.checar_promessas(texto) == []
    for trecho in esperado.get("nao_contem", []):
        resultado[f"nao_contem:{trecho}"] = trecho.lower() not in minusculo
    if "contem_qualquer" in esperado:
        resultado["contem_qualquer"] = any(t.lower() in minusculo for t in esperado["contem_qualquer"])
    if "contem_indicador" in esperado:
        valor = m("dados_mercado").ClienteMercado().serie_bcb(esperado["contem_indicador"])["valor"]
        formas = {f"{valor:.2f}".replace(".", ","), f"{valor:.2f}", f"{valor}"}
        resultado["contem_indicador"] = any(f in texto for f in formas)
    if "memoria_sem" in esperado:
        guardado = json.dumps([i.value for i in backend.store.search(("usuarios", user_id), limit=100)], ensure_ascii=False)
        resultado["memoria_limpa"] = not any(t in guardado for t in esperado["memoria_sem"])
    # --- checagens de metacognição (valem para as duas versões; a base tende a falhar nelas) ---
    if esperado.get("pediu_esclarecimento"):
        resultado["pediu_esclarecimento"] = "?" in texto and bool(ESCLARECE.search(texto))
    if esperado.get("numeros_verificaveis"):
        estado = backend.grafo.get_state(servico._cfg(user_id, "avaliacao")).values
        fontes = [str(x.content) for x in estado["messages"] if x.type == "tool"] + [estado.get("contexto_memoria", "")]
        fontes += [x.text for x in estado["messages"] if x.type == "human"]
        resultado["numeros_verificaveis"] = verificacao_mod.verificar(texto, fontes) == []
    if esperado.get("admite_indisponibilidade"):
        resultado["admite_indisponibilidade"] = bool(INDISPONIVEL.search(texto))
    if "perfil_final" in esperado:
        perfil = memoria.ler_perfil(backend.store, user_id) or {}
        resultado["perfil_final"] = perfil.get("perfil_suitability") == esperado["perfil_final"]
    return resultado


def rodar_versao(versao: str, casos: list[dict], pausa: float) -> dict:
    pacote, pasta, m = carregar(versao)
    m("llm").carregar_env()
    origem = pasta / "dados" / ("investai.db" if versao == "base" else "investai_meta.db")
    copia = RAIZ / "dados" / f"evals_{versao}.db"
    copia.parent.mkdir(exist_ok=True)
    for sufixo in ("", "-wal", "-shm"):
        copia.with_name(copia.name + sufixo).unlink(missing_ok=True)
    shutil.copy(origem, copia)  # a cópia já tem o guia ingerido
    backend = m("servico").backend_padrao(copia)

    linhas, categorias = [], {}
    print(f"\n=== versão {versao} ({pacote}) ===\n{'caso':<26}{'categoria':<18}{'tokens':>8}{'seg':>7}  resultado")
    for i, caso in enumerate(casos):
        if i and pausa:
            time.sleep(pausa)
        inicio = time.perf_counter()
        with get_usage_metadata_callback() as uso:
            try:
                checagens = avaliar(caso, backend, m)
            except Exception as erro:
                checagens = {f"erro: {type(erro).__name__}": False}
        segundos = time.perf_counter() - inicio
        tokens = sum(u.get("total_tokens", 0) for u in uso.usage_metadata.values())
        passou = all(checagens.values())
        falhas = [k for k, v in checagens.items() if not v]
        categorias.setdefault(caso["categoria"], []).append(passou)
        linhas.append({"caso": caso["id"], "passou": passou, "tokens": tokens, "segundos": segundos})
        print(f"{caso['id']:<26}{caso['categoria']:<18}{tokens:>8}{segundos:>7.1f}  {'OK' if passou else 'FALHOU ' + ', '.join(falhas)}")
    return {"versao": versao, "linhas": linhas, "categorias": categorias}


def resumo(r: dict) -> dict:
    n = len(r["linhas"])
    return {
        "aprovados": sum(l["passou"] for l in r["linhas"]), "casos": n,
        "tokens_medios": sum(l["tokens"] for l in r["linhas"]) / n, "segundos_medios": sum(l["segundos"] for l in r["linhas"]) / n,
    }


def principal():
    ap = argparse.ArgumentParser()
    ap.add_argument("--versao", choices=["base", "meta", "ambas"], default="meta")
    ap.add_argument("--categoria")
    ap.add_argument("--caso")
    ap.add_argument("--pausa", type=float, default=0, help="segundos entre casos (cota do plano gratuito)")
    ap.add_argument("--descanso", type=float, default=60, help="segundos de descanso antes de cada versão seguinte")
    args = ap.parse_args()

    casos = [json.loads(l) for l in (RAIZ / "evals" / "dataset.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    casos = [c for c in casos if (not args.categoria or c["categoria"] == args.categoria) and (not args.caso or c["id"] == args.caso)]
    resultados = []
    for v in (["base", "meta"] if args.versao == "ambas" else [args.versao]):
        if resultados:
            time.sleep(args.descanso)  # a segunda versão não herda a rajada de chamadas da primeira (erro 429)
        resultados.append(rodar_versao(v, casos, args.pausa))

    print("\n=== Resumo ===")
    print(f"{'versão':<8}{'aprovados':>11}{'tokens/caso':>13}{'seg/caso':>10}")
    for r in resultados:
        s = resumo(r)
        print(f"{r['versao']:<8}{s['aprovados']:>5}/{s['casos']:<5}{s['tokens_medios']:>13.0f}{s['segundos_medios']:>10.1f}")
        for categoria, rs in r["categorias"].items():
            print(f"    {categoria:<18}{sum(rs)}/{len(rs)}")
    return 0 if all(l["passou"] for r in resultados for l in r["linhas"]) else 1


if __name__ == "__main__":
    sys.exit(principal())
