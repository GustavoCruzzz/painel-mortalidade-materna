"""Painel Epidemiológico de Mortalidade Materna e Violência Obstétrica.

Executar localmente:   streamlit run dashboard/app.py
Fonte: SIM e SINASC (Ministério da Saúde) carregados no Aiven for PostgreSQL.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dados  # noqa: E402
from metricas import (CORES_GRUPO_CAUSA, CORES_RACA, CORES_SEXO, ESCALA_DIVERGENTE,  # noqa: E402
                      ESCALA_SEQUENCIAL, METRICAS, ORDEM_RACA)

st.set_page_config(page_title="Painel de Mortalidade Materna", page_icon="🩺", layout="wide")

FONTE = "system-ui, -apple-system, 'Segoe UI', sans-serif"


def estilizar(fig: go.Figure, altura: int = 380, legenda: bool = True) -> go.Figure:
    fig.update_layout(height=altura, margin=dict(l=8, r=8, t=36, b=8), font_family=FONTE,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title_text="")
                      if legenda else dict(), showlegend=legenda, hoverlabel=dict(font_family=FONTE))
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridwidth=0.5)
    return fig


def tabela_expansivel(df: pd.DataFrame, rotulo: str = "Ver dados em tabela") -> None:
    with st.expander(rotulo):
        st.dataframe(df, width="stretch", hide_index=True)


def com_metrica(df: pd.DataFrame, chave: str) -> pd.DataFrame:
    df = df.copy()
    df["valor"] = METRICAS[chave].calcular(df)
    return df


def seletor_metrica(rotulo: str, chaves: list[str], key: str, padrao: str) -> str:
    return st.selectbox(rotulo, chaves, index=chaves.index(padrao), key=key,
                        format_func=lambda k: METRICAS[k].rotulo)


# =============================================================================
# FILTROS GLOBAIS (barra lateral) — aplicados de forma cruzada a todas as abas
# =============================================================================
op = dados.opcoes()
if not op["anos"]:
    st.warning("Banco vazio. Rode o ETL: `python -m etl.pipeline`.")
    st.stop()

with st.sidebar:
    st.header("Filtros")
    ano_ini, ano_fim = st.select_slider("Período", options=op["anos"],
                                        value=(op["anos"][0], op["anos"][-1]))
    loc = op["loc"]
    regioes_map = dict(zip(loc["sigla_regiao"], loc["nome_regiao"]))
    regioes = st.multiselect("Região", sorted(regioes_map), format_func=regioes_map.get,
                             placeholder="Todas")
    ufs_disp = loc[loc["sigla_regiao"].isin(regioes)] if regioes else loc
    ufs = st.multiselect("Estado (UF)", sorted(ufs_disp["sigla_uf"].unique()), placeholder="Todos")
    racas_map = dict(zip(op["racas"]["cod_raca_cor"], op["racas"]["descricao"]))
    racas = st.multiselect("Raça/cor", list(racas_map), format_func=racas_map.get, placeholder="Todas")
    agrupar = st.toggle("Agrupar Preta + Parda como Negra (IBGE)", value=False)
    faixas_map = dict(zip(op["faixas"]["cod_faixa_etaria"], op["faixas"]["descricao"]))
    faixas = st.multiselect("Faixa etária", list(faixas_map), format_func=faixas_map.get, placeholder="Todas")
    sexos = st.multiselect("Sexo (aba Gênero)", ["2", "1"],
                           format_func={"1": "Masculino", "2": "Feminino"}.get, placeholder="Ambos")
    st.caption("Fontes: SIM e SINASC/Ministério da Saúde (dados abertos), IBGE e CID-10/DATASUS. "
               "Raça/cor e idade referem-se à mulher (mãe ou falecida).")

F = dados.Filtros(ano_ini, ano_fim, tuple(regioes), tuple(ufs), tuple(racas), tuple(faixas),
                  tuple(sexos), agrupar)

# =============================================================================
# CABEÇALHO + KPIs
# =============================================================================
st.title("Mortalidade materna e violência obstétrica no Brasil")
st.markdown(f"**{ano_ini}–{ano_fim}** · Análise interseccional de raça/cor, idade e território · "
            "ODS 5 (Igualdade de Gênero) e ODS 18 (Igualdade Étnico-Racial)")

por_ano = dados.agregar(F, ("ano",)).sort_values("ano")
total = por_ano.drop(columns="ano").sum().to_frame().T


def kpi(col, chave: str, ajuda: str | None = None) -> None:
    m = METRICAS[chave]
    valor = m.calcular(total).iloc[0]
    delta = None
    if len(por_ano) >= 2:
        serie = m.calcular(por_ano)
        delta_v = serie.iloc[-1] - serie.iloc[-2]
        if pd.notna(delta_v):
            delta = (f"{delta_v:+.1f}".replace(".", ",") + (" p.p." if m.unidade == "%" else "")
                     + f" em {int(por_ano['ano'].iloc[-1])}")
    col.metric(m.rotulo, m.formatar(valor), delta,
               delta_color="inverse" if m.maior_e_pior else "normal", help=ajuda or m.descricao, border=True)


# Risco relativo racial: calculado sem o filtro de raça (compara grupos)
por_raca_rr = dados.agregar(replace(F, racas=(), agrupar_negras=False), ("raca",)).set_index("raca")
rmm = METRICAS["rmm"]


def _rmm(grupos: list[str]) -> float:
    sub = por_raca_rr.loc[por_raca_rr.index.intersection(grupos)].sum().to_frame().T
    return rmm.calcular(sub).iloc[0] if len(sub) else float("nan")


rr_pretas = _rmm(["Preta"]) / _rmm(["Branca"])
rr_indigenas = _rmm(["Indígena"]) / _rmm(["Branca"])

c1, c2, c3 = st.columns(3)
kpi(c1, "rmm")
c2.metric("Risco relativo: pretas × brancas", f"{rr_pretas:.2f}×".replace(".", ","), border=True,
          help="RMM de mulheres pretas ÷ RMM de mulheres brancas, no recorte filtrado (ignora o filtro de "
               "raça). Valores > 1 indicam sobre-risco.")
c3.metric("Risco relativo: indígenas × brancas", f"{rr_indigenas:.2f}×".replace(".", ","), border=True,
          help="RMM de mulheres indígenas ÷ RMM de mulheres brancas.")
c4, c5, c6 = st.columns(3)
kpi(c4, "pct_cesarea_eletiva")
kpi(c5, "pct_prenatal_inadequado")
kpi(c6, "pct_obito_sem_assist")

nv_total, ob_total = int(total["nascidos_vivos"].iloc[0]), int(total["obitos_maternos"].iloc[0])
st.caption(f"Recorte atual: {nv_total:,} nascidos vivos e {ob_total:,} óbitos maternos.".replace(",", "."))
if ob_total < 20:
    st.info("Menos de 20 óbitos maternos no recorte: a RMM fica estatisticamente instável. "
            "Amplie o período ou a área geográfica.")

aba = st.tabs(["📈 Evolução", "🗺️ Drill-down territorial", "🔀 Interseccionalidade",
               "🩺 Causas dos óbitos", "⚖️ Gênero (10–49 anos)", "🧪 Qualidade & método"])

DIMENSOES = {"raca": "Raça/cor", "faixa": "Faixa etária", "regiao": "Região"}

# =============================================================================
# ABA 1 · Evolução temporal com seletor de métrica e de quebra
# =============================================================================
with aba[0]:
    a, b = st.columns([2, 1])
    with a:
        chave = seletor_metrica("Métrica analisada", list(METRICAS), "met_evol", "rmm")
    with b:
        quebra = st.segmented_control("Comparar por", list(DIMENSOES), format_func=DIMENSOES.get,
                                      default="raca", key="quebra_evol") or "raca"
    m = METRICAS[chave]
    st.caption(m.descricao)
    dims = ("ano", quebra) + (("faixa_ordem",) if quebra == "faixa" else ())
    df = com_metrica(dados.agregar(F, dims), chave).sort_values(["ano"] + (["faixa_ordem"] if quebra == "faixa"
                                                                           else []))
    cores = CORES_RACA if quebra == "raca" else None
    ordem = {"raca": [r for r in ORDEM_RACA if r in df["raca"].unique()]} if quebra == "raca" else {}
    fig = px.line(df, x="ano", y="valor", color=quebra, markers=True, color_discrete_map=cores,
                  category_orders=ordem, labels={"valor": m.rotulo, "ano": "Ano", quebra: DIMENSOES[quebra]})
    fig.update_traces(line_width=2, marker_size=8,
                      hovertemplate="%{fullData.name}<br>%{x}: <b>%{y:.1f}</b><extra></extra>")
    fig.update_xaxes(dtick=1)
    if chave == "rmm":
        fig.add_hline(y=30, line_dash="dot", line_width=1, line_color="#898781",
                      annotation_text="Meta ODS Brasil (30)", annotation_position="top left")
    st.plotly_chart(estilizar(fig, 420), width="stretch")

    periodo = com_metrica(dados.agregar(F, (quebra,)), chave).sort_values("valor")
    fig2 = px.bar(periodo, x="valor", y=quebra, orientation="h", color=quebra, color_discrete_map=cores,
                  labels={"valor": f"{m.rotulo} ({ano_ini}–{ano_fim})", quebra: ""}, text_auto=".1f")
    fig2.update_traces(marker_line_width=0, hovertemplate="%{y}: <b>%{x:.1f}</b><extra></extra>")
    st.plotly_chart(estilizar(fig2, 60 + 38 * len(periodo), legenda=False), width="stretch")
    tabela_expansivel(df.drop(columns=[c for c in df.columns if c not in ("ano", quebra, "valor",
                                                                          m.numerador, m.denominador)]))

# =============================================================================
# ABA 2 · Drill-down Brasil -> Região -> UF -> Município (clique na barra)
# =============================================================================
with aba[1]:
    if "drill" not in st.session_state:
        st.session_state.drill, st.session_state.drill_nonce = [], 0
    caminho = st.session_state.drill

    a, b, c = st.columns([2, 1, 1])
    with a:
        chave_d = seletor_metrica("Métrica", list(METRICAS), "met_drill", "rmm")
    with b:
        min_nv = st.number_input("Mín. de nascidos vivos por unidade", 0, 100_000, 1_000, step=500,
                                 help="Evita taxas instáveis em locais pequenos")
    with c:
        top_n = st.slider("Mostrar até", 5, 40, 20)
    md = METRICAS[chave_d]

    # Breadcrumb navegável
    niveis = ["Brasil"] + caminho
    cols = st.columns(len(niveis) + 3)
    for i, nome in enumerate(niveis):
        if cols[i].button(nome, key=f"bc_{i}", type="secondary" if i < len(niveis) - 1 else "primary"):
            st.session_state.drill = caminho[:i]
            st.session_state.drill_nonce += 1  # descarta seleções antigas do gráfico
            st.rerun()

    if len(caminho) == 0:
        nivel, fd = "sigla_regiao", F
    elif len(caminho) == 1:
        nivel, fd = "uf", replace(F, regioes=(caminho[0],))
    else:
        nivel, fd = "municipio", replace(F, regioes=(caminho[0],), ufs=(caminho[1],))

    dd = com_metrica(dados.agregar(fd, (nivel,)), chave_d)
    dd = dd[dd["nascidos_vivos"] >= min_nv] if nivel == "municipio" else dd
    dd = dd.dropna(subset=["valor"]).sort_values("valor", ascending=False).head(top_n)
    nomes = {"sigla_regiao": "Região", "uf": "UF", "municipio": "Município"}
    fig = px.bar(dd.sort_values("valor"), x="valor", y=nivel, orientation="h",
                 color="valor", color_continuous_scale=ESCALA_SEQUENCIAL,
                 labels={"valor": md.rotulo, nivel: nomes[nivel]},
                 hover_data={"nascidos_vivos": ":,", "obitos_maternos": True})
    fig.update_traces(marker_line_width=0)
    fig.update_coloraxes(showscale=False)
    ev = st.plotly_chart(estilizar(fig, 80 + 28 * len(dd), legenda=False), width="stretch",
                         on_select="rerun", selection_mode="points", key=f"drill_{'/'.join(caminho)}_{st.session_state.drill_nonce}")
    if nivel != "municipio":
        st.caption("👆 Clique em uma barra para detalhar o próximo nível.")
    pontos = (ev or {}).get("selection", {}).get("points", []) if ev else []
    if pontos and nivel != "municipio":
        st.session_state.drill = caminho + [pontos[0]["y"]]
        st.rerun()

    # Detalhamento do segmento selecionado por raça/cor
    if len(dd):
        st.subheader("Detalhamento por raça/cor do segmento")
        alvo = st.selectbox(nomes[nivel], dd[nivel].tolist())
        if nivel == "sigla_regiao":
            fs = replace(fd, regioes=(alvo,))
            seg = dados.agregar(fs, ("raca",))
        elif nivel == "uf":
            fs = replace(fd, ufs=(alvo,))
            seg = dados.agregar(fs, ("raca",))
        else:
            seg = dados.agregar(fd, ("municipio", "raca"))
            seg = seg[seg["municipio"] == alvo]
        seg = com_metrica(seg, chave_d).sort_values("valor", ascending=False)
        if md.denominador:  # mesma regra de base mínima do heatmap (evita taxas instáveis)
            minimo = 10_000 if md.multiplicador >= 100_000 else 300
            ocultos = seg.loc[seg[md.denominador] < minimo, "raca"].tolist()
            seg = seg[seg[md.denominador] >= minimo]
            if ocultos:
                st.caption(f"Ocultados por base pequena (< {minimo:,}): ".replace(",", ".") + ", ".join(ocultos))
        fig3 = px.bar(seg, x="raca", y="valor", color="raca", color_discrete_map=CORES_RACA,
                      labels={"valor": md.rotulo, "raca": ""}, text_auto=".1f",
                      hover_data={"nascidos_vivos": ":,", "obitos_maternos": True})
        st.plotly_chart(estilizar(fig3, 320, legenda=False), width="stretch")
    tabela_expansivel(dd)

# =============================================================================
# ABA 3 · Interseccionalidade raça/cor x faixa etária + risco relativo
# =============================================================================
with aba[2]:
    chave_i = seletor_metrica("Métrica", list(METRICAS), "met_inter", "rmm")
    mi = METRICAS[chave_i]
    hx = com_metrica(dados.agregar(F, ("raca", "faixa", "faixa_ordem")), chave_i)
    hx = hx[(hx["raca"] != "Ignorada") & hx["faixa_ordem"].between(1, 8)]  # idade fértil 10–49
    base_min = 10_000 if mi.multiplicador >= 100_000 else 300
    if mi.denominador:
        hx.loc[hx[mi.denominador] < base_min, "valor"] = float("nan")  # base pequena -> célula vazia
    piv = hx.pivot_table(index="raca", columns="faixa", values="valor", dropna=False)
    ordem_faixas = hx.sort_values("faixa_ordem")["faixa"].unique().tolist()
    piv = piv.reindex(columns=ordem_faixas, index=[r for r in ORDEM_RACA if r in piv.index])
    den = hx.pivot_table(index="raca", columns="faixa", values=mi.denominador or mi.numerador).reindex_like(piv)
    fig = go.Figure(go.Heatmap(z=piv.values, x=piv.columns, y=piv.index, colorscale=ESCALA_SEQUENCIAL,
                               xgap=2, ygap=2, customdata=den.values,
                               text=piv.map(lambda v: "" if pd.isna(v) else f"{v:.1f}").values,
                               texttemplate="%{text}",
                               hovertemplate="%{y} · %{x}<br><b>%{z:.1f}</b><br>base: %{customdata:,}"
                                             "<extra></extra>",
                               colorbar=dict(title=dict(text=mi.unidade or "valor"))))
    fig.update_yaxes(autorange="reversed")
    st.subheader(f"{mi.rotulo}: raça/cor × faixa etária")
    st.plotly_chart(estilizar(fig, 380, legenda=False), width="stretch")
    st.caption(f"Idade fértil (10–49 anos). Células em branco têm base menor que {base_min:,} "
               "(estatisticamente instáveis). Passe o mouse para ver a base de cada célula.".replace(",", "."))

    st.subheader("Risco relativo de morte materna em relação às mulheres brancas")
    grupo_cmp = st.segmented_control("Grupo comparado", ["Preta", "Negra", "Indígena", "Parda"],
                                     default="Preta", key="rr_grupo") or "Preta"
    base_rr = dados.agregar(replace(F, racas=(), agrupar_negras=False), ("ano", "regiao", "raca"))
    linhas = []
    for (ano, reg), g in base_rr.groupby(["ano", "regiao"]):
        g = g.set_index("raca")
        alvo = ["Preta", "Parda"] if grupo_cmp == "Negra" else [grupo_cmp]
        num = g.loc[g.index.intersection(alvo)].sum()
        ref = g.loc[["Branca"]].sum() if "Branca" in g.index else None
        if ref is None or ref["nascidos_vivos"] == 0 or num["nascidos_vivos"] == 0 or ref["obitos_maternos"] == 0:
            continue
        rr = (num["obitos_maternos"] / num["nascidos_vivos"]) / (ref["obitos_maternos"] / ref["nascidos_vivos"])
        linhas.append({"ano": ano, "regiao": reg, "rr": rr, "obitos_grupo": int(num["obitos_maternos"])})
    rrdf = pd.DataFrame(linhas)
    if not rrdf.empty:
        piv_rr = rrdf.pivot(index="regiao", columns="ano", values="rr")
        n_rr = rrdf.pivot(index="regiao", columns="ano", values="obitos_grupo").reindex_like(piv_rr)
        lim = max(2.0, float(piv_rr.max().max()))
        fig = go.Figure(go.Heatmap(z=piv_rr.values, x=[str(c) for c in piv_rr.columns], y=piv_rr.index,
                                   zmin=0, zmid=1, zmax=lim, colorscale=ESCALA_DIVERGENTE, xgap=2, ygap=2,
                                   customdata=n_rr.values,
                                   text=piv_rr.map(lambda v: "" if pd.isna(v) else f"{v:.2f}").values,
                                   texttemplate="%{text}",
                                   hovertemplate="%{y} · %{x}<br>RR <b>%{z:.2f}</b><br>óbitos do grupo: "
                                                 "%{customdata}<extra></extra>",
                                   colorbar=dict(title=dict(text="RR"))))
        st.plotly_chart(estilizar(fig, 300, legenda=False), width="stretch")
        st.caption("RR = RMM do grupo ÷ RMM de mulheres brancas. Vermelho (> 1) = sobre-risco; azul (< 1) = "
                   "risco menor; cinza ≈ igualdade.")
        tabela_expansivel(rrdf)

# =============================================================================
# ABA 4 · Causas dos óbitos maternos (treemap com drill-down + busca textual)
# =============================================================================
with aba[3]:
    ob = dados.obitos_maternos(F)
    incluir_tardias = st.toggle("Incluir mortes maternas tardias (43 dias a 1 ano)", value=False)
    if not incluir_tardias:
        ob = ob[ob["entra_rmm"]]
    if ob.empty:
        st.info("Sem óbitos no recorte selecionado.")
    else:
        st.subheader(f"{len(ob):,} óbitos maternos · clique para aprofundar".replace(",", "."))
        tm = ob.groupby(["tipo_obstetrico", "grupo_causa", "causa_descricao"]).size().reset_index(name="obitos")
        fig = px.treemap(tm, path=[px.Constant("Todos os óbitos"), "tipo_obstetrico", "grupo_causa",
                                   "causa_descricao"], values="obitos", color="obitos",
                         color_continuous_scale=ESCALA_SEQUENCIAL, maxdepth=3)
        fig.update_traces(hovertemplate="%{label}<br><b>%{value}</b> óbitos (%{percentRoot:.1%})<extra></extra>",
                          marker_line_width=2)
        fig.update_coloraxes(showscale=False)
        st.plotly_chart(estilizar(fig, 480, legenda=False), width="stretch")

        a, b = st.columns(2)
        with a:
            dist = (ob.groupby(["raca", "grupo_causa"]).size() / ob.groupby("raca").size()).reset_index(name="pct")
            dist["pct"] *= 100
            fig = px.bar(dist, x="pct", y="raca", color="grupo_causa", orientation="h",
                         color_discrete_map=CORES_GRUPO_CAUSA,
                         labels={"pct": "% dos óbitos do grupo", "raca": "", "grupo_causa": ""},
                         category_orders={"raca": [r for r in ORDEM_RACA if r in dist["raca"].unique()]})
            fig.update_traces(marker_line_width=1, hovertemplate="%{y} · %{fullData.name}: <b>%{x:.1f}%</b>"
                                                                 "<extra></extra>")
            st.markdown("**Perfil de causas por raça/cor**")
            st.plotly_chart(estilizar(fig, 380), width="stretch")
        with b:
            dim_perfil = st.selectbox("Perfil assistencial", ["momento_obito", "local_ocorrencia",
                                                              "assistencia_medica", "escolaridade"],
                                      format_func=lambda s: s.replace("_", " ").capitalize())
            perf = ob.groupby([dim_perfil, "raca"]).size().reset_index(name="obitos")
            perf["pct"] = 100 * perf["obitos"] / perf.groupby("raca")["obitos"].transform("sum")
            fig = px.bar(perf, x="pct", y=dim_perfil, color="raca", orientation="h", barmode="group",
                         color_discrete_map=CORES_RACA, hover_data={"obitos": True},
                         labels={"pct": "% dos óbitos do grupo racial", dim_perfil: ""},
                         category_orders={"raca": [r for r in ORDEM_RACA if r in perf["raca"].unique()]})
            fig.update_traces(marker_line_width=0)
            st.plotly_chart(estilizar(fig, 380), width="stretch")

        st.markdown("**Detalhamento de um segmento** (registros anonimizados)")
        grupo_sel = st.selectbox("Grupo de causa", ob["grupo_causa"].value_counts().index.tolist())
        st.dataframe(ob[ob["grupo_causa"] == grupo_sel]
                     .drop(columns=["id_obito", "entra_rmm", "faixa_ordem"])
                     .sort_values(["ano", "sigla_uf"]), width="stretch", hide_index=True, height=280)

    st.divider()
    st.subheader("🔎 Busca nas causas registradas na Declaração de Óbito")
    termo = st.text_input("Termo (ex.: eclâmpsia, hemorragia, infecção, COVID, aborto)", "hemorragia")
    if termo.strip():
        motor, res, agg = dados.buscar_causas(termo.strip(), F)
        st.caption(f"Motor de busca: **{motor}** · {len(res)} resultados mais relevantes")
        if not agg.empty:
            fig = px.bar(agg, x="raca", y="n", color="raca", color_discrete_map=CORES_RACA,
                         labels={"n": "Óbitos que mencionam o termo", "raca": ""}, text_auto=True)
            st.plotly_chart(estilizar(fig, 260, legenda=False), width="stretch")
        st.dataframe(res, width="stretch", hide_index=True, height=260)

# =============================================================================
# ABA 5 · Gênero: mortalidade em idade reprodutiva por sexo x raça/cor
# =============================================================================
with aba[4]:
    st.caption("Contexto de gênero: óbitos de pessoas de 10 a 49 anos por grupo de causa. Mostra o peso da "
               "morte materna e das agressões entre mulheres em comparação aos homens.")
    gd = dados.obitos_idade_reprodutiva(F)
    if gd.empty:
        st.info("Sem dados no recorte.")
    else:
        a, b = st.columns([1, 1])
        with a:
            modo = st.segmented_control("Métrica", ["Nº de óbitos", "% dos óbitos do sexo"],
                                        default="% dos óbitos do sexo", key="modo_gen") or "Nº de óbitos"
        with b:
            desagregar = st.toggle("Desagregar mulheres por raça/cor", value=False)
        if desagregar:
            base = gd[gd["sexo"] == "Feminino"].groupby(["raca", "grupo_causa"])["n_obitos"].sum().reset_index()
            serie, cores_g = "raca", CORES_RACA
        else:
            base = gd.groupby(["sexo", "grupo_causa"])["n_obitos"].sum().reset_index()
            serie, cores_g = "sexo", CORES_SEXO
        if modo.startswith("%"):
            base["valor"] = 100 * base["n_obitos"] / base.groupby(serie)["n_obitos"].transform("sum")
        else:
            base["valor"] = base["n_obitos"]
        ordem_g = base.groupby("grupo_causa")["valor"].sum().sort_values().index.tolist()
        fig = px.bar(base, x="valor", y="grupo_causa", color=serie, barmode="group", orientation="h",
                     color_discrete_map=cores_g, category_orders={"grupo_causa": ordem_g},
                     labels={"valor": modo, "grupo_causa": "", serie: ""})
        fig.update_traces(marker_line_width=0, hovertemplate="%{fullData.name} · %{y}: <b>%{x:,.1f}</b>"
                                                              "<extra></extra>")
        st.plotly_chart(estilizar(fig, 460), width="stretch")

        fem = gd[gd["sexo"] == "Feminino"]
        agr = fem[fem["cod_grupo_causa"] == "agressao"]
        k1, k2, k3 = st.columns(3)
        k1.metric("Mulheres (10–49) mortas por agressão", f"{int(agr['n_obitos'].sum()):,}".replace(",", "."),
                  border=True)
        k2.metric("…das quais gestantes ou puérperas", f"{int(agr['n_gestante_puerpera'].sum()):,}"
                  .replace(",", "."), border=True,
                  help="Óbito por agressão com gravidez/puerpério declarado na DO (campos OBITOGRAV/OBITOPUERP).")
        negras = agr[agr["raca"].isin(["Preta", "Parda", "Negra"])]["n_obitos"].sum()
        k3.metric("% negras entre mulheres mortas por agressão",
                  f"{100 * negras / max(agr['n_obitos'].sum(), 1):.1f}%".replace(".", ","), border=True)
        tabela_expansivel(base)

# =============================================================================
# ABA 6 · Qualidade dos dados e metodologia
# =============================================================================
with aba[5]:
    q = dados.qualidade()
    if not q.empty:
        rel = pd.json_normalize(q["relatorio"]).drop(columns=["sistema", "ano"], errors="ignore")
        st.subheader("Última carga por sistema/ano (Veracidade)")
        st.dataframe(pd.concat([q.drop(columns=["relatorio"]).reset_index(drop=True), rel], axis=1),
                     width="stretch", hide_index=True)
    comp = dados.agregar(replace(F, racas=()), ("ano", "raca"))
    comp = comp.groupby("ano").apply(
        lambda g: pd.Series({"% raça/cor ignorada (nascimentos)":
                             100 * g.loc[g["raca"] == "Ignorada", "nascidos_vivos"].sum() / g["nascidos_vivos"].sum(),
                             "% óbitos maternos investigados":
                             100 * g["obitos_investigados"].sum() / max(g["obitos_maternos"].sum(), 1)}),
        include_groups=False).reset_index()
    st.subheader("Completude e vigilância")
    st.dataframe(comp.round(1), width="stretch", hide_index=True)
    st.markdown("""
**Como ler este painel**
- **RMM** = óbitos maternos (diretos, indiretos e não especificados, até 42 dias) ÷ nascidos vivos × 100.000.
  Raça/cor e faixa etária do numerador vêm da Declaração de Óbito (SIM) e do denominador, da mãe na
  Declaração de Nascido Vivo (SINASC).
- **Proxies de violência obstétrica**: cesárea eletiva em baixo risco (Robson 1–4 antes do trabalho de parto),
  cesárea no grupo 1 de Robson, pré-natal inadequado (Kotelchuck), parto fora de estabelecimento e
  óbitos maternos sem assistência médica. Não são medidas diretas de violência, e sim de **práticas
  assistenciais e acesso** associadas a ela na literatura.
- **LGPD**: o banco não guarda datas exatas, estabelecimento, ocupação nem idade exata. Os óbitos maternos
  individuais ficam generalizados por UF e faixa etária.
- Regras completas e dicionário de dados: `README.md` do repositório.
""")
