-- =============================================================================
-- Etapa 4 — Modelagem: esquema estrela (Star Schema) no Aiven for PostgreSQL
-- Banco: PostgreSQL 16+ (plano free-1-1gb, 1 GB de disco)
-- Idempotente: pode ser executado a cada carga.
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS saude_materna;
SET search_path TO saude_materna, public;

-- -----------------------------------------------------------------------------
-- DIMENSÕES
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_tempo (
    ano              SMALLINT PRIMARY KEY,
    periodo          TEXT     NOT NULL,          -- pré-pandemia / pandemia / pós-pandemia
    base_preliminar  BOOLEAN  NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS dim_localidade (
    cod_municipio       CHAR(6)  PRIMARY KEY,     -- padrão SIM/SINASC (IBGE sem dígito verificador)
    cod_municipio_ibge7 CHAR(7),
    nome_municipio      TEXT     NOT NULL,
    cod_uf              CHAR(2)  NOT NULL,
    sigla_uf            CHAR(2)  NOT NULL,
    nome_uf             TEXT     NOT NULL,
    sigla_regiao        VARCHAR(2) NOT NULL,
    nome_regiao         TEXT     NOT NULL,
    municipio_ignorado  BOOLEAN  NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS ix_dim_localidade_uf ON dim_localidade (cod_uf);

CREATE TABLE IF NOT EXISTS dim_raca_cor (
    cod_raca_cor  VARCHAR(1) PRIMARY KEY,
    descricao     TEXT NOT NULL,
    grupo_ibge    TEXT NOT NULL                    -- Negra = Preta + Parda
);

CREATE TABLE IF NOT EXISTS dim_faixa_etaria (
    cod_faixa_etaria VARCHAR(5) PRIMARY KEY,
    descricao        TEXT NOT NULL,
    idade_min        SMALLINT,
    idade_max        SMALLINT,
    ordem            SMALLINT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_escolaridade (
    cod_escolaridade VARCHAR(1) PRIMARY KEY,
    descricao        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_sexo (
    cod_sexo  VARCHAR(1) PRIMARY KEY,
    descricao TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_tipo_obstetrico (
    tipo_obstetrico TEXT PRIMARY KEY,
    descricao       TEXT NOT NULL,
    entra_rmm       BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_grupo_causa_materna (
    grupo_causa TEXT PRIMARY KEY,
    descricao   TEXT NOT NULL,
    cids        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_grupo_causa_geral (
    cod_grupo_causa TEXT PRIMARY KEY,
    descricao       TEXT NOT NULL
);

-- Domínios pequenos do SIM (momento do óbito, local de ocorrência, sim/não)
CREATE TABLE IF NOT EXISTS dim_dominio (
    dominio   TEXT       NOT NULL,
    codigo    VARCHAR(2) NOT NULL,
    descricao TEXT       NOT NULL,
    PRIMARY KEY (dominio, codigo)
);

CREATE TABLE IF NOT EXISTS dim_cid10 (
    cid       VARCHAR(4) PRIMARY KEY,
    descricao TEXT NOT NULL
);

-- -----------------------------------------------------------------------------
-- FATO 1 · Indicadores de saúde materna por município x raça/cor x faixa etária
-- Grão: ano x município de residência x raça/cor da mãe x faixa etária da mãe
-- Une o denominador (SINASC) e o numerador (SIM) da Razão de Mortalidade Materna.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fato_saude_materna (
    ano                            SMALLINT   NOT NULL REFERENCES dim_tempo,
    cod_municipio                  CHAR(6)    NOT NULL REFERENCES dim_localidade,
    cod_raca_cor                   VARCHAR(1) NOT NULL REFERENCES dim_raca_cor,
    cod_faixa_etaria               VARCHAR(5) NOT NULL REFERENCES dim_faixa_etaria,
    cod_uf                         CHAR(2)    GENERATED ALWAYS AS (substr(cod_municipio, 1, 2)) STORED,
    -- SINASC (nascidos vivos e assistência ao parto)
    nascidos_vivos                 INTEGER NOT NULL DEFAULT 0 CHECK (nascidos_vivos >= 0),
    partos_info_valida             INTEGER NOT NULL DEFAULT 0,
    partos_cesareos                INTEGER NOT NULL DEFAULT 0,
    robson_classificados           INTEGER NOT NULL DEFAULT 0,
    robson1_total                  INTEGER NOT NULL DEFAULT 0,
    robson1_cesareas               INTEGER NOT NULL DEFAULT 0,
    baixo_risco_total              INTEGER NOT NULL DEFAULT 0,
    cesareas_eletivas_baixo_risco  INTEGER NOT NULL DEFAULT 0,
    prenatal_classificado          INTEGER NOT NULL DEFAULT 0,
    prenatal_inadequado            INTEGER NOT NULL DEFAULT 0,
    consultas_info_valida          INTEGER NOT NULL DEFAULT 0,
    menos_7_consultas              INTEGER NOT NULL DEFAULT 0,
    inicio_prenatal_valido         INTEGER NOT NULL DEFAULT 0,
    inicio_prenatal_tardio         INTEGER NOT NULL DEFAULT 0,
    local_info_valida              INTEGER NOT NULL DEFAULT 0,
    partos_fora_estabelecimento    INTEGER NOT NULL DEFAULT 0,
    apgar5_valido                  INTEGER NOT NULL DEFAULT 0,
    apgar5_baixo                   INTEGER NOT NULL DEFAULT 0,
    gestacao_valida                INTEGER NOT NULL DEFAULT 0,
    prematuros                     INTEGER NOT NULL DEFAULT 0,
    peso_valido                    INTEGER NOT NULL DEFAULT 0,
    baixo_peso                     INTEGER NOT NULL DEFAULT 0,
    -- SIM (óbitos maternos)
    obitos_maternos                INTEGER NOT NULL DEFAULT 0,
    obitos_maternos_diretos        INTEGER NOT NULL DEFAULT 0,
    obitos_maternos_indiretos      INTEGER NOT NULL DEFAULT 0,
    obitos_maternos_tardios        INTEGER NOT NULL DEFAULT 0,
    obitos_sem_assistencia         INTEGER NOT NULL DEFAULT 0,
    obitos_fora_estabelecimento    INTEGER NOT NULL DEFAULT 0,
    obitos_investigados            INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (ano, cod_municipio, cod_raca_cor, cod_faixa_etaria),
    -- Regras de Veracidade no próprio banco: numerador nunca maior que denominador
    CHECK (partos_cesareos <= partos_info_valida),
    CHECK (robson1_cesareas <= robson1_total),
    CHECK (prenatal_inadequado <= prenatal_classificado),
    CHECK (obitos_maternos_diretos + obitos_maternos_indiretos <= obitos_maternos)
);
CREATE INDEX IF NOT EXISTS ix_fato_sm_uf_ano   ON fato_saude_materna (cod_uf, ano);
CREATE INDEX IF NOT EXISTS ix_fato_sm_raca_ano ON fato_saude_materna (cod_raca_cor, ano);

-- -----------------------------------------------------------------------------
-- FATO 2 · Registro anonimizado de cada morte materna (drill-down por causa)
-- Generalização LGPD: localização apenas por UF; idade apenas por faixa.
-- Colunas semi-estruturadas: cadeia_causas (JSONB) e busca textual (tsvector).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fato_obito_materno (
    id_obito               TEXT       PRIMARY KEY,
    ano                    SMALLINT   NOT NULL REFERENCES dim_tempo,
    cod_uf                 CHAR(2)    NOT NULL,
    cod_raca_cor           VARCHAR(1) NOT NULL REFERENCES dim_raca_cor,
    cod_faixa_etaria       VARCHAR(5) NOT NULL REFERENCES dim_faixa_etaria,
    cod_escolaridade       VARCHAR(1) NOT NULL REFERENCES dim_escolaridade,
    causa_basica           VARCHAR(4) NOT NULL,
    causa_basica_descricao TEXT,
    tipo_obstetrico        TEXT       NOT NULL REFERENCES dim_tipo_obstetrico,
    grupo_causa            TEXT       NOT NULL REFERENCES dim_grupo_causa_materna,
    cod_momento_obito      VARCHAR(1) NOT NULL,
    cod_local_ocorrencia   VARCHAR(1) NOT NULL,
    cod_assistencia_medica VARCHAR(1) NOT NULL,
    cod_necropsia          VARCHAR(1) NOT NULL,
    investigado            BOOLEAN    NOT NULL,
    cadeia_causas          JSONB      NOT NULL,
    texto_causas           TEXT,
    -- translate() remove acentos (é imutável, ao contrário de unaccent) -> busca "eclampsia" acha "Eclâmpsia"
    tsv_causas             TSVECTOR GENERATED ALWAYS AS (to_tsvector('portuguese', translate(lower(coalesce(texto_causas, '')),
                               'áàâãäéèêëíìîïóòôõöúùûüç', 'aaaaaeeeeiiiiooooouuuuc'))) STORED
);
CREATE INDEX IF NOT EXISTS ix_fom_ano_uf   ON fato_obito_materno (ano, cod_uf);
CREATE INDEX IF NOT EXISTS ix_fom_cadeia   ON fato_obito_materno USING GIN (cadeia_causas jsonb_path_ops);
CREATE INDEX IF NOT EXISTS ix_fom_tsv      ON fato_obito_materno USING GIN (tsv_causas);

-- -----------------------------------------------------------------------------
-- FATO 3 · Óbitos em idade reprodutiva (10–49) por sexo — eixo de gênero
-- Grão: ano x UF x sexo x raça/cor x faixa etária x grupo de causa
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fato_obito_idade_reprodutiva (
    ano                 SMALLINT   NOT NULL REFERENCES dim_tempo,
    cod_uf              CHAR(2)    NOT NULL,
    cod_sexo            VARCHAR(1) NOT NULL REFERENCES dim_sexo,
    cod_raca_cor        VARCHAR(1) NOT NULL REFERENCES dim_raca_cor,
    cod_faixa_etaria    VARCHAR(5) NOT NULL REFERENCES dim_faixa_etaria,
    cod_grupo_causa     TEXT       NOT NULL REFERENCES dim_grupo_causa_geral,
    n_obitos            INTEGER    NOT NULL CHECK (n_obitos > 0),
    n_gestante_puerpera INTEGER    NOT NULL DEFAULT 0,
    PRIMARY KEY (ano, cod_uf, cod_sexo, cod_raca_cor, cod_faixa_etaria, cod_grupo_causa)
);

-- -----------------------------------------------------------------------------
-- CONTROLE · Log de execuções do ETL (Velocidade + Veracidade)
-- relatorio: contadores de qualidade · fonte: metadados JSON do recurso CKAN
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS etl_execucao (
    id            BIGSERIAL PRIMARY KEY,
    iniciado_em   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finalizado_em TIMESTAMPTZ,
    sistema       TEXT     NOT NULL,
    ano           SMALLINT NOT NULL,
    status        TEXT     NOT NULL,
    fracao_amostra NUMERIC(4,3) NOT NULL DEFAULT 1,
    relatorio     JSONB,
    fonte         JSONB
);
CREATE INDEX IF NOT EXISTS ix_etl_exec ON etl_execucao (sistema, ano, finalizado_em DESC);
