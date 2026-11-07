"""Catálogo de métricas do dashboard (espelha as Regras de Negócio do README).

Cada métrica = numerador / denominador x multiplicador, sempre calculada
DEPOIS da soma (razão de somas, nunca média de razões).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Metrica:
    rotulo: str
    numerador: str
    denominador: str | None
    multiplicador: float
    unidade: str
    descricao: str
    maior_e_pior: bool = True

    def calcular(self, df: pd.DataFrame) -> pd.Series:
        num = df[self.numerador].astype(float)
        if self.denominador is None:
            return num
        den = df[self.denominador].astype(float).replace(0, np.nan)
        return num / den * self.multiplicador

    def formatar(self, valor) -> str:
        if valor is None or pd.isna(valor):
            return "—"
        if self.denominador is None:
            return f"{valor:,.0f}".replace(",", ".")
        casas = 1 if self.multiplicador >= 100 else 2
        return f"{valor:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".") + self.unidade


METRICAS: dict[str, Metrica] = {
    "rmm": Metrica("Razão de Mortalidade Materna", "obitos_maternos", "nascidos_vivos", 100_000, "",
                   "Óbitos maternos (até 42 dias) por 100 mil nascidos vivos. Meta ODS 3.1 para o Brasil: 30."),
    "obitos_maternos": Metrica("Óbitos maternos (nº)", "obitos_maternos", None, 1, "",
                               "Mortes maternas diretas, indiretas e não especificadas."),
    "nascidos_vivos": Metrica("Nascidos vivos (nº)", "nascidos_vivos", None, 1, "",
                              "Total de nascidos vivos (SINASC)."),
    "pct_cesarea": Metrica("Taxa de cesárea", "partos_cesareos", "partos_info_valida", 100, "%",
                           "Cesáreas / partos com tipo informado. Referência OMS: 10–15%."),
    "pct_cesarea_robson1": Metrica("Cesárea no grupo 1 de Robson", "robson1_cesareas", "robson1_total", 100, "%",
                                   "Nulíparas, gestação única, cefálica, ≥37 sem., trabalho de parto espontâneo. "
                                   "Referência OMS: < 10%."),
    "pct_cesarea_eletiva": Metrica("Cesárea eletiva em baixo risco", "cesareas_eletivas_baixo_risco",
                                   "baixo_risco_total", 100, "%",
                                   "Cesárea realizada antes do início do trabalho de parto nos grupos 1–4 de Robson "
                                   "(proxy de intervenção potencialmente desnecessária)."),
    "pct_prenatal_inadequado": Metrica("Pré-natal inadequado (Kotelchuck)", "prenatal_inadequado",
                                       "prenatal_classificado", 100, "%",
                                       "Não realizou ou teve pré-natal inadequado pelo índice de Kotelchuck."),
    "pct_menos_7": Metrica("Menos de 7 consultas de pré-natal", "menos_7_consultas", "consultas_info_valida",
                           100, "%", "Recomendação do Ministério da Saúde: ≥ 7 consultas."),
    "pct_inicio_tardio": Metrica("Início tardio do pré-natal", "inicio_prenatal_tardio", "inicio_prenatal_valido",
                                 100, "%", "Primeira consulta após o 3º mês de gestação."),
    "pct_fora_estab": Metrica("Parto fora de estabelecimento de saúde", "partos_fora_estabelecimento",
                              "local_info_valida", 100, "%", "Partos em domicílio ou outros locais (exclui aldeias)."),
    "pct_apgar_baixo": Metrica("Apgar < 7 no 5º minuto", "apgar5_baixo", "apgar5_valido", 100, "%",
                               "Indicador de asfixia/sofrimento neonatal."),
    "pct_prematuro": Metrica("Prematuridade", "prematuros", "gestacao_valida", 100, "%", "Nascimentos < 37 semanas."),
    "pct_baixo_peso": Metrica("Baixo peso ao nascer", "baixo_peso", "peso_valido", 100, "%", "Peso < 2.500 g."),
    "pct_obito_sem_assist": Metrica("Óbitos maternos sem assistência médica", "obitos_sem_assistencia",
                                    "obitos_maternos", 100, "%", "Desassistência durante a doença que levou à morte."),
    "pct_obito_fora_estab": Metrica("Óbitos maternos fora de estab. de saúde", "obitos_fora_estabelecimento",
                                    "obitos_maternos", 100, "%", "Óbito em domicílio, via pública ou outros locais."),
    "pct_obito_direto": Metrica("Proporção de causas obstétricas diretas", "obitos_maternos_diretos",
                                "obitos_maternos", 100, "%",
                                "Causas diretas são, em sua maioria, evitáveis com assistência adequada."),
    "pct_obito_investigado": Metrica("Óbitos maternos investigados", "obitos_investigados", "obitos_maternos",
                                     100, "%", "Qualidade da vigilância: quanto maior, melhor.", maior_e_pior=False),
}

COLUNAS_SOMA = sorted({m.numerador for m in METRICAS.values()} |
                      {m.denominador for m in METRICAS.values() if m.denominador})

# Cores categóricas — fixas por entidade (nunca por ranking), paleta validada para daltonismo
CORES_RACA = {
    "Preta": "#2a78d6", "Negra": "#2a78d6", "Parda": "#eb6834", "Branca": "#1baf7a",
    "Indígena": "#eda100", "Amarela": "#e87ba4", "Ignorada": "#898781",
}
ORDEM_RACA = ["Preta", "Negra", "Parda", "Branca", "Indígena", "Amarela", "Ignorada"]
CORES_SEXO = {"Feminino": "#2a78d6", "Masculino": "#eb6834"}
ESCALA_SEQUENCIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
ESCALA_DIVERGENTE = [[0.0, "#2a78d6"], [0.5, "#f0efec"], [1.0, "#e34948"]]
# Grupos de causa materna: 8 slots da paleta categórica validada, em ordem fixa
CORES_GRUPO_CAUSA = {
    "Doenças preexistentes agravadas pela gestação": "#2a78d6",
    "Síndromes hipertensivas (pré-eclâmpsia/eclâmpsia)": "#eb6834",
    "Outras complicações obstétricas diretas": "#1baf7a",
    "Hemorragias (placenta prévia, descolamento, pós-parto)": "#eda100",
    "Gravidez que termina em aborto": "#e87ba4",
    "Infecção puerperal": "#008300",
    "Morte obstétrica de causa não especificada": "#6250d6",
    "Causas fora do cap. XV com vínculo gestacional": "#e34948",
    "Morte materna tardia / sequelas": "#898781",
}
