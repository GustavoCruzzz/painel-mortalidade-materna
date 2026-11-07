"""Etapa 2 — Ingestão: descoberta via API e download dos dados públicos.

Fontes (todas abertas, governamentais e brasileiras):
* API CKAN do Portal de Dados Abertos do SUS  -> metadados JSON (semi-estruturado)
  e links dos microdados CSV do SIM e do SINASC (estruturado).
* API de Localidades do IBGE                  -> municípios/UF/região (JSON).
* Tabela CID-10 do DATASUS                    -> descrições textuais das causas
  (texto livre, usado para busca full-text).
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

from . import config

log = logging.getLogger(__name__)

_SESSAO = requests.Session()
_SESSAO.headers["User-Agent"] = "painel-mortalidade-materna-etl/1.0 (projeto academico)"


# Arquivos de referência versionados no repositório (IBGE e CID-10). Usados quando não
# há cópia em data/raw: os servidores do governo podem recusar conexões de fora do Brasil
# (ex.: runners do GitHub Actions), e essas tabelas mudam raramente.
DIR_REFERENCIAS = Path(__file__).resolve().parent / "referencias"

# Repositório público dos arquivos do Portal de Dados Abertos do SUS (AWS S3, São Paulo).
# Usado como alternativa quando a API CKAN não responde.
S3_SUS = "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br"
S3_ARQUIVOS = {"sim": "SIM/csv/Mortalidade_Geral_{ano}_csv.zip", "sinasc": "SINASC/csv/SINASC_{ano}_csv.zip"}

CONECTAR_TIMEOUT = 10  # segundos para abrir a conexão: servidor inalcançável falha rápido


def _get(url: str, *, stream: bool = False, tentativas: int = 4, timeout: int = 60) -> requests.Response:
    """GET com retry exponencial (as APIs públicas oscilam com frequência)."""
    for i in range(1, tentativas + 1):
        try:
            r = _SESSAO.get(url, stream=stream, timeout=(CONECTAR_TIMEOUT, timeout))
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            if i == tentativas:
                raise
            espera = 2**i
            log.warning("Falha em %s (%s). Nova tentativa em %ss", url, exc, espera)
            time.sleep(espera)
    raise RuntimeError("inalcançável")


# ---------------------------------------------------------------------------
# API CKAN (metadados semi-estruturados)
# ---------------------------------------------------------------------------

_PACOTES: dict[str, dict] = {}       # um package_show por pacote em cada execução
_CKAN_FALHOU: list[Exception] = []   # depois da primeira falha, não insiste na API


def obter_pacote_ckan(nome_pacote: str) -> dict:
    """Consulta `package_show` e guarda o JSON bruto em data/raw/metadata/."""
    if nome_pacote in _PACOTES:
        return _PACOTES[nome_pacote]
    if _CKAN_FALHOU:
        raise _CKAN_FALHOU[0]
    url = f"{config.CKAN_API}/package_show?id={nome_pacote}"
    try:
        payload = _get(url, tentativas=3).json()
    except requests.RequestException as exc:
        _CKAN_FALHOU.append(exc)
        raise
    if not payload.get("success"):
        raise RuntimeError(f"CKAN retornou erro para {nome_pacote}: {payload.get('error')}")
    pacote = payload["result"]
    destino = config.DIR_RAW / "metadata" / f"{nome_pacote}.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(pacote, ensure_ascii=False, indent=2), encoding="utf-8")
    _PACOTES[nome_pacote] = pacote
    return pacote


def localizar_recurso(pacote: dict, ano: int, aceitar_preliminar: bool = False) -> dict:
    """Encontra o recurso CSV (zip) de um ano no pacote CKAN.

    Por padrão rejeita bases marcadas como "preliminar" (Veracidade: dados
    ainda sujeitos a investigação/reclassificação de óbitos).
    """
    candidatos = []
    for r in pacote.get("resources", []):
        url = (r.get("url") or "").lower()
        nome = (r.get("name") or "").lower()
        if str(r.get("format", "")).upper() != "CSV" or not url.endswith(f"_{ano}_csv.zip"):
            continue
        r = dict(r)
        r["preliminar"] = "preliminar" in nome
        candidatos.append(r)
    if not candidatos:
        raise LookupError(f"Ano {ano} não encontrado no pacote {pacote.get('name')}")
    recurso = candidatos[0]
    if recurso["preliminar"] and not aceitar_preliminar:
        raise LookupError(
            f"Base {pacote.get('name')} {ano} é preliminar; use --aceitar-preliminar para incluí-la"
        )
    return recurso


# ---------------------------------------------------------------------------
# Download dos microdados (streaming, sem carregar tudo em memória)
# ---------------------------------------------------------------------------

def baixar_arquivo(url: str, destino: Path, forcar: bool = False) -> Path:
    """Baixa em streaming. Pula o download se o arquivo local tiver o mesmo tamanho."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists() and not forcar:
        try:
            tamanho_remoto = int(_SESSAO.head(url, timeout=(CONECTAR_TIMEOUT, 30))
                                 .headers.get("Content-Length", -1))
        except requests.RequestException:
            tamanho_remoto = -1
        if tamanho_remoto in (-1, destino.stat().st_size):
            log.info("Usando cache local: %s", destino.name)
            return destino

    log.info("Baixando %s", url)
    tmp = destino.with_suffix(destino.suffix + ".part")
    with _get(url, stream=True, timeout=120) as r, open(tmp, "wb") as fh:
        for bloco in r.iter_content(chunk_size=8 * 1024 * 1024):
            fh.write(bloco)
    tmp.replace(destino)
    return destino


def sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for bloco in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def url_s3(sistema: str, ano: int) -> str:
    """URL direta do arquivo no repositório S3 do Portal de Dados Abertos do SUS."""
    return f"{S3_SUS}/{S3_ARQUIVOS[sistema].format(ano=ano)}"


def _recurso_s3(sistema: str, ano: int) -> dict:
    """Alternativa à API CKAN: metadados mínimos a partir do cabeçalho HTTP do arquivo no S3."""
    url = url_s3(sistema, ano)
    try:
        r = _SESSAO.head(url, timeout=(CONECTAR_TIMEOUT, 30))
    except requests.RequestException as exc:
        raise RuntimeError(f"Nem a API CKAN nem o S3 responderam para {sistema} {ano}: {exc}") from exc
    if r.status_code == 404:
        raise LookupError(f"Ano {ano} não encontrado no S3 para {sistema}")
    r.raise_for_status()
    return {"url": url, "format": "CSV", "origem_metadados": "s3",
            "last_modified": r.headers.get("Last-Modified"), "etag": r.headers.get("ETag"),
            # Sem a API não há como ler o rótulo "preliminar": só os anos padrão são aceitos
            "preliminar": None if ano in config.ANOS_PADRAO else True}


def localizar_microdados(sistema: str, ano: int, aceitar_preliminar: bool = False) -> dict:
    """Metadados do arquivo de um ano (sem baixar). Usa a API CKAN e, se ela não
    responder, o cabeçalho do arquivo no S3."""
    nome_pacote = config.CKAN_PACOTE_SIM if sistema == "sim" else config.CKAN_PACOTE_SINASC
    try:
        pacote = obter_pacote_ckan(nome_pacote)
    except requests.RequestException as exc:
        log.warning("API CKAN indisponível (%s); usando o arquivo direto no S3", exc.__class__.__name__)
        recurso = _recurso_s3(sistema, ano)
        if recurso["preliminar"] and not aceitar_preliminar:
            raise LookupError(f"Sem a API não é possível confirmar se {sistema} {ano} é preliminar")
    else:
        recurso = localizar_recurso(pacote, ano, aceitar_preliminar)
        recurso["origem_metadados"] = "ckan"
        recurso["pacote_metadata_modified"] = pacote.get("metadata_modified")
    recurso["pacote"] = nome_pacote
    return recurso


def baixar_recurso(sistema: str, recurso: dict) -> Path:
    """Baixa o arquivo descrito por `localizar_microdados` e acrescenta o SHA-256."""
    destino = config.DIR_RAW / sistema / Path(recurso["url"]).name
    baixar_arquivo(recurso["url"], destino)
    recurso["sha256"] = sha256(destino)
    return destino


def _referencia(cache: Path, versionado: Path, url: str, descompactar: bool = False) -> Path:
    """Cópia local em data/raw; senão, a versionada no repositório; senão, baixa."""
    if cache.exists():
        return cache
    cache.parent.mkdir(parents=True, exist_ok=True)
    if versionado.exists():
        log.info("Usando referência versionada: %s", versionado.name)
        dados = versionado.read_bytes()
        cache.write_bytes(gzip.decompress(dados) if descompactar else dados)
    else:
        cache.write_bytes(_get(url).content)
    return cache


# ---------------------------------------------------------------------------
# Dimensões auxiliares (IBGE e CID-10)
# ---------------------------------------------------------------------------

def carregar_municipios() -> pd.DataFrame:
    """API de Localidades do IBGE -> dimensão de municípios (código de 6 dígitos,
    padrão usado pelo SIM/SINASC)."""
    cache = _referencia(config.DIR_RAW / "ibge" / "municipios.json",
                        DIR_REFERENCIAS / "municipios_ibge.json.gz", config.IBGE_API_MUNICIPIOS,
                        descompactar=True)
    dados = json.loads(cache.read_text(encoding="utf-8"))
    df = pd.DataFrame(dados)
    return pd.DataFrame({
        "cod_municipio": df["municipio-id"].astype(str).str[:6],
        "cod_municipio_ibge7": df["municipio-id"].astype(str),
        "nome_municipio": df["municipio-nome"],
        "cod_uf": df["UF-id"].astype(str),
        "sigla_uf": df["UF-sigla"],
        "nome_uf": df["UF-nome"],
        "sigla_regiao": df["regiao-sigla"],
        "nome_regiao": df["regiao-nome"],
    }).drop_duplicates("cod_municipio")


def carregar_cid10() -> pd.DataFrame:
    """Tabela CID-10 (categorias de 3 e subcategorias de 4 caracteres)."""
    cache = _referencia(config.DIR_RAW / "cid10" / "CID10CSV.zip",
                        DIR_REFERENCIAS / "CID10CSV.zip", config.CID10_URL)
    with zipfile.ZipFile(cache) as z:
        sub = pd.read_csv(io.BytesIO(z.read("CID-10-SUBCATEGORIAS.CSV")), sep=";",
                          encoding="latin-1", dtype=str, usecols=["SUBCAT", "DESCRICAO"])
        cat = pd.read_csv(io.BytesIO(z.read("CID-10-CATEGORIAS.CSV")), sep=";",
                          encoding="latin-1", dtype=str, usecols=["CAT", "DESCRICAO"])
    sub.columns = cat.columns = ["cid", "descricao"]
    df = pd.concat([cat, sub], ignore_index=True)
    df["cid"] = df["cid"].str.strip().str.upper()
    df["descricao"] = df["descricao"].str.strip()
    # Códigos de uso emergencial (COVID-19) não constam da tabela de 2008
    extras = pd.DataFrame({"cid": ["U07", "U071", "U072"],
                           "descricao": ["COVID-19", "COVID-19, vírus identificado",
                                         "COVID-19, vírus não identificado"]})
    return pd.concat([df, extras]).drop_duplicates("cid").reset_index(drop=True)
