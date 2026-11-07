"""Exporta a base tratada (versão armazenada no PostgreSQL) para `dados_tratados/`.

Permite que qualquer pessoa confira o resultado do tratamento sem acesso ao banco:

* fatos     -> Parquet (formato colunar, compactado) + amostra CSV de 1.000 linhas
* dimensões -> CSV (pequenas, legíveis em qualquer editor)
* controle  -> JSON com a versão (URL, data de publicação, SHA-256) de cada arquivo de origem
* MANIFESTO.json -> linhas, colunas e SHA-256 de cada arquivo exportado

Uso:  python -m etl.exportar_base_tratada
Lê DASHBOARD_DATABASE_URL (somente leitura) ou, na falta dela, DATABASE_URL.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from . import config

log = logging.getLogger("etl.exportar")

DESTINO = config.RAIZ_PROJETO / "dados_tratados"
SCHEMA = "saude_materna"

FATOS = ["fato_saude_materna", "fato_obito_materno", "fato_obito_idade_reprodutiva"]
DIMENSOES = [
    "dim_tempo", "dim_localidade", "dim_raca_cor", "dim_faixa_etaria", "dim_escolaridade",
    "dim_sexo", "dim_tipo_obstetrico", "dim_grupo_causa_materna", "dim_grupo_causa_geral",
    "dim_dominio", "dim_cid10",
]
# tsv_causas é um índice de busca gerado pelo banco a partir de texto_causas: não é exportado
COLUNAS_GERADAS = {"tsv_causas"}


def _sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _ler(conn, tabela: str) -> pd.DataFrame:
    colunas = [
        c for (c,) in conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :s AND table_name = :t ORDER BY ordinal_position"),
            {"s": SCHEMA, "t": tabela})
        if c not in COLUNAS_GERADAS
    ]
    df = pd.read_sql(text(f"SELECT {', '.join(colunas)} FROM {SCHEMA}.{tabela} ORDER BY 1"), conn)
    for c in df.columns:  # JSONB chega como dict/list: grava como texto JSON
        if df[c].map(lambda v: isinstance(v, (dict, list))).any():
            df[c] = df[c].map(lambda v: json.dumps(v, ensure_ascii=False) if v is not None else None)
    return df


def exportar() -> dict:
    url = os.getenv("DASHBOARD_DATABASE_URL") or config.DATABASE_URL
    if not url:
        raise SystemExit("Defina DASHBOARD_DATABASE_URL ou DATABASE_URL (.env)")
    engine = create_engine(config.normalizar_url_postgres(url))

    for sub in ("fatos", "amostras_csv", "dimensoes", "controle"):
        (DESTINO / sub).mkdir(parents=True, exist_ok=True)

    arquivos: list[Path] = []
    resumo: dict[str, dict] = {}
    with engine.connect() as conn:
        for t in FATOS:
            df = _ler(conn, t)
            p = DESTINO / "fatos" / f"{t}.parquet"
            df.to_parquet(p, index=False, compression="zstd")
            a = DESTINO / "amostras_csv" / f"{t}_amostra.csv"
            df.head(1000).to_csv(a, index=False, encoding="utf-8", lineterminator="\n")
            arquivos += [p, a]
            resumo[t] = {"linhas": len(df), "colunas": list(df.columns)}
            log.info("%s: %s linhas", t, f"{len(df):,}")
        for t in DIMENSOES:
            df = _ler(conn, t)
            p = DESTINO / "dimensoes" / f"{t}.csv"
            df.to_csv(p, index=False, encoding="utf-8", lineterminator="\n")
            arquivos.append(p)
            resumo[t] = {"linhas": len(df), "colunas": list(df.columns)}
        execucoes = conn.execute(text(
            f"SELECT sistema, ano, status, finalizado_em, fracao_amostra, relatorio, "
            f"fonte->>'url' AS url, fonte->>'last_modified' AS publicado_em, fonte->>'sha256' AS sha256 "
            f"FROM {SCHEMA}.etl_execucao ORDER BY sistema, ano")).mappings().all()
        p = DESTINO / "controle" / "versao_fontes_e_qualidade.json"
        p.write_text(json.dumps([dict(r) for r in execucoes], ensure_ascii=False, indent=2, default=str),
                     encoding="utf-8", newline="\n")
        arquivos.append(p)

    manifesto = {
        "descricao": "Base tratada do Painel de Mortalidade Materna (SIM + SINASC 2019-2024)",
        "origem": "Exportada do Aiven for PostgreSQL, esquema saude_materna",
        "tabelas": resumo,
        "arquivos": {str(f.relative_to(DESTINO)).replace("\\", "/"):
                     {"bytes": f.stat().st_size, "sha256": _sha256(f)} for f in arquivos},
    }
    (DESTINO / "MANIFESTO.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=2),
                                            encoding="utf-8", newline="\n")
    return manifesto


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    m = exportar()
    total = sum(v["bytes"] for v in m["arquivos"].values())
    log.info("Exportados %d arquivos (%.1f MB) em %s", len(m["arquivos"]), total / 1e6, DESTINO)
