"""Configuração central do pipeline ETL.

Todas as credenciais são lidas de variáveis de ambiente (arquivo .env local
ou Secrets do GitHub Actions). Nenhum segredo fica no código.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ_PROJETO / ".env")

# ---------------------------------------------------------------------------
# Diretórios locais (camadas raw -> processed). Ficam fora do Git (.gitignore)
# ---------------------------------------------------------------------------
DIR_DADOS = Path(os.getenv("ETL_DIR_DADOS", RAIZ_PROJETO / "data"))
DIR_RAW = DIR_DADOS / "raw"
DIR_PROCESSED = DIR_DADOS / "processed"
DIR_SQL = Path(__file__).resolve().parent / "sql"

# ---------------------------------------------------------------------------
# Fontes públicas oficiais
# ---------------------------------------------------------------------------
# API CKAN do Portal de Dados Abertos do SUS (antigo OpenDataSUS)
CKAN_API = os.getenv(
    "CKAN_API", "https://dadosabertos.saude.gov.br/api/ckan/api/3/action"
)
CKAN_PACOTE_SIM = "sim"
CKAN_PACOTE_SINASC = "sistema-de-informacao-sobre-nascidos-vivos-sinasc"

# API de Localidades do IBGE (municípios, UFs, regiões)
IBGE_API_MUNICIPIOS = (
    "https://servicodados.ibge.gov.br/api/v1/localidades/municipios?view=nivelado"
)

# Tabela CID-10 oficial (DATASUS) — descrições textuais das causas de óbito
CID10_URL = "http://www2.datasus.gov.br/cid10/V2008/downloads/CID10CSV.zip"

# ---------------------------------------------------------------------------
# Parâmetros de processamento
# ---------------------------------------------------------------------------
ANOS_PADRAO = [2019, 2020, 2021, 2022, 2023, 2024]
TAMANHO_CHUNK = int(os.getenv("ETL_CHUNK", "250000"))
# Amostragem controlada (1.0 = base completa). Usada apenas em desenvolvimento.
FRACAO_AMOSTRA = float(os.getenv("ETL_AMOSTRA", "1.0"))
SEMENTE_AMOSTRA = 42

# Limite de armazenamento do plano gratuito da Aiven (1 GB). O loader aborta
# se o banco ultrapassar este percentual do limite.
LIMITE_BANCO_BYTES = 1 * 1024**3
ALERTA_PERCENTUAL_BANCO = 0.80

# ---------------------------------------------------------------------------
# Credenciais (somente via ambiente)
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")  # URI do avnadmin (escrita)
DASHBOARD_DB_USER = os.getenv("DASHBOARD_DB_USER", "dashboard_leitor")
OPENSEARCH_URL = os.getenv("OPENSEARCH_URL")  # opcional
OPENSEARCH_INDICE = os.getenv("OPENSEARCH_INDICE", "obitos-maternos")


def normalizar_url_postgres(url: str) -> str:
    """Converte a URI do Aiven (postgres://) para o dialeto do SQLAlchemy."""
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url
