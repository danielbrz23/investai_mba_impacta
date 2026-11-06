---
title: InvestAI Metacognição
emoji: 🧠
colorFrom: purple
colorTo: blue
sdk: docker
app_port: 7860
---

# InvestAI — pasta 2 (com metacognição)

Cópia da pasta `investai_1_base/` (mesmo conhecimento, mesmas ferramentas, mesmos guardrails, mesma API) **mais** uma camada em que
o agente **monitora, avalia e regula o próprio raciocínio**. O pacote se chama `investai_meta`, para as duas pastas
coexistirem no mesmo ambiente. Resultados lado a lado em [`COMPARATIVO.md`](COMPARATIVO.md).

> Conteúdo didático. Nada aqui é recomendação oficial de investimento.

## O que muda em relação à pasta 1

```
START → guarda_entrada → carregar_memoria (★ lições + ★ prompt procedural) → ★ planejar ─┬─ ★ perguntar_cliente → guarda_memoria
                                                                                         └→ agente ⇄ ferramentas → ★ monitor_loop ⟶ ★ replanejar
agente → ★ autoavaliar ─(confiança baixa)→ ★ replanejar → agente
              ↓
        ★ verificar_fatos → guarda_resposta ─(reprovada)→ ★ reescrever → ★ verificar_fatos
              ↓                           └─(esgotou)→ resposta_segura → ★ registrar_licao
        guarda_memoria → memorizar (★ com reflexão sobre contradições) → END
```

| Capacidade | Pasta 1 (base) | Pasta 2 (metacognição) | Módulo |
|---|---|---|---|
| Planejamento | ReAct passo a passo | planeja antes; **pergunta ao cliente** quando falta objetivo, prazo ou risco | `planejador.py` |
| Saber o que não sabe | responde com o que tem | **autoavalia** a confiança e as lacunas; replaneja 1 vez; avisa a incerteza | `autoavaliacao.py` |
| Controle do loop | limite fixo de voltas | **monitor** detecta chamada repetida ou falhas em sequência e troca de estratégia | `monitor_loop.py` |
| Números na resposta | confia no LLM | **verifica** cada R$ e % contra as saídas das ferramentas | `verificacao.py` |
| Resposta reprovada | vai direto para a mensagem segura | **autocrítica e reescrita** (até 2×) | `autocritica.py` |
| Aprender com erros | — | falhas e 👎 viram **lições** (Reflexion), recuperadas por similaridade | `licoes.py` |
| Aprender com feedback | prompt fixo | **prompt procedural** otimizado pelo LangMem, com diff, validação e rollback | `procedural.py` |
| Memória do cliente | recusa mudança brusca de perfil | **pergunta se o cliente quer mesmo mudar** e só aplica com um "sim" | `reflexao_memoria.py` |
| Transparência | resposta | resposta + **"como o agente pensou"** (plano, confiança, trilha de decisões) | `servico.py`, UI |

Princípios da camada: cada módulo é testável sozinho; os que usam LLM **degradam** (planejador, autoavaliação e replanejador
nunca derrubam o atendimento); e tudo o que o agente aprende passa pelo mesmo crivo de segurança da memória do cliente.

## Rodando

```bash
pip install -r requirements.txt && pip install -e . --no-deps
cp .env.example .env                                  # GEMINI_API_KEY
python scripts/clonar_conhecimento.py                 # copia o guia já ingerido da pasta 1 (1 s, sem gastar cota)
#   ou: python scripts/ingerir_conhecimento.py        # ingere do zero (~5 min)
python scripts/conversar.py ana                       # terminal, mostrando a trilha de metacognição
pytest                                                # testes sem rede
langgraph dev                                         # Studio: grafo "investai_meta", context {"user_id": "ana"}
uvicorn app.api:app --port 7860                       # API em /docs, interface em /ui
```

### API (o que é novo)

`POST /chat` devolve, além de `resposta`, `ordem_pendente` e `bloqueado`, o bloco **`metacognicao`**:

```json
{
  "resposta": "Para indicar algo adequado, qual é o seu objetivo e em quanto tempo você precisa do dinheiro?",
  "ordem_pendente": null, "bloqueado": false,
  "metacognicao": {
    "plano": ["descobrir o perfil", "sugerir produtos"], "confianca": 1.0, "lacunas": [],
    "licoes_usadas": [], "reescritas": 0, "replanejamentos": 0,
    "trilha": [{"no": "planejar", "decisao": "perguntar ao cliente", "motivo": "falta: objetivo, prazo"}]
  }
}
```

| Rota nova | Função |
|---|---|
| `POST /feedback` `{"user_id","thread_id","nota":1\|-1,"comentario"}` | registra 👍/👎; o 👎 vira uma lição |
| `GET /licoes` | lições aprendidas até agora |

### Memória procedural (prompt que evolui)

```bash
python scripts/otimizar_prompt.py             # usa os feedbacks, mostra o DIFF e valida (não grava)
python scripts/otimizar_prompt.py --aplicar   # ativa o prompt novo (o anterior vai para o histórico)
python scripts/otimizar_prompt.py --reverter  # rollback
```

O prompt novo é recusado se perder as regras de segurança (`dados_nao_confiaveis`, `registrar_ordem`, `FGC`, "Nunca prometa")
ou se tiver padrão de injeção, e nada é ativado sem um humano ver o diff.

### Avaliação comparativa

```bash
python evals/run_evals.py --versao ambas --pausa 4      # 23 casos nas duas pastas: aprovação, tokens e segundos por caso
python evals/run_evals.py --versao meta --categoria metacognicao
```

## Limitações conhecidas

- **Custo:** cada turno faz mais chamadas ao LLM (plano, autoavaliação e, às vezes, replanejamento, reescrita e lição).
  Com a cota gratuita do Gemini isso pesa; veja os números no `COMPARATIVO.md`.
- A verificação de números é heurística: confere valores em R$ e % contra as fontes (tolerância de 1%) e pode reprovar
  uma conta derivada legítima, que então é reescrita ou cai na mensagem segura.
- A confiança que o modelo reporta sobre si mesmo é uma estimativa, não uma garantia.
- Lições e prompt otimizado são geradas por LLM a partir de texto de clientes; por isso passam por validação e o prompt exige aprovação humana.
- O deploy (Dockerfile pronto) **não foi publicado**; mesmas instruções e cuidados da pasta 1.
