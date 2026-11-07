"""Tabelas de domínio (dimensões pequenas) derivadas dos dicionários de dados
oficiais do SIM e do SINASC (Ministério da Saúde).

Estes dicionários alimentam as tabelas dim_* do banco e são a única fonte
de verdade para a decodificação dos códigos numéricos dos microdados.
"""
from __future__ import annotations

IGNORADO = "9"

# Raça/cor (SIM: RACACOR | SINASC: RACACORMAE) — classificação do IBGE.
RACA_COR = {
    "1": "Branca",
    "2": "Preta",
    "3": "Amarela",
    "4": "Parda",
    "5": "Indígena",
    "9": "Ignorada",
}
# Agrupamento IBGE usado em análises de desigualdade racial: Negra = Preta + Parda
RACA_COR_AGRUPADA = {
    "1": "Branca",
    "2": "Negra",
    "3": "Amarela",
    "4": "Negra",
    "5": "Indígena",
    "9": "Ignorada",
}

# Faixas etárias quinquenais (idade fértil 10–49, OMS / MS)
FAIXAS_ETARIAS = [
    # codigo, descricao, idade_min, idade_max, ordem
    ("10-14", "10 a 14 anos", 10, 14, 1),
    ("15-19", "15 a 19 anos", 15, 19, 2),
    ("20-24", "20 a 24 anos", 20, 24, 3),
    ("25-29", "25 a 29 anos", 25, 29, 4),
    ("30-34", "30 a 34 anos", 30, 34, 5),
    ("35-39", "35 a 39 anos", 35, 39, 6),
    ("40-44", "40 a 44 anos", 40, 44, 7),
    ("45-49", "45 a 49 anos", 45, 49, 8),
    ("50+", "50 anos ou mais", 50, 120, 9),
    ("<10", "Menos de 10 anos", 0, 9, 0),
    ("IGN", "Idade ignorada", None, None, 10),
]

# Escolaridade (SIM: ESC2010 | SINASC: ESCMAE2010)
ESCOLARIDADE = {
    "0": "Sem escolaridade",
    "1": "Fundamental I (1ª a 4ª série)",
    "2": "Fundamental II (5ª a 8ª série)",
    "3": "Médio",
    "4": "Superior incompleto",
    "5": "Superior completo",
    "9": "Ignorada",
}

SEXO = {"1": "Masculino", "2": "Feminino", "9": "Ignorado"}

# SIM — momento do óbito em relação à gestação (TPMORTEOCO)
MOMENTO_OBITO = {
    "1": "Na gravidez",
    "2": "No parto",
    "3": "No abortamento",
    "4": "Até 42 dias após o parto",
    "5": "De 43 dias a 1 ano após a gestação",
    "8": "Não ocorreu nestes períodos",
    "9": "Ignorado",
}

# SIM — local de ocorrência do óbito (LOCOCOR)
LOCAL_OCORRENCIA = {
    "1": "Hospital",
    "2": "Outro estabelecimento de saúde",
    "3": "Domicílio",
    "4": "Via pública",
    "5": "Outros",
    "6": "Aldeia indígena",
    "9": "Ignorado",
}

SIM_NAO = {"1": "Sim", "2": "Não", "9": "Ignorado"}

# Tipo de morte materna (classificação OMS / Guia de Vigilância do Óbito Materno)
TIPO_OBSTETRICO = {
    "direta": "Obstétrica direta",
    "indireta": "Obstétrica indireta",
    "nao_especificada": "Obstétrica não especificada",
    "tardia": "Materna tardia (43 dias a 1 ano)",
}

# Grupos de causa da morte materna
GRUPO_CAUSA_MATERNA = {
    "aborto": ("Gravidez que termina em aborto", "O00–O08"),
    "hipertensao": ("Síndromes hipertensivas (pré-eclâmpsia/eclâmpsia)", "O10–O16"),
    "hemorragia": ("Hemorragias (placenta prévia, descolamento, pós-parto)", "O20, O44–O46, O67, O72"),
    "infeccao": ("Infecção puerperal", "O85–O86"),
    "outras_diretas": ("Outras complicações obstétricas diretas", "demais O00–O92"),
    "indiretas": ("Doenças preexistentes agravadas pela gestação", "O24–O25, O98–O99"),
    "nao_especificada": ("Morte obstétrica de causa não especificada", "O95"),
    "outras_especiais": ("Causas fora do cap. XV com vínculo gestacional", "A34, F53, M83, D39.2, E23.0"),
    "tardia": ("Morte materna tardia / sequelas", "O96–O97"),
}

# Grupos gerais de causa para óbitos em idade reprodutiva (comparação por sexo)
GRUPO_CAUSA_GERAL = {
    "materna": "Morte materna (exceto tardia)",
    "covid19": "COVID-19",
    "agressao": "Agressões / homicídios (X85–Y09)",
    "suicidio": "Lesões autoprovocadas (X60–X84)",
    "transporte": "Acidentes de transporte (V01–V99)",
    "outras_externas": "Outras causas externas",
    "neoplasias": "Neoplasias (C00–D48)",
    "circulatorio": "Doenças do aparelho circulatório (I00–I99)",
    "infecciosas": "Doenças infecciosas e parasitárias (A00–B99)",
    "demais": "Demais causas",
}

REGIOES = {"N": "Norte", "NE": "Nordeste", "SE": "Sudeste", "S": "Sul", "CO": "Centro-Oeste"}

# Código IBGE da UF (2 dígitos) -> (sigla, nome, sigla da região)
UFS = {
    "11": ("RO", "Rondônia", "N"), "12": ("AC", "Acre", "N"), "13": ("AM", "Amazonas", "N"),
    "14": ("RR", "Roraima", "N"), "15": ("PA", "Pará", "N"), "16": ("AP", "Amapá", "N"),
    "17": ("TO", "Tocantins", "N"), "21": ("MA", "Maranhão", "NE"), "22": ("PI", "Piauí", "NE"),
    "23": ("CE", "Ceará", "NE"), "24": ("RN", "Rio Grande do Norte", "NE"),
    "25": ("PB", "Paraíba", "NE"), "26": ("PE", "Pernambuco", "NE"), "27": ("AL", "Alagoas", "NE"),
    "28": ("SE", "Sergipe", "NE"), "29": ("BA", "Bahia", "NE"), "31": ("MG", "Minas Gerais", "SE"),
    "32": ("ES", "Espírito Santo", "SE"), "33": ("RJ", "Rio de Janeiro", "SE"),
    "35": ("SP", "São Paulo", "SE"), "41": ("PR", "Paraná", "S"), "42": ("SC", "Santa Catarina", "S"),
    "43": ("RS", "Rio Grande do Sul", "S"), "50": ("MS", "Mato Grosso do Sul", "CO"),
    "51": ("MT", "Mato Grosso", "CO"), "52": ("GO", "Goiás", "CO"), "53": ("DF", "Distrito Federal", "CO"),
}
