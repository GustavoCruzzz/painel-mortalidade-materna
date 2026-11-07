-- =============================================================================
-- Etapa 5 — Regras de Negócio em SQL (camada semântica)
-- Estas views são a "fonte oficial" das métricas: o dashboard e qualquer
-- ferramenta de BI (Metabase, Grafana) devem consultar por elas.
-- =============================================================================
SET search_path TO saude_materna, public;

-- UF (derivada da dimensão de localidade)
CREATE OR REPLACE VIEW vw_uf AS
SELECT DISTINCT cod_uf, sigla_uf, nome_uf, sigla_regiao, nome_regiao
FROM dim_localidade;

-- Fato desnormalizada com rótulos (útil para BI self-service)
CREATE OR REPLACE VIEW vw_fato_saude_materna AS
SELECT f.*,
       l.nome_municipio, l.sigla_uf, l.nome_uf, l.sigla_regiao, l.nome_regiao,
       r.descricao  AS raca_cor, r.grupo_ibge AS raca_cor_grupo,
       fe.descricao AS faixa_etaria, fe.ordem AS faixa_ordem,
       t.periodo
FROM fato_saude_materna f
JOIN dim_localidade   l  USING (cod_municipio)
JOIN dim_raca_cor     r  USING (cod_raca_cor)
JOIN dim_faixa_etaria fe USING (cod_faixa_etaria)
JOIN dim_tempo        t  USING (ano);

-- RN-03 · Razão de Mortalidade Materna (RMM) por 100 mil nascidos vivos
--   RMM = óbitos maternos (diretos + indiretos + não especificados, até 42 dias)
--         / nascidos vivos x 100.000
-- Recorte interseccional: UF x raça/cor x ano.
CREATE OR REPLACE VIEW vw_rmm_uf_raca AS
SELECT ano, sigla_regiao, sigla_uf, cod_raca_cor, raca_cor,
       SUM(nascidos_vivos)  AS nascidos_vivos,
       SUM(obitos_maternos) AS obitos_maternos,
       ROUND(100000.0 * SUM(obitos_maternos) / NULLIF(SUM(nascidos_vivos), 0), 1) AS rmm
FROM vw_fato_saude_materna
GROUP BY ano, sigla_regiao, sigla_uf, cod_raca_cor, raca_cor;

-- RN-09 · Risco relativo racial da morte materna
--   RR = RMM(mulheres pretas) / RMM(mulheres brancas) — RR > 1 indica sobre-risco
CREATE OR REPLACE VIEW vw_risco_relativo_racial AS
WITH base AS (
    SELECT ano, sigla_regiao,
           SUM(obitos_maternos) FILTER (WHERE cod_raca_cor = '2') AS obitos_pretas,
           SUM(nascidos_vivos)  FILTER (WHERE cod_raca_cor = '2') AS nv_pretas,
           SUM(obitos_maternos) FILTER (WHERE cod_raca_cor IN ('2','4')) AS obitos_negras,
           SUM(nascidos_vivos)  FILTER (WHERE cod_raca_cor IN ('2','4')) AS nv_negras,
           SUM(obitos_maternos) FILTER (WHERE cod_raca_cor = '1') AS obitos_brancas,
           SUM(nascidos_vivos)  FILTER (WHERE cod_raca_cor = '1') AS nv_brancas
    FROM vw_fato_saude_materna
    GROUP BY ano, sigla_regiao
)
SELECT ano, sigla_regiao,
       ROUND(100000.0 * obitos_pretas  / NULLIF(nv_pretas, 0), 1)  AS rmm_pretas,
       ROUND(100000.0 * obitos_negras  / NULLIF(nv_negras, 0), 1)  AS rmm_negras,
       ROUND(100000.0 * obitos_brancas / NULLIF(nv_brancas, 0), 1) AS rmm_brancas,
       ROUND((obitos_pretas::numeric / NULLIF(nv_pretas, 0))
             / NULLIF(obitos_brancas::numeric / NULLIF(nv_brancas, 0), 0), 2) AS rr_pretas_brancas,
       ROUND((obitos_negras::numeric / NULLIF(nv_negras, 0))
             / NULLIF(obitos_brancas::numeric / NULLIF(nv_brancas, 0), 0), 2) AS rr_negras_brancas
FROM base;

-- RN-07 · Indicadores de assistência obstétrica (proxies de violência obstétrica)
-- Todos os percentuais usam apenas registros com informação válida no denominador.
CREATE OR REPLACE VIEW vw_indicadores_obstetricos AS
SELECT ano, sigla_regiao, sigla_uf, cod_raca_cor, raca_cor, cod_faixa_etaria, faixa_etaria,
       SUM(nascidos_vivos) AS nascidos_vivos,
       ROUND(100.0 * SUM(partos_cesareos) / NULLIF(SUM(partos_info_valida), 0), 1)            AS pct_cesarea,
       ROUND(100.0 * SUM(robson1_cesareas) / NULLIF(SUM(robson1_total), 0), 1)               AS pct_cesarea_robson1,
       ROUND(100.0 * SUM(cesareas_eletivas_baixo_risco) / NULLIF(SUM(baixo_risco_total), 0), 1) AS pct_cesarea_eletiva_baixo_risco,
       ROUND(100.0 * SUM(prenatal_inadequado) / NULLIF(SUM(prenatal_classificado), 0), 1)     AS pct_prenatal_inadequado,
       ROUND(100.0 * SUM(menos_7_consultas) / NULLIF(SUM(consultas_info_valida), 0), 1)       AS pct_menos_7_consultas,
       ROUND(100.0 * SUM(inicio_prenatal_tardio) / NULLIF(SUM(inicio_prenatal_valido), 0), 1) AS pct_inicio_prenatal_tardio,
       ROUND(100.0 * SUM(partos_fora_estabelecimento) / NULLIF(SUM(local_info_valida), 0), 2) AS pct_parto_fora_estabelecimento,
       ROUND(100.0 * SUM(apgar5_baixo) / NULLIF(SUM(apgar5_valido), 0), 2)                    AS pct_apgar5_baixo,
       ROUND(100.0 * SUM(prematuros) / NULLIF(SUM(gestacao_valida), 0), 1)                    AS pct_prematuridade
FROM vw_fato_saude_materna
GROUP BY ano, sigla_regiao, sigla_uf, cod_raca_cor, raca_cor, cod_faixa_etaria, faixa_etaria;

-- RN-06 · Perfil assistencial das mortes maternas
CREATE OR REPLACE VIEW vw_obito_materno_detalhado AS
SELECT o.id_obito, o.ano, u.sigla_regiao, u.sigla_uf, u.nome_uf,
       r.descricao AS raca_cor, r.grupo_ibge AS raca_cor_grupo,
       fe.descricao AS faixa_etaria, e.descricao AS escolaridade,
       o.causa_basica, o.causa_basica_descricao,
       t.descricao AS tipo_obstetrico, t.entra_rmm,
       g.descricao AS grupo_causa,
       dm.descricao AS momento_obito, dl.descricao AS local_ocorrencia,
       da.descricao AS assistencia_medica, dn.descricao AS necropsia,
       o.investigado, o.cadeia_causas, o.texto_causas
FROM fato_obito_materno o
JOIN vw_uf u                    USING (cod_uf)
JOIN dim_raca_cor r             USING (cod_raca_cor)
JOIN dim_faixa_etaria fe        USING (cod_faixa_etaria)
JOIN dim_escolaridade e         USING (cod_escolaridade)
JOIN dim_tipo_obstetrico t      USING (tipo_obstetrico)
JOIN dim_grupo_causa_materna g  USING (grupo_causa)
LEFT JOIN dim_dominio dm ON dm.dominio = 'momento_obito'    AND dm.codigo = o.cod_momento_obito
LEFT JOIN dim_dominio dl ON dl.dominio = 'local_ocorrencia' AND dl.codigo = o.cod_local_ocorrencia
LEFT JOIN dim_dominio da ON da.dominio = 'sim_nao'          AND da.codigo = o.cod_assistencia_medica
LEFT JOIN dim_dominio dn ON dn.dominio = 'sim_nao'          AND dn.codigo = o.cod_necropsia;

-- Resumo de qualidade da última execução de cada sistema/ano
CREATE OR REPLACE VIEW vw_qualidade_ultima_carga AS
SELECT DISTINCT ON (sistema, ano)
       sistema, ano, finalizado_em, status, fracao_amostra, relatorio,
       fonte ->> 'name' AS recurso, fonte ->> 'last_modified' AS fonte_modificada_em
FROM etl_execucao
WHERE status = 'sucesso'
ORDER BY sistema, ano, finalizado_em DESC;
