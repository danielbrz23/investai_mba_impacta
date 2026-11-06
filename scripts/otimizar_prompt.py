"""Memória procedural: otimiza o prompt do assessor com o feedback 👍/👎 dos clientes (LangMem).

  python scripts/otimizar_prompt.py             mostra o diff do prompt proposto (não grava nada)
  python scripts/otimizar_prompt.py --aplicar   ativa o prompt novo (a versão atual vai para o histórico)
  python scripts/otimizar_prompt.py --reverter  volta para a versão anterior

O prompt novo só vale se mantiver as regras de segurança e não tiver padrões de injeção (procedural.validar),
e um humano precisa conferir o diff antes de usar --aplicar.
"""

import argparse
import sys

import _caminhos  # noqa: F401

from investai_meta import db
from investai_meta.llm import criar_embeddings, criar_llm
from investai_meta.metacognicao import procedural

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--reverter", action="store_true")
    ap.add_argument("--limite", type=int, default=20, help="quantos feedbacks recentes usar")
    args = ap.parse_args()

    store = db.abrir_store(embeddings=criar_embeddings())
    if args.reverter:
        print("Prompt anterior restaurado." if procedural.reverter(store) else "Não há versão anterior para restaurar.")
        sys.exit(0)

    feedbacks = db.listar_feedbacks(db.conectar())
    trajetorias = procedural.trajetorias_de_feedback(db.abrir_checkpointer(), feedbacks, args.limite)
    if not trajetorias:
        raise SystemExit("Nenhum feedback com conversa encontrado. Use 👍/👎 na interface ou POST /feedback primeiro.")

    atual = procedural.prompt_atual(store)
    print(f"Otimizando com {len(trajetorias)} trajetória(s)...")
    novo = procedural.otimizar(criar_llm(), atual, trajetorias)
    valido, motivo = procedural.validar(novo, atual)
    print("\n" + (procedural.diff(atual, novo) or "(sem diferenças)"))
    if not valido:
        raise SystemExit(f"\nPrompt proposto RECUSADO: {motivo}")
    if args.aplicar:
        procedural.aplicar(store, novo)
        print("\nPrompt novo ativado. Para desfazer: --reverter")
    else:
        print("\nValidação ok. Rode com --aplicar para ativar.")
