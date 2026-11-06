"""Interface Gradio: chat com confirmação de ordens, painel "como o agente pensou", feedback 👍/👎, ordens e memória."""

import tempfile
import uuid
from pathlib import Path

import gradio as gr

from investai_meta import servico


def montar_ui(app, obter_backend):
    """Monta a interface em /ui dentro do app FastAPI. `obter_backend` é chamado a cada clique."""

    def _pensamento(m):
        if not m:
            return ""
        confianca = m.get("confianca")
        linhas = [f"**Confiança:** {'▓' * round((confianca or 0) * 10)}{'░' * (10 - round((confianca or 0) * 10))} {confianca:.0%}" if confianca is not None else ""]
        if m.get("plano"):
            linhas.append("**Plano:** " + " → ".join(m["plano"]))
        if m.get("lacunas"):
            linhas.append("**Lacunas:** " + "; ".join(m["lacunas"]))
        if m.get("licoes_usadas"):
            linhas.append("**Lições aplicadas:** " + "; ".join(m["licoes_usadas"]))
        linhas.append(f"**Reescritas:** {m.get('reescritas', 0)} · **Replanejamentos:** {m.get('replanejamentos', 0)}")
        if m.get("trilha"):
            linhas.append("\n**Trilha de decisões**\n" + "\n".join(f"- `{t['no']}` → {t['decisao']}" + (f" ({t['motivo']})" if t["motivo"] else "") for t in m["trilha"]))
        return "\n\n".join(l for l in linhas if l)

    def enviar(user_id, mensagem, historico, thread_id):
        if not mensagem.strip():
            return historico, "", thread_id, gr.update(visible=False), "", ""
        thread_id = thread_id or f"ui-{uuid.uuid4().hex[:8]}"
        historico = historico + [{"role": "user", "content": mensagem}]
        try:
            r = servico.conversar(obter_backend(), user_id.strip(), thread_id, mensagem)
        except ValueError as erro:
            r = {"resposta": f"⚠️ {erro}", "ordem_pendente": None}
        except Exception:
            r = {"resposta": "⚠️ Serviço indisponível no momento. Tente novamente em instantes.", "ordem_pendente": None}
        historico = historico + [{"role": "assistant", "content": r["resposta"]}]
        return historico, "", thread_id, *_card(r["ordem_pendente"]), _pensamento(r.get("metacognicao"))

    def decidir(aprovado, user_id, historico, thread_id):
        try:
            r = servico.retomar(obter_backend(), user_id.strip(), thread_id, aprovado)
        except Exception:
            r = {"resposta": "⚠️ Não há ordem aguardando confirmação.", "ordem_pendente": None}
        return historico + [{"role": "assistant", "content": r["resposta"]}], *_card(r["ordem_pendente"])

    def avaliar(nota, user_id, thread_id, comentario):
        if not thread_id:
            return "Converse primeiro."
        try:
            r = servico.registrar_feedback(obter_backend(), user_id.strip(), thread_id, nota, comentario or None)
        except Exception:
            return "⚠️ Não consegui registrar o feedback."
        return "Obrigado! O agente aprendeu uma lição com isso." if r["licao_gravada"] else "Obrigado pelo feedback!"

    def _card(ordem):
        if not ordem:
            return gr.update(visible=False), ""
        texto = (f"### Confirmar ordem\n**{ordem['ordem'].upper()}** de **R$ {ordem['valor']:,.2f}** em "
                 f"**{ordem['produto']}** (risco {ordem['risco']}/5)")
        return gr.update(visible=True), texto

    def carregar_ordens(user_id):
        linhas = servico.listar_ordens(obter_backend(), user_id.strip() or None)
        return [[o["criado_em"], o["user_id"], o["produto_id"], o["tipo"], o["valor"], o["status"]] for o in linhas]

    def gerar_excel(user_id):
        caminho = Path(tempfile.mkdtemp()) / "ordens.xlsx"
        caminho.write_bytes(servico.ordens_em_excel(obter_backend(), user_id.strip() or None))
        return str(caminho)

    def ver_memoria(user_id):
        try:
            return servico.ver_memoria(obter_backend(), user_id.strip())
        except ValueError as erro:
            return {"erro": str(erro)}

    with gr.Blocks(title="InvestAI") as demo:
        gr.Markdown("# InvestAI\nAssessor de investimentos **educacional**. Não é recomendação oficial de investimento.")
        user_id = gr.Textbox(label="Cliente (user_id)", value="ana", max_lines=1)
        with gr.Tab("Chat"):
            thread = gr.State("")
            chat = gr.Chatbot(height=420, label="Conversa")
            with gr.Group(visible=False) as cartao:
                texto_ordem = gr.Markdown()
                with gr.Row():
                    aprovar = gr.Button("✅ Aprovar", variant="primary")
                    rejeitar = gr.Button("❌ Rejeitar")
            msg = gr.Textbox(label="Mensagem", placeholder="Ex.: Tenho 35 anos e quero montar uma reserva de emergência.")
            with gr.Accordion("Como o agente pensou", open=False):
                pensamento = gr.Markdown("Envie uma mensagem para ver o plano, a confiança e as decisões do agente.")
            with gr.Row():
                comentario = gr.Textbox(label="Comentário (opcional)", scale=4, max_lines=1)
                bom = gr.Button("👍", scale=1)
                ruim = gr.Button("👎", scale=1)
            retorno = gr.Markdown()
            bom.click(lambda u, t, c: avaliar(1, u, t, c), [user_id, thread, comentario], [retorno])
            ruim.click(lambda u, t, c: avaliar(-1, u, t, c), [user_id, thread, comentario], [retorno])
            msg.submit(enviar, [user_id, msg, chat, thread], [chat, msg, thread, cartao, texto_ordem, pensamento])
            aprovar.click(lambda u, h, t: decidir(True, u, h, t), [user_id, chat, thread], [chat, cartao, texto_ordem])
            rejeitar.click(lambda u, h, t: decidir(False, u, h, t), [user_id, chat, thread], [chat, cartao, texto_ordem])
        with gr.Tab("Ordens"):
            tabela = gr.Dataframe(
                headers=["criado_em", "cliente", "produto", "tipo", "valor (R$)", "status"], interactive=False,
            )
            with gr.Row():
                atualizar = gr.Button("Atualizar")
                baixar = gr.Button("Gerar Excel")
            arquivo = gr.File(label="ordens.xlsx")
            atualizar.click(carregar_ordens, [user_id], [tabela])
            baixar.click(gerar_excel, [user_id], [arquivo])
        with gr.Tab("Lições do agente"):
            gr.Markdown("Erros que viraram regra (Reflexion). O 👎 e os guardrails alimentam esta lista.")
            ver_licoes = gr.Button("Atualizar")
            tabela_licoes = gr.Dataframe(headers=["regra", "situação", "erro"], interactive=False)
            ver_licoes.click(lambda: [[l["regra"], l["situacao"], l["erro"]] for l in servico.listar_licoes(obter_backend())], None, [tabela_licoes])
        with gr.Tab("Memória do cliente"):
            gr.Markdown("O que o assistente guardou sobre este cliente (por isso é importante o guardrail de memória).")
            ver = gr.Button("Ver memória")
            saida = gr.JSON()
            ver.click(ver_memoria, [user_id], [saida])

    return gr.mount_gradio_app(app, demo, path="/ui", theme=gr.themes.Soft())
