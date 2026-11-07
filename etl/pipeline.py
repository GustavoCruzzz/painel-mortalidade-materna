"""Orquestrador do pipeline (batch). Uso:

    python -m etl.pipeline                          # 2019–2024, carga completa
    python -m etl.pipeline --anos 2023              # um ano
    python -m etl.pipeline --anos 2019-2024 --incremental   # só o que mudou na fonte
    python -m etl.pipeline --sem-banco              # só gera Parquet em data/processed

Fluxo por ano:  API CKAN -> download -> transformação em chunks (SIM e SINASC)
                -> Parquet (camada processed) -> PostgreSQL (COPY) -> OpenSearch.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

import pandas as pd

from . import config, extract, load, transform
from .dominios import UFS

log = logging.getLogger("etl")


def _intervalo_anos(texto: str) -> list[int]:
    anos: list[int] = []
    for parte in texto.split(","):
        if "-" in parte:
            ini, fim = parte.split("-")
            anos.extend(range(int(ini), int(fim) + 1))
        else:
            anos.append(int(parte))
    return sorted(set(anos))


def enriquecer_obitos(obitos: pd.DataFrame, cid10: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta descrições CID-10 (texto não estruturado) para a busca full-text."""
    if obitos.empty:
        return obitos
    desc = dict(zip(cid10["cid"], cid10["descricao"]))

    def descrever(cid: str) -> str:
        return desc.get(cid) or desc.get(cid[:3]) or cid

    import json
    textos = []
    for causa, cadeia in zip(obitos["causa_basica"], obitos["cadeia_causas"]):
        cids = [c for lista in json.loads(cadeia).values() for c in lista]
        termos = [descrever(causa)] + [descrever(c) for c in dict.fromkeys(cids) if c != causa]
        textos.append(" | ".join(termos))
    obitos = obitos.copy()
    obitos["causa_basica_descricao"] = obitos["causa_basica"].map(descrever)
    obitos["texto_causas"] = textos
    return obitos


def executar(args: argparse.Namespace) -> int:
    anos = _intervalo_anos(args.anos)
    log.info("Anos: %s | chunk=%s | amostra=%s", anos, config.TAMANHO_CHUNK, config.FRACAO_AMOSTRA)

    municipios = extract.carregar_municipios()
    cid10 = extract.carregar_cid10()
    cod_mun, cod_ufs = set(municipios["cod_municipio"]), set(UFS)

    engine = None
    if not args.sem_banco:
        engine = load.criar_engine()
        load.executar_arquivo_sql(engine, "schema.sql")
        load.carregar_dimensoes(engine, municipios, cid10, anos,
                                anos_preliminares=set(anos) if args.aceitar_preliminar else set())

    anos_carregados: list[int] = []
    for ano in anos:
        inicio = datetime.now(timezone.utc)
        try:
            zip_sim, rec_sim = extract.baixar_microdados("sim", ano, args.aceitar_preliminar)
            zip_sn, rec_sn = extract.baixar_microdados("sinasc", ano, args.aceitar_preliminar)
        except LookupError as exc:
            log.warning("Ano %s ignorado: %s", ano, exc)
            continue

        if args.incremental and engine is not None:
            iguais = (load.ultima_versao_carregada(engine, "SIM", ano) == rec_sim.get("last_modified") and
                      load.ultima_versao_carregada(engine, "SINASC", ano) == rec_sn.get("last_modified"))
            if iguais:
                log.info("Ano %s sem alterações na fonte — pulando (modo incremental)", ano)
                continue

        try:
            obitos, obitos_mun, idade_rep, rel_sim = transform.processar_sim(zip_sim, ano, cod_mun, cod_ufs)
            nascimentos, rel_sn = transform.processar_sinasc(zip_sn, ano, cod_mun, cod_ufs)
            fato = transform.integrar_fato(nascimentos, obitos_mun)
            obitos = enriquecer_obitos(obitos, cid10)

            for nome, df in [("fato_saude_materna", fato), ("fato_obito_materno", obitos),
                             ("fato_obito_idade_reprodutiva", idade_rep)]:
                transform.salvar_parquet(df, nome, ano)
            for rel in (rel_sim, rel_sn):
                log.info("Qualidade %s", rel.to_dict())

            if engine is not None:
                load.carregar_fatos_ano(engine, ano, fato, obitos, idade_rep)
                load.registrar_execucao(engine, "SIM", ano, "sucesso", rel_sim.to_dict(), rec_sim, inicio)
                load.registrar_execucao(engine, "SINASC", ano, "sucesso", rel_sn.to_dict(), rec_sn, inicio)
            anos_carregados.append(ano)
        except Exception as exc:  # registra a falha e segue para o próximo ano
            log.exception("Falha no ano %s", ano)
            if engine is not None:
                load.registrar_execucao(engine, "PIPELINE", ano, "erro", {"erro": str(exc)}, None, inicio)
            if args.parar_no_erro:
                return 1

    if engine is not None:
        load.executar_arquivo_sql(engine, "views.sql")
        load.conceder_leitura(engine)
        load.verificar_tamanho(engine)
        if anos_carregados and not args.sem_opensearch:
            load.indexar_opensearch(engine, anos_carregados)
    log.info("Concluído. Anos processados: %s", anos_carregados)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ETL SIM + SINASC -> Aiven (PostgreSQL / OpenSearch)")
    p.add_argument("--anos", default=",".join(map(str, config.ANOS_PADRAO)),
                   help="Ex.: 2023 | 2019-2024 | 2019,2021")
    p.add_argument("--incremental", action="store_true",
                   help="Só reprocessa anos cujo recurso CKAN mudou desde a última carga")
    p.add_argument("--aceitar-preliminar", action="store_true", help="Inclui bases preliminares")
    p.add_argument("--sem-banco", action="store_true", help="Gera apenas os Parquet locais")
    p.add_argument("--sem-opensearch", action="store_true", help="Não indexa no OpenSearch")
    p.add_argument("--parar-no-erro", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        stream=sys.stdout)
    return executar(args)


if __name__ == "__main__":
    raise SystemExit(main())
