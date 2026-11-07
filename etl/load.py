"""Etapa 4 — Carga no Aiven for PostgreSQL (relacional) e Aiven for OpenSearch
(não relacional, opcional).

* PostgreSQL: COPY em CSV (muito mais rápido que INSERTs) dentro de uma
  transação por ano -> carga idempotente (DELETE do ano + COPY).
* OpenSearch: API _bulk com _id determinístico -> reprocessar não duplica.
"""
from __future__ import annotations

import io
import json
import logging
import re
from urllib.parse import urlsplit, urlunsplit

import pandas as pd
import requests
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from . import config
from .dominios import (ESCOLARIDADE, FAIXAS_ETARIAS, GRUPO_CAUSA_GERAL, GRUPO_CAUSA_MATERNA,
                       LOCAL_OCORRENCIA, MOMENTO_OBITO, RACA_COR, RACA_COR_AGRUPADA, REGIOES, SEXO,
                       SIM_NAO, TIPO_OBSTETRICO, UFS)

log = logging.getLogger(__name__)
SCHEMA = "saude_materna"


# ---------------------------------------------------------------------------
# Conexão e DDL
# ---------------------------------------------------------------------------

def criar_engine(url: str | None = None) -> Engine:
    url = url or config.DATABASE_URL
    if not url:
        raise RuntimeError("DATABASE_URL não definida (veja .env.example)")
    # Plano gratuito da Aiven: máx. 20 conexões -> pool pequeno
    return create_engine(config.normalizar_url_postgres(url), pool_size=2, max_overflow=0,
                         pool_pre_ping=True)


def executar_arquivo_sql(engine: Engine, nome_arquivo: str) -> None:
    sql = (config.DIR_SQL / nome_arquivo).read_text(encoding="utf-8")
    with engine.begin() as conn:
        conn.exec_driver_sql(sql)
    log.info("SQL aplicado: %s", nome_arquivo)


def conceder_leitura(engine: Engine, usuario: str = config.DASHBOARD_DB_USER) -> None:
    """Princípio do menor privilégio: o usuário do dashboard só tem SELECT."""
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", usuario):
        raise ValueError(f"Nome de usuário inválido: {usuario!r}")
    with engine.begin() as conn:
        existe = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :u"), {"u": usuario}).first()
        if not existe:
            log.warning("Usuário %s não existe (crie via Terraform); GRANT ignorado", usuario)
            return
        conn.exec_driver_sql(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {usuario}")
        conn.exec_driver_sql(f"GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO {usuario}")
        conn.exec_driver_sql(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} GRANT SELECT ON TABLES TO {usuario}")
    log.info("SELECT concedido a %s", usuario)


# ---------------------------------------------------------------------------
# COPY / UPSERT
# ---------------------------------------------------------------------------

def _copy_df(conn, tabela: str, df: pd.DataFrame) -> None:
    """COPY ... FROM STDIN (CSV) usando a conexão psycopg subjacente."""
    if df.empty:
        return
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False, na_rep="")
    colunas = ", ".join(df.columns)
    raw = conn.connection.dbapi_connection  # psycopg.Connection
    with raw.cursor() as cur:
        with cur.copy(f"COPY {SCHEMA}.{tabela} ({colunas}) FROM STDIN WITH (FORMAT csv)") as cp:
            cp.write(buf.getvalue())


def _upsert(conn, tabela: str, df: pd.DataFrame, pk: list[str]) -> None:
    """Carrega numa tabela temporária e faz INSERT ... ON CONFLICT DO UPDATE."""
    tmp = f"tmp_{tabela}"
    conn.exec_driver_sql(f"CREATE TEMP TABLE {tmp} (LIKE {SCHEMA}.{tabela} INCLUDING DEFAULTS) ON COMMIT DROP")
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False, na_rep="")
    raw = conn.connection.dbapi_connection
    with raw.cursor() as cur, cur.copy(f"COPY {tmp} ({', '.join(df.columns)}) FROM STDIN WITH (FORMAT csv)") as cp:
        cp.write(buf.getvalue())
    cols = ", ".join(df.columns)
    upd = ", ".join(f"{c} = EXCLUDED.{c}" for c in df.columns if c not in pk) or None
    acao = f"DO UPDATE SET {upd}" if upd else "DO NOTHING"
    conn.exec_driver_sql(
        f"INSERT INTO {SCHEMA}.{tabela} ({cols}) SELECT {cols} FROM {tmp} "
        f"ON CONFLICT ({', '.join(pk)}) {acao}")


# ---------------------------------------------------------------------------
# Dimensões
# ---------------------------------------------------------------------------

def _periodo(ano: int) -> str:
    return "pré-pandemia" if ano < 2020 else ("pandemia" if ano <= 2021 else "pós-pandemia")


def carregar_dimensoes(engine: Engine, municipios: pd.DataFrame, cid10: pd.DataFrame,
                       anos: list[int], anos_preliminares: set[int] | None = None) -> None:
    anos_preliminares = anos_preliminares or set()
    # Linha "município ignorado" por UF (destino da regra RN-08)
    ign = pd.DataFrame([
        {"cod_municipio": f"{cod}0000", "cod_municipio_ibge7": None,
         "nome_municipio": f"Município ignorado - {sig}", "cod_uf": cod, "sigla_uf": sig,
         "nome_uf": nome, "sigla_regiao": reg, "nome_regiao": REGIOES[reg]}
        for cod, (sig, nome, reg) in UFS.items()])
    loc = pd.concat([municipios.assign(municipio_ignorado=False),
                     ign.assign(municipio_ignorado=True)], ignore_index=True)

    dims = {
        "dim_tempo": (pd.DataFrame({"ano": anos, "periodo": [_periodo(a) for a in anos],
                                    "base_preliminar": [a in anos_preliminares for a in anos]}), ["ano"]),
        "dim_localidade": (loc, ["cod_municipio"]),
        "dim_raca_cor": (pd.DataFrame([{"cod_raca_cor": k, "descricao": v,
                                        "grupo_ibge": RACA_COR_AGRUPADA[k]} for k, v in RACA_COR.items()]),
                         ["cod_raca_cor"]),
        "dim_faixa_etaria": (pd.DataFrame(FAIXAS_ETARIAS, columns=["cod_faixa_etaria", "descricao",
                                                                   "idade_min", "idade_max", "ordem"])
                             .astype({"idade_min": "Int64", "idade_max": "Int64"}), ["cod_faixa_etaria"]),
        "dim_escolaridade": (pd.DataFrame(ESCOLARIDADE.items(), columns=["cod_escolaridade", "descricao"]),
                             ["cod_escolaridade"]),
        "dim_sexo": (pd.DataFrame(SEXO.items(), columns=["cod_sexo", "descricao"]), ["cod_sexo"]),
        "dim_tipo_obstetrico": (pd.DataFrame([{"tipo_obstetrico": k, "descricao": v, "entra_rmm": k != "tardia"}
                                              for k, v in TIPO_OBSTETRICO.items()]), ["tipo_obstetrico"]),
        "dim_grupo_causa_materna": (pd.DataFrame([{"grupo_causa": k, "descricao": d, "cids": c}
                                                  for k, (d, c) in GRUPO_CAUSA_MATERNA.items()]), ["grupo_causa"]),
        "dim_grupo_causa_geral": (pd.DataFrame(GRUPO_CAUSA_GERAL.items(),
                                               columns=["cod_grupo_causa", "descricao"]), ["cod_grupo_causa"]),
        "dim_dominio": (pd.DataFrame(
            [("momento_obito", k, v) for k, v in MOMENTO_OBITO.items()]
            + [("local_ocorrencia", k, v) for k, v in LOCAL_OCORRENCIA.items()]
            + [("sim_nao", k, v) for k, v in SIM_NAO.items()],
            columns=["dominio", "codigo", "descricao"]), ["dominio", "codigo"]),
        "dim_cid10": (cid10, ["cid"]),
    }
    with engine.begin() as conn:
        for tabela, (df, pk) in dims.items():
            _upsert(conn, tabela, df, pk)
            log.info("Dimensão %s: %s linhas", tabela, len(df))


# ---------------------------------------------------------------------------
# Fatos (idempotente por ano)
# ---------------------------------------------------------------------------

def carregar_fatos_ano(engine: Engine, ano: int, fato: pd.DataFrame, obitos: pd.DataFrame,
                       idade_reprodutiva: pd.DataFrame) -> None:
    with engine.begin() as conn:
        for tabela in ("fato_saude_materna", "fato_obito_materno", "fato_obito_idade_reprodutiva"):
            conn.execute(text(f"DELETE FROM {SCHEMA}.{tabela} WHERE ano = :a"), {"a": ano})
        _copy_df(conn, "fato_saude_materna", fato)
        _copy_df(conn, "fato_obito_materno", obitos)
        _copy_df(conn, "fato_obito_idade_reprodutiva", idade_reprodutiva)
    log.info("Ano %s carregado: fato=%s, óbitos=%s, idade_reprodutiva=%s",
             ano, len(fato), len(obitos), len(idade_reprodutiva))


def registrar_execucao(engine: Engine, sistema: str, ano: int, status: str,
                       relatorio: dict | None, fonte: dict | None, iniciado_em) -> None:
    with engine.begin() as conn:
        conn.execute(text(
            f"INSERT INTO {SCHEMA}.etl_execucao (iniciado_em, finalizado_em, sistema, ano, status, "
            "fracao_amostra, relatorio, fonte) VALUES (:ini, now(), :s, :a, :st, :f, "
            "CAST(:r AS jsonb), CAST(:fo AS jsonb))"),
            {"ini": iniciado_em, "s": sistema, "a": ano, "st": status, "f": config.FRACAO_AMOSTRA,
             "r": json.dumps(relatorio, ensure_ascii=False, default=str),
             "fo": json.dumps(fonte, ensure_ascii=False, default=str)})


def ultima_versao_carregada(engine: Engine, sistema: str, ano: int) -> str | None:
    """Usado no modo incremental: compara com o last_modified do recurso CKAN."""
    with engine.connect() as conn:
        return conn.execute(text(
            f"SELECT fonte ->> 'last_modified' FROM {SCHEMA}.etl_execucao "
            "WHERE sistema = :s AND ano = :a AND status = 'sucesso' AND fracao_amostra = 1 "
            "ORDER BY finalizado_em DESC LIMIT 1"), {"s": sistema, "a": ano}).scalar()


def verificar_tamanho(engine: Engine) -> int:
    """Volume: garante que o banco cabe no limite de 1 GB do plano gratuito."""
    with engine.connect() as conn:
        tamanho = conn.execute(text("SELECT pg_database_size(current_database())")).scalar()
        tabelas = conn.execute(text(
            "SELECT relname, pg_total_relation_size(c.oid) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :s AND c.relkind = 'r' ORDER BY 2 DESC"), {"s": SCHEMA}).all()
    for nome, bytes_ in tabelas:
        log.info("  %-32s %8.1f MB", nome, bytes_ / 1024**2)
    pct = tamanho / config.LIMITE_BANCO_BYTES
    log.info("Tamanho total do banco: %.1f MB (%.0f%% do limite free tier)", tamanho / 1024**2, pct * 100)
    if pct > config.ALERTA_PERCENTUAL_BANCO:
        log.warning("ATENÇÃO: banco acima de %.0f%% do limite de 1 GB!", config.ALERTA_PERCENTUAL_BANCO * 100)
    return tamanho


# ---------------------------------------------------------------------------
# OpenSearch (não relacional, documentos JSON + busca full-text)
# ---------------------------------------------------------------------------

MAPEAMENTO_OPENSEARCH = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {"properties": {
        "ano": {"type": "short"},
        "regiao": {"type": "keyword"}, "uf": {"type": "keyword"},
        "raca_cor": {"type": "keyword"}, "raca_cor_grupo": {"type": "keyword"},
        "faixa_etaria": {"type": "keyword"}, "escolaridade": {"type": "keyword"},
        "tipo_obstetrico": {"type": "keyword"}, "grupo_causa": {"type": "keyword"},
        "momento_obito": {"type": "keyword"}, "local_ocorrencia": {"type": "keyword"},
        "assistencia_medica": {"type": "keyword"}, "investigado": {"type": "boolean"},
        "causa_basica": {"type": "keyword"},
        "causa_basica_descricao": {"type": "text", "analyzer": "brazilian"},
        "texto_causas": {"type": "text", "analyzer": "brazilian"},
        "cadeia_causas": {"type": "object", "properties": {
            k: {"type": "keyword"} for k in ("a", "b", "c", "d", "ii")}},
    }},
}


def _os_base(url: str) -> tuple[str, tuple[str, str] | None]:
    """Separa usuário/senha da URI do Aiven (https://user:pass@host:port)."""
    p = urlsplit(url)
    auth = (p.username, p.password) if p.username else None
    netloc = p.hostname + (f":{p.port}" if p.port else "")
    return urlunsplit((p.scheme, netloc, "", "", "")), auth


def indexar_opensearch(engine: Engine, anos: list[int], url: str | None = None) -> int:
    url = url or config.OPENSEARCH_URL
    if not url:
        log.info("OPENSEARCH_URL não definida — indexação NoSQL ignorada (opcional)")
        return 0
    base, auth = _os_base(url)
    indice = config.OPENSEARCH_INDICE
    r = requests.head(f"{base}/{indice}", auth=auth, timeout=30)
    if r.status_code == 404:
        requests.put(f"{base}/{indice}", json=MAPEAMENTO_OPENSEARCH, auth=auth, timeout=60).raise_for_status()
        log.info("Índice %s criado", indice)

    with engine.connect() as conn:
        df = pd.read_sql(text(
            f"SELECT * FROM {SCHEMA}.vw_obito_materno_detalhado WHERE ano = ANY(:anos)"),
            conn, params={"anos": anos})
    total = 0
    for inicio in range(0, len(df), 1000):
        linhas = []
        for rec in df.iloc[inicio:inicio + 1000].to_dict("records"):
            linhas.append(json.dumps({"index": {"_index": indice, "_id": rec["id_obito"]}}))
            doc = {
                "ano": int(rec["ano"]), "regiao": rec["sigla_regiao"], "uf": rec["sigla_uf"],
                "raca_cor": rec["raca_cor"], "raca_cor_grupo": rec["raca_cor_grupo"],
                "faixa_etaria": rec["faixa_etaria"], "escolaridade": rec["escolaridade"],
                "tipo_obstetrico": rec["tipo_obstetrico"], "grupo_causa": rec["grupo_causa"],
                "momento_obito": rec["momento_obito"], "local_ocorrencia": rec["local_ocorrencia"],
                "assistencia_medica": rec["assistencia_medica"], "investigado": bool(rec["investigado"]),
                "causa_basica": rec["causa_basica"], "causa_basica_descricao": rec["causa_basica_descricao"],
                "texto_causas": rec["texto_causas"], "cadeia_causas": rec["cadeia_causas"],
            }
            linhas.append(json.dumps(doc, ensure_ascii=False))
        corpo = ("\n".join(linhas) + "\n").encode("utf-8")
        resp = requests.post(f"{base}/_bulk", data=corpo, auth=auth, timeout=120,
                             headers={"Content-Type": "application/x-ndjson"})
        resp.raise_for_status()
        if resp.json().get("errors"):
            raise RuntimeError("Erros na indexação bulk do OpenSearch")
        total += len(linhas) // 2
    log.info("OpenSearch: %s documentos indexados em %s", total, indice)
    return total
