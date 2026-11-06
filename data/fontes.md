# Fontes

O guia `guia_investimentos.md` foi escrito com base nas fontes abaixo. Os números que mudam (Selic, CDI, IPCA, taxas do Tesouro e cotações) não ficam fixos no texto: são lidos das APIs públicas na hora da ingestão.

| Fonte | Uso no projeto | Acesso |
|---|---|---|
| Banco Central do Brasil – SGS | Selic, CDI, IPCA, dólar e poupança (séries 432, 4389, 13522, 433, 1 e 195) | `api.bcb.gov.br`, sem chave |
| Banco Central do Brasil – Expectativas de Mercado (Focus) | Projeção de Selic e IPCA para o ano | `olinda.bcb.gov.br`, sem chave |
| Tesouro Nacional – Tesouro Transparente | Taxas e preços dos títulos do Tesouro Direto | CSV aberto no portal Tesouro Transparente |
| brapi.dev | Cotações e variação de ações, FIIs e ETFs da B3 | API pública, token opcional |
| Tesouro Direto | Regras dos títulos e tabela regressiva de IR | tesourodireto.com.br |
| B3 | Regras de negociação, ações, FIIs, ETFs e BDRs | b3.com.br |
| CVM | Suitability, regras de fundos e come-cotas | gov.br/cvm |
| ANBIMA | Classificação de fundos e boas práticas de distribuição | anbima.com.br |
| FGC | Limite de cobertura de R$ 250 mil por CPF e instituição | fgc.org.br |

Regra do projeto: o agente não pode citar um número que não veio de uma fonte acima. Se a API estiver fora, ele diz que o dado está indisponível.
