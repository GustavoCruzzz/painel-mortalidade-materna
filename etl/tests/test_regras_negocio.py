"""Testes das regras de negócio (rodam no CI: `pytest etl/tests`)."""
import pandas as pd
import pytest

from etl import regras_negocio as rn


def _obito(causa, tipobito="2", sexo="2", grav="", puerp="", **kw):
    base = {"causabas": causa, "tipobito": tipobito, "sexo": sexo, "obitograv": grav, "obitopuerp": puerp,
            "assistmed": kw.get("assistmed", "1"), "lococor": kw.get("lococor", "1"),
            "fonteinv": kw.get("fonteinv", "")}
    return base


def _classificar(*registros):
    df = pd.DataFrame(list(registros)).astype("string")
    return rn.classificar_morte_materna(df)


@pytest.mark.parametrize("causa,tipo,grupo", [
    ("O149", "direta", "hipertensao"),
    ("O150", "direta", "hipertensao"),
    ("O720", "direta", "hemorragia"),
    ("O85", "direta", "infeccao"),
    ("O060", "direta", "aborto"),
    ("O881", "direta", "outras_diretas"),
    ("O995", "indireta", "indiretas"),
    ("O985", "indireta", "indiretas"),
    ("O100", "indireta", "hipertensao"),    # hipertensão preexistente: indireta, grupo hipertensão
    ("O240", "indireta", "indiretas"),
    ("O244", "direta", "outras_diretas"),   # diabetes gestacional é direta
    ("O95", "nao_especificada", "nao_especificada"),
    ("O969", "tardia", "tardia"),
    ("O97X", "tardia", "tardia"),
    ("A34", "direta", "outras_especiais"),
])
def test_classificacao_capitulo_xv(causa, tipo, grupo):
    r = _classificar(_obito(causa)).iloc[0]
    assert r["tipo_obstetrico"] == tipo
    assert r["grupo_causa"] == grupo


def test_causas_especiais_exigem_vinculo_gestacional():
    r = _classificar(_obito("F530", grav="2", puerp="3"), _obito("F530", puerp="1"),
                     _obito("D392", grav="1"), _obito("D391", grav="1"))
    assert pd.isna(r.loc[0, "tipo_obstetrico"])
    assert r.loc[1, "tipo_obstetrico"] == "direta"
    assert r.loc[2, "tipo_obstetrico"] == "direta"
    assert pd.isna(r.loc[3, "tipo_obstetrico"])  # D39.1 não é placenta


def test_exclui_obito_fetal_e_masculino_e_nao_obstetrico():
    r = _classificar(_obito("O149", tipobito="1"), _obito("O149", sexo="1"), _obito("I10"))
    assert r["tipo_obstetrico"].isna().all()


def test_rmm_nao_inclui_tardias():
    tipos = pd.Series(["direta", "indireta", "nao_especificada", "tardia", None], dtype="string")
    assert rn.e_morte_materna_rmm(tipos).tolist() == [True, True, True, False, False]


def test_idade_sim():
    s = pd.Series(["425", "501", "230", "", "499", "4XX"], dtype="string")
    assert rn.idade_sim_em_anos(s).tolist()[:3] == [25, 101, 0]
    assert pd.isna(rn.idade_sim_em_anos(s).iloc[3])


def test_faixa_etaria():
    idades = pd.Series([12, 19, 20, 49, 50, None], dtype="Int64")
    assert rn.faixa_etaria(idades).tolist() == ["10-14", "15-19", "20-24", "45-49", "50+", "IGN"]


def test_normalizar_codigo():
    s = pd.Series(["01", "4", "7", None, " 2 ", "0"], dtype="string")
    assert rn.normalizar_codigo(s, {"1", "2", "4"}).tolist() == ["1", "4", "9", "9", "2", "9"]
    assert rn.normalizar_codigo(pd.Series(["0", "00"]), {"0", "1"}).tolist() == ["0", "0"]


def test_validar_municipio():
    s = pd.Series(["355030", "359999", "000000", "990000"], dtype="string")
    out = rn.validar_municipio(s, {"355030"}, {"35"})
    assert out.iloc[0] == "355030"
    assert out.iloc[1] == "350000"
    assert out.iloc[2:].isna().all()


def test_cadeia_de_causas():
    df = pd.DataFrame({"linhaa": ["*O159"], "linhab": ["*O149*R571"], "linhac": [None],
                       "linhad": [""], "linhaii": ["*I10X"]})
    cadeia = rn.cadeia_de_causas(df).iloc[0]
    assert cadeia == {"a": ["O159"], "b": ["O149", "R571"], "c": [], "d": [], "ii": ["I10"]}


def test_indicadores_sinasc_denominadores_validos():
    df = pd.DataFrame({
        "parto": ["2", "1", "9"], "tprobson": ["01", "02", "11"], "stcesparto": ["2", "3", ""],
        "kotelchuck": ["2", "5", "9"], "consultas": ["3", "4", ""], "mesprenat": ["05", "02", "99"],
        "locnasc": ["1", "3", "5"], "apgar5": ["06", "09", ""], "semagestac": ["36", "", ""],
        "gestacao": ["", "5", ""], "peso": ["2400", "3300", "50"],
    }).astype("string").fillna("")
    ind = rn.indicadores_sinasc(df).sum()
    assert ind["nascidos_vivos"] == 3
    assert ind["partos_info_valida"] == 2 and ind["partos_cesareos"] == 1
    assert ind["robson1_total"] == 1 and ind["robson1_cesareas"] == 1
    assert ind["baixo_risco_total"] == 2 and ind["cesareas_eletivas_baixo_risco"] == 0
    assert ind["prenatal_classificado"] == 2 and ind["prenatal_inadequado"] == 1
    assert ind["inicio_prenatal_valido"] == 2 and ind["inicio_prenatal_tardio"] == 1
    assert ind["partos_fora_estabelecimento"] == 1
    assert ind["apgar5_valido"] == 2 and ind["apgar5_baixo"] == 1
    assert ind["gestacao_valida"] == 2 and ind["prematuros"] == 1
    assert ind["peso_valido"] == 2 and ind["baixo_peso"] == 1


def test_grupo_causa_geral():
    causas = pd.Series(["X954", "X700", "V234", "B342", "C509", "I219", "O149", "W19"], dtype="string")
    tipos = pd.Series([None, None, None, None, None, None, "direta", None], dtype="string")
    assert rn.grupo_causa_geral(causas, tipos).tolist() == [
        "agressao", "suicidio", "transporte", "covid19", "neoplasias", "circulatorio", "materna", "outras_externas"]
