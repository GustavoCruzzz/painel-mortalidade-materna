"""Testes da ingestão que não dependem de rede."""
import gzip
import json

from etl import extract


def test_url_s3_segue_o_padrao_do_portal():
    assert extract.url_s3("sim", 2023).endswith("/SIM/csv/Mortalidade_Geral_2023_csv.zip")
    assert extract.url_s3("sinasc", 2023).endswith("/SINASC/csv/SINASC_2023_csv.zip")
    assert extract.url_s3("sim", 2023).startswith("https://s3.sa-east-1.amazonaws.com/")


def test_referencia_versionada_e_usada_sem_rede(tmp_path):
    versionado = tmp_path / "ref.json.gz"
    versionado.write_bytes(gzip.compress(json.dumps([{"a": 1}]).encode()))
    cache = tmp_path / "raw" / "ref.json"
    caminho = extract._referencia(cache, versionado, "http://url-invalida.local/", descompactar=True)
    assert json.loads(caminho.read_text()) == [{"a": 1}]


def test_referencias_do_repositorio_existem():
    assert (extract.DIR_REFERENCIAS / "municipios_ibge.json.gz").exists()
    assert (extract.DIR_REFERENCIAS / "CID10CSV.zip").exists()
