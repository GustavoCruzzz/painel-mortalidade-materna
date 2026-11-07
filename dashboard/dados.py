"""Camada de acesso a dados do dashboard.

Todas as agregações são executadas NO BANCO (PostgreSQL) com SQL parametrizado;
o Streamlit recebe apenas o resultado agregado. Nomes de colunas/dimensões vêm
de listas fechadas (whitelist) — nunca de texto digitado pelo usuário.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import pandas as pd
import requests
import streamlit as st
from sqlalchemy import create_engine, text

from metricas import COLUNAS_SOMA

S = "saude_materna"


def segredo(nome: str) -> str | None:
    """Lê de st.secrets (Streamlit Cloud) ou de variável de ambiente (.env local)."""
    try:
        if nome in st.secrets:
            return st.secrets[nome]
    except Exception:  # noqa: BLE001 — sem secrets.toml local
        pass
    return os.getenv(nome)


@st.cache_resource(show_spinner=False)
def engine():
    url = segredo("DASHBOARD_DATABASE_URL") or segredo("DATABASE_URL")
    if not url:
        st.error("Configure DASHBOARD_DATABASE_URL em .streamlit/secrets.toml ou no ambiente.")
        st.stop()
    for prefixo in ("postgres://", "postgresql://"):
        if url.startswith(prefixo):
            url = "postgresql+psycopg://" + url[len(prefixo):]
    # Aiven free tier: no máximo 20 conexões simultâneas
    return create_engine(url, pool_size=2, max_overflow=1, pool_pre_ping=True, pool_recycle=1800)


def _sql(query: str, params: dict | None = None) -> pd.DataFrame:
    with engine().connect() as conn:
        return pd.read_sql(text(query), conn, params=params or {})


# ---------------------------------------------------------------------------
# Filtros globais (filtros cruzados aplicados a todas as consultas)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Filtros:
    ano_ini: int
    ano_fim: int
    regioes: tuple[str, ...] = ()
    ufs: tuple[str, ...] = ()
    racas: tuple[str, ...] = ()
    faixas: tuple[str, ...] = ()
    sexos: tuple[str, ...] = ()
    agrupar_negras: bool = False

    def where(self, alias_loc: str = "l", alias_fato: str = "f", com_faixa: bool = True) -> tuple[str, dict]:
        cond = [f"{alias_fato}.ano BETWEEN :ano_ini AND :ano_fim"]
        p: dict = {"ano_ini": self.ano_ini, "ano_fim": self.ano_fim}
        if self.regioes:
            cond.append(f"{alias_loc}.sigla_regiao = ANY(:regioes)")
            p["regioes"] = list(self.regioes)
        if self.ufs:
            cond.append(f"{alias_loc}.sigla_uf = ANY(:ufs)")
            p["ufs"] = list(self.ufs)
        if self.racas:
            cond.append(f"{alias_fato}.cod_raca_cor = ANY(:racas)")
            p["racas"] = list(self.racas)
        if self.faixas and com_faixa:
            cond.append(f"{alias_fato}.cod_faixa_etaria = ANY(:faixas)")
            p["faixas"] = list(self.faixas)
        return " AND ".join(cond), p


def expr_raca(f: Filtros) -> str:
    return "r.grupo_ibge" if f.agrupar_negras else "r.descricao"


# Dimensões permitidas para GROUP BY na fato principal
def _dims(f: Filtros) -> dict[str, str]:
    return {
        "ano": "f.ano",
        "regiao": "l.nome_regiao",
        "sigla_regiao": "l.sigla_regiao",
        "uf": "l.sigla_uf",
        "municipio": "l.nome_municipio || ' (' || l.sigla_uf || ')'",
        "raca": expr_raca(f),
        "faixa": "fe.descricao",
        "faixa_ordem": "fe.ordem",
    }


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def opcoes() -> dict:
    loc = _sql(f"SELECT DISTINCT sigla_regiao, nome_regiao, sigla_uf, nome_uf FROM {S}.dim_localidade "
               "ORDER BY sigla_uf")
    anos = _sql(f"SELECT DISTINCT ano FROM {S}.fato_saude_materna ORDER BY ano")["ano"].tolist()
    racas = _sql(f"SELECT cod_raca_cor, descricao FROM {S}.dim_raca_cor ORDER BY cod_raca_cor")
    faixas = _sql(f"SELECT cod_faixa_etaria, descricao FROM {S}.dim_faixa_etaria WHERE ordem BETWEEN 1 AND 9 "
                  "ORDER BY ordem")
    return {"loc": loc, "anos": anos, "racas": racas, "faixas": faixas}


@st.cache_data(ttl=3600, show_spinner=False)
def agregar(f: Filtros, dims: tuple[str, ...]) -> pd.DataFrame:
    """SUM de todas as medidas da fato, agrupado pelas dimensões pedidas."""
    mapa = _dims(f)
    sel_dims = [f"{mapa[d]} AS {d}" for d in dims]
    somas = [f"SUM(f.{c})::bigint AS {c}" for c in COLUNAS_SOMA]
    where, p = f.where()
    q = (f"SELECT {', '.join(sel_dims + somas)} "
         f"FROM {S}.fato_saude_materna f "
         f"JOIN {S}.dim_localidade l USING (cod_municipio) "
         f"JOIN {S}.dim_raca_cor r USING (cod_raca_cor) "
         f"JOIN {S}.dim_faixa_etaria fe USING (cod_faixa_etaria) "
         f"WHERE {where}" + (f" GROUP BY {', '.join(mapa[d] for d in dims)}" if dims else ""))
    return _sql(q, p)


@st.cache_data(ttl=3600, show_spinner=False)
def obitos_maternos(f: Filtros) -> pd.DataFrame:
    """Registros anonimizados (já com rótulos) para treemap e drill-down por causa."""
    where, p = f.where(alias_loc="u", alias_fato="o")
    q = (f"SELECT o.id_obito, o.ano, u.sigla_regiao, u.sigla_uf, {expr_raca(f)} AS raca, "
         "fe.descricao AS faixa, fe.ordem AS faixa_ordem, e.descricao AS escolaridade, "
         "t.descricao AS tipo_obstetrico, t.entra_rmm, g.descricao AS grupo_causa, "
         "o.causa_basica, coalesce(o.causa_basica_descricao, o.causa_basica) AS causa_descricao, "
         "dm.descricao AS momento_obito, dl.descricao AS local_ocorrencia, "
         "da.descricao AS assistencia_medica, o.investigado "
         f"FROM {S}.fato_obito_materno o "
         f"JOIN {S}.vw_uf u USING (cod_uf) "
         f"JOIN {S}.dim_raca_cor r USING (cod_raca_cor) "
         f"JOIN {S}.dim_faixa_etaria fe USING (cod_faixa_etaria) "
         f"JOIN {S}.dim_escolaridade e USING (cod_escolaridade) "
         f"JOIN {S}.dim_tipo_obstetrico t USING (tipo_obstetrico) "
         f"JOIN {S}.dim_grupo_causa_materna g USING (grupo_causa) "
         f"LEFT JOIN {S}.dim_dominio dm ON dm.dominio='momento_obito' AND dm.codigo=o.cod_momento_obito "
         f"LEFT JOIN {S}.dim_dominio dl ON dl.dominio='local_ocorrencia' AND dl.codigo=o.cod_local_ocorrencia "
         f"LEFT JOIN {S}.dim_dominio da ON da.dominio='sim_nao' AND da.codigo=o.cod_assistencia_medica "
         f"WHERE {where}")
    return _sql(q, p)


@st.cache_data(ttl=3600, show_spinner=False)
def obitos_idade_reprodutiva(f: Filtros) -> pd.DataFrame:
    where, p = f.where(alias_loc="u", alias_fato="o")
    if f.sexos:
        where += " AND o.cod_sexo = ANY(:sexos)"
        p["sexos"] = list(f.sexos)
    q = (f"SELECT o.ano, s.descricao AS sexo, {expr_raca(f)} AS raca, fe.descricao AS faixa, "
         "fe.ordem AS faixa_ordem, g.descricao AS grupo_causa, o.cod_grupo_causa, "
         "SUM(o.n_obitos)::bigint AS n_obitos, SUM(o.n_gestante_puerpera)::bigint AS n_gestante_puerpera "
         f"FROM {S}.fato_obito_idade_reprodutiva o "
         f"JOIN {S}.vw_uf u USING (cod_uf) "
         f"JOIN {S}.dim_sexo s USING (cod_sexo) "
         f"JOIN {S}.dim_raca_cor r USING (cod_raca_cor) "
         f"JOIN {S}.dim_faixa_etaria fe USING (cod_faixa_etaria) "
         f"JOIN {S}.dim_grupo_causa_geral g USING (cod_grupo_causa) "
         f"WHERE {where} GROUP BY 1,2,3,4,5,6,7")
    return _sql(q, p)


@st.cache_data(ttl=600, show_spinner=False)
def qualidade() -> pd.DataFrame:
    return _sql(f"SELECT sistema, ano, finalizado_em, fracao_amostra, recurso, fonte_modificada_em, relatorio "
                f"FROM {S}.vw_qualidade_ultima_carga ORDER BY ano, sistema")


# ---------------------------------------------------------------------------
# Busca textual — OpenSearch (NoSQL) com fallback para full-text do PostgreSQL
# ---------------------------------------------------------------------------

def _sem_acento(t: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


@st.cache_data(ttl=600, show_spinner=False)
def buscar_causas(termo: str, f: Filtros, limite: int = 200) -> tuple[str, pd.DataFrame, pd.DataFrame]:
    """Retorna (motor, resultados, agregação por raça)."""
    url = segredo("OPENSEARCH_URL")
    if url:
        try:
            return ("OpenSearch",) + _buscar_opensearch(url, termo, f, limite)
        except requests.RequestException as exc:
            st.warning(f"OpenSearch indisponível ({exc.__class__.__name__}); usando PostgreSQL.")
    where, p = f.where(alias_loc="u", alias_fato="o")
    p.update({"q": _sem_acento(termo), "lim": limite})
    base = (f"FROM {S}.fato_obito_materno o JOIN {S}.vw_uf u USING (cod_uf) "
            f"JOIN {S}.dim_raca_cor r USING (cod_raca_cor) "
            f"WHERE {where} AND o.tsv_causas @@ plainto_tsquery('portuguese', :q)")
    res = _sql(f"SELECT o.ano, u.sigla_uf AS uf, {expr_raca(f)} AS raca, o.causa_basica, "
               f"o.causa_basica_descricao, o.texto_causas, "
               f"ts_rank(o.tsv_causas, plainto_tsquery('portuguese', :q)) AS relevancia {base} "
               f"ORDER BY relevancia DESC LIMIT :lim", p)
    agg = _sql(f"SELECT {expr_raca(f)} AS raca, COUNT(*) AS n {base} GROUP BY 1 ORDER BY 2 DESC", p)
    return "PostgreSQL full-text", res, agg


def _buscar_opensearch(url: str, termo: str, f: Filtros, limite: int):
    p = urlsplit(url)
    base = urlunsplit((p.scheme, f"{p.hostname}:{p.port}" if p.port else p.hostname, "", "", ""))
    auth = (p.username, p.password) if p.username else None
    indice = segredo("OPENSEARCH_INDICE") or "obitos-maternos"
    filtros = [{"range": {"ano": {"gte": f.ano_ini, "lte": f.ano_fim}}}]
    if f.ufs:
        filtros.append({"terms": {"uf": list(f.ufs)}})
    if f.regioes:
        filtros.append({"terms": {"regiao": list(f.regioes)}})
    campo_raca = "raca_cor_grupo" if f.agrupar_negras else "raca_cor"
    corpo = {
        "size": limite,
        "query": {"bool": {"must": [{"multi_match": {"query": termo, "fields": ["texto_causas",
                                                                                "causa_basica_descricao^2"]}}],
                           "filter": filtros}},
        "aggs": {"por_raca": {"terms": {"field": campo_raca, "size": 10}}},
    }
    r = requests.post(f"{base}/{indice}/_search", json=corpo, auth=auth, timeout=20)
    r.raise_for_status()
    js = r.json()
    res = pd.DataFrame([{**h["_source"], "relevancia": h["_score"]} for h in js["hits"]["hits"]])
    if not res.empty:
        res = res.rename(columns={campo_raca: "raca"})[["ano", "uf", "raca", "causa_basica",
                                                         "causa_basica_descricao", "texto_causas", "relevancia"]]
    agg = pd.DataFrame([{"raca": b["key"], "n": b["doc_count"]}
                        for b in js["aggregations"]["por_raca"]["buckets"]])
    return res, agg
