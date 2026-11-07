"""Regras de negócio do painel — funções vetorizadas (Pandas) e testáveis.

Cada função aqui implementa uma regra documentada no README (seção
"Regras de Negócio"). Elas recebem Series/DataFrames já padronizados
(colunas em minúsculas, valores como texto) e devolvem colunas derivadas.

Referências:
- Ministério da Saúde. Guia de Vigilância Epidemiológica do Óbito Materno (2009).
- OMS. CID-10, Capítulo XV e definição de morte materna (até 42 dias).
- OMS. Classificação de Robson para cesarianas (2015/2017).
- Kotelchuck (1994). Índice de adequação do pré-natal (APNCU).
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .dominios import ESCOLARIDADE, FAIXAS_ETARIAS, IGNORADO, LOCAL_OCORRENCIA, MOMENTO_OBITO, RACA_COR

# ===========================================================================
# RN-00 · Padronização / tipagem (Veracidade)
# ===========================================================================

def padronizar_nomes_colunas(df: pd.DataFrame) -> pd.DataFrame:
    """RN-00a: nomes de colunas em snake_case minúsculo, sem aspas/espaços.

    O SIM publica cabeçalhos em minúsculas e o SINASC em maiúsculas; esta
    regra unifica ambos.
    """
    novos = []
    for c in df.columns:
        c = str(c).strip().strip('"').strip().lower()
        c = re.sub(r"[^0-9a-z]+", "_", c).strip("_")
        novos.append(c)
    df.columns = novos
    return df


def normalizar_codigo(serie: pd.Series, validos, padrao: str = IGNORADO) -> pd.Series:
    """RN-00b: códigos categóricos fora do dicionário viram 'Ignorado' (9).

    Também remove zeros à esquerda espúrios ("01" -> "1") e espaços.
    """
    s = serie.astype("string").str.strip().str.lstrip("0")
    s = s.mask(s == "", "0")  # "0" / "00" legítimos (ex.: escolaridade 0)
    validos = set(validos)
    return s.where(s.isin(validos), padrao).fillna(padrao).astype("string")


def para_inteiro(serie: pd.Series, minimo: int, maximo: int) -> pd.Series:
    """RN-00c: converte texto -> inteiro anulável; valores fora de [min, max] viram nulo."""
    s = pd.to_numeric(serie, errors="coerce")
    s = s.where((s >= minimo) & (s <= maximo))
    return s.astype("Int64")


def ano_da_data(serie: pd.Series) -> pd.Series:
    """RN-00d: extrai o ano de datas no formato DDMMAAAA (SIM/SINASC)."""
    s = serie.astype("string").str.strip().str.zfill(8)
    return pd.to_numeric(s.str[4:8], errors="coerce").astype("Int64")


def idade_sim_em_anos(serie: pd.Series) -> pd.Series:
    """RN-00e: decodifica o campo IDADE do SIM.

    O 1º dígito é a unidade (0=min, 1=h, 2=dias, 3=meses, 4=anos, 5=100+ anos)
    e os dois seguintes a quantidade. Ex.: '425' -> 25 anos; '501' -> 101 anos.
    """
    s = serie.astype("string").str.strip()
    unidade = s.str[0]
    valor = pd.to_numeric(s.str[1:], errors="coerce")
    anos = pd.Series(np.nan, index=s.index)
    anos = anos.mask(unidade == "4", valor)
    anos = anos.mask(unidade == "5", valor + 100)
    anos = anos.mask(unidade.isin(["0", "1", "2", "3"]), 0)
    return anos.where(anos <= 120).astype("Int64")


def faixa_etaria(idade: pd.Series) -> pd.Series:
    """RN-01: enquadra a idade em anos nas faixas quinquenais da dimensão."""
    saida = pd.Series("IGN", index=idade.index, dtype="string")
    for codigo, _desc, minimo, maximo, _ordem in FAIXAS_ETARIAS:
        if minimo is None:
            continue
        saida = saida.mask(idade.between(minimo, maximo).fillna(False), codigo)
    return saida


# ===========================================================================
# RN-02 · Classificação da morte materna (SIM)
# ===========================================================================

_ESPECIAIS_3 = {"F53", "M83"}
_ESPECIAIS_4 = {"D392", "E230"}
_HEMORRAGIA = {"O20", "O44", "O45", "O46", "O67", "O72"}


def classificar_morte_materna(df: pd.DataFrame) -> pd.DataFrame:
    """RN-02: classifica cada óbito como morte materna e define tipo e grupo.

    Definição (OMS/MS): óbito de mulher durante a gestação ou até 42 dias após
    o seu término, por causa relacionada ou agravada pela gravidez.

    * Obstétrica direta  : O00–O92 (exceto as indiretas abaixo), mais
                           A34 (tétano obstétrico) e F53, M83, D39.2, E23.0
                           quando há vínculo gestacional declarado
                           (OBITOGRAV=1 ou OBITOPUERP=1).
    * Obstétrica indireta: O10, O24 (exceto O24.4), O25, O98, O99.
    * Não especificada   : O95.
    * Tardia             : O96–O97 (43 dias a 1 ano) — NÃO entra na RMM.

    Pré-condições: óbito não fetal (TIPOBITO=2) e sexo feminino (SEXO=2).

    Retorna DataFrame com colunas `tipo_obstetrico` e `grupo_causa`
    (nulos quando o óbito não é materno).
    """
    causa = df["causabas"].astype("string").str.strip().str.upper().fillna("")
    c3, c4 = causa.str[:3], causa.str[:4]
    col = lambda nome: df[nome].astype("string").fillna("")  # noqa: E731
    elegivel = col("tipobito").eq("2") & col("sexo").eq("2")
    vinculo = col("obitograv").eq("1") | col("obitopuerp").eq("1")

    cap_xv = c3.str.match(r"^O\d\d$")
    tardia = c3.isin(["O96", "O97"])
    indireta = c3.isin(["O10", "O25", "O98", "O99"]) | ((c3 == "O24") & (c4 != "O244"))
    nao_esp = c3 == "O95"
    especiais = (c3 == "A34") | ((c3.isin(_ESPECIAIS_3) | c4.isin(_ESPECIAIS_4)) & vinculo)
    direta = (cap_xv & ~tardia & ~indireta & ~nao_esp) | especiais

    tipo = np.select(
        [elegivel & tardia, elegivel & indireta, elegivel & nao_esp, elegivel & direta],
        ["tardia", "indireta", "nao_especificada", "direta"],
        default=None,
    )
    grupo = np.select(
        [
            tipo == "tardia",
            (tipo != None) & (c3 >= "O00") & (c3 <= "O08"),  # noqa: E711
            (tipo != None) & (c3 >= "O10") & (c3 <= "O16"),  # noqa: E711
            (tipo != None) & c3.isin(_HEMORRAGIA),  # noqa: E711
            (tipo != None) & c3.isin(["O85", "O86"]),  # noqa: E711
            tipo == "indireta",
            tipo == "nao_especificada",
            (tipo == "direta") & ~cap_xv,
            tipo == "direta",
        ],
        ["tardia", "aborto", "hipertensao", "hemorragia", "infeccao", "indiretas",
         "nao_especificada", "outras_especiais", "outras_diretas"],
        default=None,
    )
    return pd.DataFrame(
        {"tipo_obstetrico": pd.Series(tipo, index=df.index, dtype="string"),
         "grupo_causa": pd.Series(grupo, index=df.index, dtype="string")}
    )


def e_morte_materna_rmm(tipo_obstetrico: pd.Series) -> pd.Series:
    """RN-03: entra no numerador da RMM = direta + indireta + não especificada."""
    return tipo_obstetrico.isin(["direta", "indireta", "nao_especificada"]).fillna(False)


def grupo_causa_geral(causabas: pd.Series, tipo_obstetrico: pd.Series) -> pd.Series:
    """RN-04: agrupa a causa básica para a comparação por sexo (10–49 anos)."""
    c = causabas.astype("string").str.strip().str.upper().fillna("")
    c3, c4, l1 = c.str[:3], c.str[:4], c.str[:1]
    materna = e_morte_materna_rmm(tipo_obstetrico)
    grupo = np.select(
        [
            materna,
            c4.isin(["B342", "U071", "U072"]),
            (c3 >= "X85") & (c3 <= "Y09"),
            (c3 >= "X60") & (c3 <= "X84"),
            l1 == "V",
            l1.isin(["W", "X", "Y"]),
            (l1 == "C") | ((c3 >= "D00") & (c3 <= "D48")),
            l1 == "I",
            l1.isin(["A", "B"]),
        ],
        ["materna", "covid19", "agressao", "suicidio", "transporte", "outras_externas",
         "neoplasias", "circulatorio", "infecciosas"],
        default="demais",
    )
    return pd.Series(grupo, index=c.index, dtype="string")


def cadeia_de_causas(df: pd.DataFrame) -> pd.Series:
    """RN-05: transforma as linhas A–D e II da Declaração de Óbito
    (strings semi-estruturadas como '*O149*R571') em listas de CIDs.

    Resultado é um dicionário por óbito, gravado como JSONB no PostgreSQL e
    como objeto aninhado no OpenSearch.
    """
    linhas = {"a": "linhaa", "b": "linhab", "c": "linhac", "d": "linhad", "ii": "linhaii"}
    partes = {}
    for chave, col in linhas.items():
        s = df[col].astype("string").fillna("") if col in df else pd.Series("", index=df.index)
        partes[chave] = s.str.upper().str.findall(r"\*?([A-Z]\d{2}[0-9X]?)")
    return pd.Series(
        [{k: [x.rstrip("X") if len(x) == 4 and x.endswith("X") else x for x in partes[k][i]]
          for k in linhas} for i in df.index],
        index=df.index,
    )


# ===========================================================================
# RN-06 · Indicadores de assistência ao óbito (SIM)
# ===========================================================================

def flags_obito(df: pd.DataFrame, tipo_obstetrico: pd.Series) -> pd.DataFrame:
    """RN-06: contadores por óbito materno usados nas métricas agregadas."""
    materna = e_morte_materna_rmm(tipo_obstetrico)
    lococor = df["lococor"].fillna("9")
    fonteinv = df["fonteinv"].fillna("")
    return pd.DataFrame({
        "obitos_maternos": materna,
        "obitos_maternos_diretos": tipo_obstetrico.eq("direta").fillna(False),
        "obitos_maternos_indiretos": tipo_obstetrico.eq("indireta").fillna(False),
        "obitos_maternos_tardios": tipo_obstetrico.eq("tardia").fillna(False),
        # Desassistência: óbito materno sem assistência médica durante a doença
        "obitos_sem_assistencia": materna & df["assistmed"].eq("2").fillna(False),
        # Óbito materno fora de estabelecimento de saúde (domicílio/via pública/outros)
        "obitos_fora_estabelecimento": materna & lococor.isin(["3", "4", "5"]),
        # Qualidade: óbito materno investigado (FONTEINV 1–8)
        "obitos_investigados": materna & fonteinv.isin(list("12345678")),
    }).astype("int32")


# ===========================================================================
# RN-07 · Indicadores obstétricos / proxies de violência obstétrica (SINASC)
# ===========================================================================

def indicadores_sinasc(df: pd.DataFrame) -> pd.DataFrame:
    """RN-07: transforma cada nascimento em contadores (numeradores e
    denominadores válidos). Registros com informação ignorada saem apenas do
    denominador do indicador correspondente — nunca do total de nascidos vivos.
    """
    parto = df["parto"]
    robson = para_inteiro(df["tprobson"], 1, 10)
    kotel = df["kotelchuck"]
    consultas = df["consultas"]
    mes_pn = para_inteiro(df["mesprenat"], 1, 9)
    apgar5 = para_inteiro(df["apgar5"], 0, 10)
    semanas = para_inteiro(df["semagestac"], 20, 45)
    gestacao = df["gestacao"]
    peso = para_inteiro(df["peso"], 300, 6500)

    cesarea = parto.eq("2")
    baixo_risco = robson.between(1, 4).fillna(False)

    # Prematuridade: usa semanas exatas; na ausência, a faixa GESTACAO (1–4 = <37 sem.)
    prematuro_sem = semanas.lt(37)
    prematuro_faixa = gestacao.isin(["1", "2", "3", "4"])
    gest_valida = semanas.notna() | gestacao.isin(list("123456"))
    prematuro = prematuro_sem.fillna(False) | (semanas.isna() & prematuro_faixa)

    out = pd.DataFrame({
        "nascidos_vivos": 1,
        # Tipo de parto
        "partos_info_valida": parto.isin(["1", "2"]),
        "partos_cesareos": cesarea,
        # Robson (OMS): grupo 1 = nulípara, termo, cefálico, trabalho de parto espontâneo
        "robson_classificados": robson.notna(),
        "robson1_total": robson.eq(1).fillna(False),
        "robson1_cesareas": robson.eq(1).fillna(False) & cesarea,
        # Cesárea eletiva (antes do trabalho de parto) em gestação de baixo risco (Robson 1–4)
        "baixo_risco_total": baixo_risco,
        "cesareas_eletivas_baixo_risco": baixo_risco & cesarea & df["stcesparto"].eq("1"),
        # Pré-natal (Kotelchuck): 1 = não realizou, 2 = inadequado
        "prenatal_classificado": kotel.isin(list("12345")),
        "prenatal_inadequado": kotel.isin(["1", "2"]),
        # Menos de 7 consultas (CONSULTAS 1–3) — meta do MS é ≥ 7
        "consultas_info_valida": consultas.isin(list("1234")),
        "menos_7_consultas": consultas.isin(["1", "2", "3"]),
        # Início tardio do pré-natal (após o 3º mês)
        "inicio_prenatal_valido": mes_pn.notna(),
        "inicio_prenatal_tardio": mes_pn.gt(3).fillna(False),
        # Parto fora de estabelecimento de saúde (domicílio / outros)
        "local_info_valida": df["locnasc"].isin(list("12345")),
        "partos_fora_estabelecimento": df["locnasc"].isin(["3", "4"]),
        # Desfechos neonatais
        "apgar5_valido": apgar5.notna(),
        "apgar5_baixo": apgar5.lt(7).fillna(False),
        "gestacao_valida": gest_valida,
        "prematuros": prematuro & gest_valida,
        "peso_valido": peso.notna(),
        "baixo_peso": peso.lt(2500).fillna(False),
    })
    return out.fillna(False).astype("int32")


# ===========================================================================
# RN-08 · Localidade (Veracidade referencial)
# ===========================================================================

def validar_municipio(codigos: pd.Series, municipios_validos: set[str], ufs_validas: set[str]) -> pd.Series:
    """RN-08: valida o município de residência contra a API do IBGE.

    * código encontrado            -> mantém
    * código inexistente, UF válida -> 'UU0000' (município ignorado da UF)
    * UF inválida / exterior       -> nulo (registro descartado e contabilizado)
    """
    c = codigos.astype("string").str.strip().str[:6]
    uf = c.str[:2]
    ok = c.isin(municipios_validos)
    ign_uf = ~ok & uf.isin(ufs_validas)
    return c.where(ok, (uf + "0000").where(ign_uf))


# Rótulos usados no índice de busca (OpenSearch) e na tabela de óbitos
def rotulo(serie: pd.Series, dicionario: dict) -> pd.Series:
    return serie.map(dicionario).fillna(dicionario.get("9", "Ignorado"))


__all__ = [
    "padronizar_nomes_colunas", "normalizar_codigo", "para_inteiro", "ano_da_data",
    "idade_sim_em_anos", "faixa_etaria", "classificar_morte_materna", "e_morte_materna_rmm",
    "grupo_causa_geral", "cadeia_de_causas", "flags_obito", "indicadores_sinasc",
    "validar_municipio", "rotulo", "RACA_COR", "ESCOLARIDADE", "MOMENTO_OBITO", "LOCAL_OCORRENCIA",
]
