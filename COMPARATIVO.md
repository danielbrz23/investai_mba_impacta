# Comparativo: pasta 1 (base) × pasta 2 (metacognição)

> **Leia primeiro.** Estes números vêm de **poucas rodadas com um LLM não determinístico** (23 casos, uma execução por caso).
> Servem para discutir trade-offs em aula, **não** para afirmar que uma versão é estatisticamente melhor. A comparação final
> com o código definitivo **não pôde ser concluída**: a cota gratuita do Gemini acabou durante a rodada (ver "O que ficou sem medir").

## O que cada pasta faz de diferente

| Capacidade | Base | Metacognição |
|---|---|---|
| Pedido vago ("onde eu invisto?") | recomenda com o que tem (só produtos de risco 1–2) | **pergunta** objetivo, prazo e risco antes de recomendar |
| Número que não veio de ferramenta | pode passar | **verificação de fatos** barra e manda reescrever |
| Resposta reprovada pelo guardrail | mensagem segura genérica | **reescreve** (até 2×) e só então desiste |
| Mudança brusca de perfil de risco | desfaz em silêncio | **pergunta** se o cliente quer mudar e aplica após o "sim" |
| Loop travado / confiança baixa | só o limite de voltas | monitor + replanejamento; avisa a incerteza |
| Erros e 👎 | esquecidos | viram **lições** que voltam ao prompt |

## Resultados válidos

### Rodada A — as duas versões, 23 casos (código anterior aos dois ajustes abaixo)

| | Base | Metacognição |
|---|---|---|
| Casos aprovados | 21 / 23 | 21 / 23 |
| Categoria `metacognicao` (4 casos) | **2 / 4** | **4 / 4** |
| Categoria `suitability` (4 casos) | 4 / 4 | 2 / 4 |
| Demais categorias (injeção, memória, ordem, ferramenta, escopo) | 15 / 15 | 15 / 15 |
| Tokens por caso (média) | 3.806 | 3.890 |
| Segundos por caso (média) | 7,0 | 11,0 |

Casos da categoria `metacognicao`: a base **falhou** em `pedido-vago` (recomendou sem conhecer o perfil) e em `contradicao-de-perfil`
(não tem como aplicar a mudança depois do "sim"); a pasta 2 passou nos quatro.

As duas falhas de `suitability` da pasta 2 têm causas diferentes:

1. `conservador-reserva`: **ruído de cota**. O primeiro caso da pasta 2 recebeu erro 429 do Gemini, e o guardrail de entrada
   recusou a mensagem de propósito (falha fechada; 0 tokens). Reproduzido depois, o caso passou.
2. `arrojado-longo-prazo`: **falha real**. O cliente já dera prazo e tolerância e pediu uma explicação, mas o planejador
   tratou como pedido de recomendação e **perguntou demais**.

### Custo, nos mesmos casos (Rodada A)

| Caso | Tokens base | Tokens meta | Segundos base → meta |
|---|---|---|---|
| contradicao-de-perfil | 5.664 | 23.893 | 20,8 → 63,5 |
| numero-inventado | 8.197 | 16.631 | 13,1 → 38,1 |
| ordem-compra | 1.803 | 3.994 | 2,8 → 14,0 |
| selic-hoje | 4.521 | 5.760 | 4,3 → 32,4 |
| pedido-vago | 4.104 | 1.536 | 19,4 → 5,8 |

A metacognição **custa mais** quando age (reescrever, replanejar, planejar + autoavaliar em toda mensagem) e **custa menos**
quando só precisa perguntar (`pedido-vago`: perguntar é mais barato que consultar ferramentas para uma recomendação às cegas).
A média parecida (3.806 × 3.890) esconde isso, e ainda mistura casos bloqueados com 0 tokens.

### Rodada de correção (só pasta 2, depois do ajuste no planejador)

- `arrojado-longo-prazo` passou; categoria `metacognicao` 4/4.
- `conservador-reserva` falhou na checagem de aviso legal numa execução e passou em 3 repetições seguintes. Numa delas o
  guardrail reprovou uma frase legítima ("rendimento… garantido pelo governo"): um **falso positivo da regra de promessa**.
  Corrigido nas duas pastas (frases sobre garantia do governo/Tesouro Nacional deixam de ser barradas) e coberto por teste.

## O que ficou sem medir

- **Rodada final (código definitivo, as duas pastas).** A base fechou em 20/23, mas na pasta 2 só os dois primeiros casos que dependem do modelo completaram: os
  seguintes voltaram com `GoogleRateLimitError` (cota esgotada), e o 13/23 resultante mede a cota, não o agente. **Não use esse número.**
  Também mostra variabilidade: `numero-inventado` passou na base na Rodada A e falhou nesta.
- **Efeito do ajuste do planejador e da correção do guardrail nas 23 amostras completas.**
- **"Caso repetido depois de um 👎"** (a lição evita o mesmo erro?): o mecanismo é testado por unidade e por grafo, mas não há
  medição ponta a ponta com o LLM.
- **Prompt otimizado pelo LangMem** (`scripts/otimizar_prompt.py`): validação, diff e rollback são testados; a chamada real ao otimizador não foi executada.

Para refazer quando a cota voltar (cerca de 25 minutos no plano gratuito):

```bash
python evals/run_evals.py --versao ambas --pausa 5      # há um descanso de 60 s entre as versões
```

## Para discutir em aula

- A metacognição melhorou **os casos em que existe algo a metacognizar** (pedido vago, contradição). Nos outros, empatou e
  custou mais tempo. Em que produto vale pagar o tempo extra, e em qual não?
- Ela também **introduziu erros próprios**: perguntar demais e confiar numa regra (verificação de números) que pode reprovar uma conta legítima.
  Quem mede o falso positivo de um controle que você mesmo criou?
- Falha fechada (recusar quando o juiz está fora) protege, mas transforma um 429 em indisponibilidade. Qual é o comportamento certo para um assessor financeiro?
- Lições e prompt otimizado são texto gerado por LLM a partir de mensagens de clientes. Por que passam por validação e, no caso do prompt, por um humano?
