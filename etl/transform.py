"""Etapa 3 — Limpeza e tratamento (Data Wrangling) em lotes (Pandas chunking).

Os CSVs do SIM (~500 MB/ano) e do SINASC (~900 MB/ano) são lidos direto de
dentro do .zip, em blocos de `config.TAMANHO_CHUNK` linhas, sem nunca
descompactar o arquivo inteiro em disco ou em memória.

Cada bloco passa por:
  1. padronização dos nomes de colunas (RN-00a)
  2. deduplicação por hash de linha, entre blocos (Veracidade)
  3. amostragem controlada opcional (ETL_AMOSTRA < 1.0)
  4. conversão de tipos / normalização de códigos (RN-00b..e)
  5. validação referencial do município com o IBGE (RN-08)
  6. aplicação das regras de negócio (RN-01..07)
  7. agregação parcial — só os agregados ficam em memória

Minimização (LGPD): colunas quase-identificadoras (datas exatas, estabelecimento,
ocupação, naturalidade…) só existem em memória durante o cálculo do hash de
deduplicação e são descartadas no mesmo bloco. Nada disso é persistido.
"""
from __future__ import annotations

import json
import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import config
from . import regras_negocio as rn
from .dominios import ESCOLARIDADE, LOCAL_OCORRENCIA, MOMENTO_OBITO, RACA_COR, SEXO, SIM_NAO

log = logging.getLogger(__name__)

CHAVES_FATO = ["ano", "cod_municipio", "cod_raca_cor", "cod_faixa_etaria"]


# ---------------------------------------------------------------------------
# Infraestrutura de leitura
# ---------------------------------------------------------------------------

class DeduplicadorHash:
    """Remove linhas duplicadas entre blocos usando hash 64-bit de todas as colunas
    (exceto o contador sequencial do arquivo)."""

    def __init__(self) -> None:
        self._vistos = np.empty(0, dtype=np.uint64)

    def filtrar(self, df: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
        colunas = [c for c in df.columns if c != "contador"]
        h = pd.util.hash_pandas_object(df[colunas], index=False).to_numpy()
        dup_interno = pd.Series(h).duplicated().to_numpy()
        dup_externo = np.isin(h, self._vistos)
        manter = ~(dup_interno | dup_externo)
        self._vistos = np.concatenate([self._vistos, h[manter]])
        return df.loc[manter], h[manter]


def ler_csv_zip_em_chunks(caminho_zip: Path):
    """Gera DataFrames (texto) a partir do CSV dentro do zip, em blocos."""
    with zipfile.ZipFile(caminho_zip) as z:
        nome = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        with z.open(nome) as fh:
            leitor = pd.read_csv(
                fh, sep=";", dtype=str, chunksize=config.TAMANHO_CHUNK,
                encoding="latin-1", keep_default_na=False, na_values=[""],
            )
            for i, bloco in enumerate(leitor):
                yield i, rn.padronizar_nomes_colunas(bloco)


@dataclass
class RelatorioQualidade:
    """Contadores de Veracidade gravados em etl_execucao (JSONB)."""
    sistema: str
    ano: int
    contadores: dict = field(default_factory=dict)

    def soma(self, chave: str, valor: int) -> None:
        self.contadores[chave] = int(self.contadores.get(chave, 0) + int(valor))

    def to_dict(self) -> dict:
        return {"sistema": self.sistema, "ano": self.ano, **self.contadores}


def _amostrar(df: pd.DataFrame, i: int) -> pd.DataFrame:
    if config.FRACAO_AMOSTRA >= 1.0:
        return df
    return df.sample(frac=config.FRACAO_AMOSTRA, random_state=config.SEMENTE_AMOSTRA + i)


def _texto(df: pd.DataFrame, colunas: list[str]) -> pd.DataFrame:
    """Garante que as colunas existem (layouts mudam entre anos) e não têm nulos."""
    for c in colunas:
        if c not in df:
            df[c] = ""
    return df[colunas].fillna("").astype("string").copy()


# ---------------------------------------------------------------------------
# SIM — Sistema de Informação sobre Mortalidade
# ---------------------------------------------------------------------------

COLUNAS_SIM = [
    "tipobito", "dtobito", "idade", "sexo", "racacor", "esc2010", "codmunres", "lococor",
    "obitograv", "obitopuerp", "tpmorteoco", "assistmed", "necropsia", "fonteinv",
    "linhaa", "linhab", "linhac", "linhad", "linhaii", "causabas",
]


def processar_sim(caminho_zip: Path, ano: int, municipios: set[str], ufs: set[str]):
    """Retorna (obitos_maternos_registro, agregado_municipal, agregado_idade_reprodutiva, relatorio)."""
    rel = RelatorioQualidade("SIM", ano)
    dedup = DeduplicadorHash()
    registros, agg_mun, agg_rep = [], [], []

    for i, bruto in ler_csv_zip_em_chunks(caminho_zip):
        rel.soma("linhas_lidas", len(bruto))
        bloco, hashes = dedup.filtrar(bruto)
        rel.soma("duplicadas_removidas", len(bruto) - len(bloco))
        hashes = pd.Series(hashes, index=bloco.index)
        bloco = _amostrar(bloco, i)
        df = _texto(bloco, COLUNAS_SIM)  # minimização: demais colunas descartadas aqui
        df["_hash"] = hashes.loc[df.index].to_numpy()
        del bruto, bloco

        # Óbitos fetais não entram no escopo (definição de morte materna é de óbito não fetal)
        fetal = df["tipobito"] != "2"
        rel.soma("obitos_fetais_excluidos", fetal.sum())
        df = df.loc[~fetal].copy()

        rel.soma("data_divergente_do_ano", (rn.ano_da_data(df["dtobito"]) != ano).fillna(True).sum())
        df["ano"] = ano  # ano de registro do arquivo (padrão das estatísticas oficiais)
        df["sexo"] = rn.normalizar_codigo(df["sexo"], ["1", "2"])
        df["cod_raca_cor"] = rn.normalizar_codigo(df["racacor"], RACA_COR)
        df["cod_escolaridade"] = rn.normalizar_codigo(df["esc2010"], ESCOLARIDADE)
        idade = rn.idade_sim_em_anos(df["idade"])
        df["cod_faixa_etaria"] = rn.faixa_etaria(idade)
        for c, dic in [("lococor", LOCAL_OCORRENCIA), ("tpmorteoco", MOMENTO_OBITO),
                       ("assistmed", SIM_NAO), ("necropsia", SIM_NAO)]:
            df[c] = rn.normalizar_codigo(df[c], dic)

        df["cod_municipio"] = rn.validar_municipio(df["codmunres"], municipios, ufs)
        rel.soma("municipio_reatribuido_uf_ignorado",
                 (df["cod_municipio"].notna() & ~df["codmunres"].str[:6].isin(municipios)).sum())
        invalido = df["cod_municipio"].isna()
        rel.soma("residencia_exterior_ou_invalida_descartada", invalido.sum())
        df = df.loc[~invalido].copy()

        classif = rn.classificar_morte_materna(df)
        df["tipo_obstetrico"], df["grupo_causa"] = classif["tipo_obstetrico"], classif["grupo_causa"]

        # --- (a) registro individual anonimizado de cada morte materna ----------
        mat = df.loc[df["tipo_obstetrico"].notna()].copy()
        if len(mat):
            mat["cadeia_causas"] = rn.cadeia_de_causas(mat).map(json.dumps)
            registros.append(pd.DataFrame({
                "id_obito": [f"{ano}-{h:016x}" for h in mat["_hash"].to_numpy(dtype=np.uint64)],
                "ano": ano,
                "cod_uf": mat["cod_municipio"].str[:2],  # generalização LGPD: só UF
                "cod_raca_cor": mat["cod_raca_cor"],
                "cod_faixa_etaria": mat["cod_faixa_etaria"],
                "cod_escolaridade": mat["cod_escolaridade"],
                "causa_basica": mat["causabas"].str.upper().str.strip(),
                "tipo_obstetrico": mat["tipo_obstetrico"],
                "grupo_causa": mat["grupo_causa"],
                "cod_momento_obito": mat["tpmorteoco"],
                "cod_local_ocorrencia": mat["lococor"],
                "cod_assistencia_medica": mat["assistmed"],
                "cod_necropsia": mat["necropsia"],
                "investigado": mat["fonteinv"].isin(list("12345678")),
                "cadeia_causas": mat["cadeia_causas"],
            }))

            # --- (b) agregado municipal para a RMM ------------------------------
            flags = rn.flags_obito(mat, mat["tipo_obstetrico"])
            agg_mun.append(pd.concat([mat[CHAVES_FATO], flags], axis=1)
                           .groupby(CHAVES_FATO, observed=True).sum().reset_index())

        # --- (c) óbitos em idade reprodutiva (10–49) por sexo — eixo de gênero ---
        rep = df.loc[df["sexo"].isin(["1", "2"]) &
                     df["cod_faixa_etaria"].isin(["10-14", "15-19", "20-24", "25-29",
                                                  "30-34", "35-39", "40-44", "45-49"])].copy()
        rep["cod_uf"] = rep["cod_municipio"].str[:2]
        rep["cod_grupo_causa"] = rn.grupo_causa_geral(rep["causabas"], rep["tipo_obstetrico"])
        rep["n_obitos"] = 1
        rep["n_gestante_puerpera"] = ((rep["sexo"] == "2") &
                                      (rep["obitograv"].eq("1") | rep["obitopuerp"].isin(["1", "2"]))
                                      ).astype("int32")
        chaves_rep = ["ano", "cod_uf", "sexo", "cod_raca_cor", "cod_faixa_etaria", "cod_grupo_causa"]
        agg_rep.append(rep.groupby(chaves_rep, observed=True)[["n_obitos", "n_gestante_puerpera"]]
                       .sum().reset_index())
        log.info("SIM %s · bloco %s processado (%s óbitos maternos acumulados)",
                 ano, i, sum(len(r) for r in registros))

    obitos = pd.concat(registros, ignore_index=True) if registros else pd.DataFrame()
    mun = (pd.concat(agg_mun).groupby(CHAVES_FATO).sum().reset_index()
           if agg_mun else pd.DataFrame(columns=CHAVES_FATO))
    rep = (pd.concat(agg_rep).groupby(["ano", "cod_uf", "sexo", "cod_raca_cor", "cod_faixa_etaria",
                                       "cod_grupo_causa"]).sum().reset_index())
    rep = rep.rename(columns={"sexo": "cod_sexo"})

    rel.soma("obitos_maternos_rmm", int(mun["obitos_maternos"].sum()) if len(mun) else 0)
    rel.soma("obitos_maternos_tardios", int(mun["obitos_maternos_tardios"].sum()) if len(mun) else 0)
    if len(obitos):
        rel.soma("obitos_maternos_raca_ignorada", (obitos["cod_raca_cor"] == "9").sum())
    return obitos, mun, rep, rel


# ---------------------------------------------------------------------------
# SINASC — Sistema de Informação sobre Nascidos Vivos
# ---------------------------------------------------------------------------

COLUNAS_SINASC = [
    "codmunres", "locnasc", "idademae", "racacormae", "parto", "consultas", "mesprenat",
    "stcesparto", "tprobson", "kotelchuck", "apgar5", "peso", "semagestac", "gestacao", "dtnasc",
]


def processar_sinasc(caminho_zip: Path, ano: int, municipios: set[str], ufs: set[str]):
    """Retorna (agregado_municipal_nascimentos, relatorio)."""
    rel = RelatorioQualidade("SINASC", ano)
    dedup = DeduplicadorHash()
    parciais = []

    for i, bruto in ler_csv_zip_em_chunks(caminho_zip):
        rel.soma("linhas_lidas", len(bruto))
        bloco, _ = dedup.filtrar(bruto)
        rel.soma("duplicadas_removidas", len(bruto) - len(bloco))
        df = _texto(_amostrar(bloco, i), COLUNAS_SINASC)
        del bruto, bloco

        rel.soma("data_divergente_do_ano", (rn.ano_da_data(df["dtnasc"]) != ano).fillna(True).sum())
        df["ano"] = ano
        df["cod_raca_cor"] = rn.normalizar_codigo(df["racacormae"], RACA_COR)
        df["cod_faixa_etaria"] = rn.faixa_etaria(rn.para_inteiro(df["idademae"], 8, 70))
        rel.soma("raca_mae_ignorada", (df["cod_raca_cor"] == "9").sum())
        rel.soma("idade_mae_ignorada", (df["cod_faixa_etaria"] == "IGN").sum())

        df["cod_municipio"] = rn.validar_municipio(df["codmunres"], municipios, ufs)
        rel.soma("municipio_reatribuido_uf_ignorado",
                 (df["cod_municipio"].notna() & ~df["codmunres"].str[:6].isin(municipios)).sum())
        invalido = df["cod_municipio"].isna()
        rel.soma("residencia_exterior_ou_invalida_descartada", invalido.sum())
        df = df.loc[~invalido].copy()

        ind = rn.indicadores_sinasc(df)
        parciais.append(pd.concat([df[CHAVES_FATO], ind], axis=1)
                        .groupby(CHAVES_FATO, observed=True).sum().reset_index())
        log.info("SINASC %s · bloco %s processado", ano, i)

    agg = pd.concat(parciais).groupby(CHAVES_FATO).sum().reset_index()
    rel.soma("nascidos_vivos", int(agg["nascidos_vivos"].sum()))
    return agg, rel


# ---------------------------------------------------------------------------
# Integração SIM x SINASC (numerador e denominador da RMM na mesma tabela fato)
# ---------------------------------------------------------------------------

def integrar_fato(nascimentos: pd.DataFrame, obitos_mun: pd.DataFrame) -> pd.DataFrame:
    """Outer join pelas chaves da fato; células sem evento recebem zero."""
    fato = nascimentos.merge(obitos_mun, on=CHAVES_FATO, how="outer")
    medidas = [c for c in fato.columns if c not in CHAVES_FATO]
    fato[medidas] = fato[medidas].fillna(0).astype("int32")
    fato["ano"] = fato["ano"].astype("int16")
    return fato.sort_values(CHAVES_FATO).reset_index(drop=True)


def salvar_parquet(df: pd.DataFrame, tabela: str, ano: int) -> Path:
    destino = config.DIR_PROCESSED / tabela / f"ano={ano}.parquet"
    destino.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(destino, index=False)
    return destino
