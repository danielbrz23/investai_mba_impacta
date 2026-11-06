"""Configurações fixas do projeto. Segredos ficam no .env, nunca aqui."""

from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

# Banco local: um arquivo SQLite dentro da pasta do projeto (sem serviço externo).
CAMINHO_DB = RAIZ / "dados" / "investai_meta.db"

MODELO_LLM = "gemini-3.5-flash-lite"
MODELO_EMBEDDING = "models/gemini-embedding-001"
DIMS_EMBEDDING = 3072  # vetor do gemini-embedding-001; SQLite não limita o tamanho

# Chunking do guia: cada seção "###" é cortada em pedaços de até CHUNK_TAMANHO caracteres.
CHUNK_TAMANHO = 800
CHUNK_SOBREPOSICAO = 100

# Cache das APIs públicas. Os dados mudam pouco ao longo do dia, então 6 horas basta.
CACHE_TTL_SEGUNDOS = 6 * 60 * 60
TIMEOUT_HTTP_SEGUNDOS = 20

# Séries do Banco Central (SGS). Chave = nome usado no guia; valor = código da série.
SERIES_BCB = {
    "selic": 432,        # Selic meta, % ao ano
    "cdi": 4389,         # CDI anualizado, % ao ano
    "ipca_12m": 13522,   # IPCA acumulado em 12 meses, %
    "ipca_mes": 433,     # IPCA mensal, %
    "dolar": 1,          # dólar comercial, venda (PTAX)
    "poupanca": 195,     # rendimento mensal da poupança, %
}

BCB_SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados/ultimos/{n}?formato=json"
BCB_FOCUS_URL = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoAnuais"
TESOURO_CSV_URL = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/"
    "resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv"
)
BRAPI_URL = "https://brapi.dev/api/quote/{ticker}"

# --- Agente -------------------------------------------------------------------------
MAX_ITER = 6              # voltas máximas do loop ReAct (ferramentas) por mensagem
RECURSION_LIMIT = 40      # trava final do LangGraph (a metacognição adiciona nós ao loop)
MAX_CHARS_ENTRADA = 2000  # mensagens maiores que isso são recusadas (evita "encher" o contexto)
USAR_JUIZ_LLM = True      # liga os juízes LLM dos guardrails (as regras determinísticas ficam sempre ligadas)

# Namespaces do store
NS_CONHECIMENTO = ("conhecimento", "investimentos")
NS_CARTOES = ("catalogo", "produtos")

# Tickers que a ferramenta de cotação aceita (os que aparecem no guia, mais alguns exemplos de ações e FIIs)
TICKERS_PERMITIDOS = {"BOVA11", "IVVB11", "HASH11", "PETR4", "VALE3", "ITUB4", "MXRF11", "HGLG11"}

# Risco máximo (escala 1-5 dos produtos) aceito por perfil de suitability
RISCO_MAXIMO_POR_PERFIL = {"conservador": 2, "moderado": 3, "arrojado": 5}

# --- Metacognição -------------------------------------------------------------------
LIMIAR_CONFIANCA = 0.6          # abaixo disso o agente replaneja (e, no fim, avisa a incerteza)
MAX_REPLANEJAMENTOS = 1         # replanejar custa uma volta inteira de ferramentas: no máximo uma vez
MAX_REESCRITAS = 2              # tentativas de corrigir uma resposta reprovada antes de desistir
MAX_PERGUNTAS_POR_CONVERSA = 2  # o agente não pode ficar interrogando o cliente
LIMITE_LICAO_CHARS = 300

NS_LICOES = ("agente", "licoes")                    # Reflexion: erros que viraram regra
NS_PROMPT = ("agente", "prompt")                    # memória procedural: prompt otimizado
NS_PROMPT_HISTORICO = ("agente", "prompt_historico")
