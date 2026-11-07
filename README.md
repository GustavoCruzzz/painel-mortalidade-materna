# Painel Epidemiológico de Mortalidade Materna e Violência Obstétrica

> Projeto Prático · Big Data e Analytics
> Pipeline de engenharia, governança e análise de Big Data em nuvem a custo zero (Aiven Free Tier),
> com análise interseccional de **raça/cor × idade × território** sobre a saúde de mulheres gestantes
> e puérperas no Brasil. Alinhado à **ODS 5 (Igualdade de Gênero)** e à **ODS 18 (Igualdade Étnico-Racial)**.

| Item | Onde |
|---|---|
| Código do ETL (extração, limpeza, regras de negócio, carga) | [`etl/`](etl/) |
| Infraestrutura como Código (Terraform + Aiven) | [`terraform/`](terraform/) |
| Dashboard interativo (Streamlit) | [`dashboard/`](dashboard/) |
| Agendamento / CI | [`.github/workflows/`](.github/workflows/) |
| Dashboard online | **<https://painel-mortalidade-materna-wxkg6vbjkxbndxteouxuyc.streamlit.app/>** |

---

## Sumário
1. [Entendimento do negócio e escopo](#1-entendimento-do-negócio-e-escopo)
2. [Arquitetura da solução](#2-arquitetura-da-solução)
3. [Análise dos 5 V's](#3-análise-dos-5-vs-aplicada-ao-dataset)
4. [Classificação dos tipos de dados](#4-classificação-dos-tipos-de-dados)
5. [Aspectos legais: LGPD e dados abertos](#5-aspectos-legais-lgpd-e-dados-abertos)
6. [Ingestão e ETL](#6-ingestão-e-etl)
7. [Modelagem e escolha dos bancos](#7-modelagem-e-justificativa-da-escolha-dos-bancos)
8. [Dicionário de dados](#8-dicionário-de-dados)
9. [Regras de negócio](#9-regras-de-negócio)
10. [Dashboard](#10-dashboard-dinâmico)
11. [Segurança da informação](#11-segurança-da-informação)
12. [Guia de reprodução (Deployment Guide)](#12-guia-de-reprodução-deployment-guide)
13. [Roteiro do pitch (10 min)](#13-roteiro-sugerido-para-o-pitch-de-10-minutos)
14. [Limitações e referências](#14-limitações-e-referências)

---

## 1. Entendimento do negócio e escopo

**Problema.** A morte materna é considerada evitável em mais de 90% dos casos. O Brasil se comprometeu
a reduzir a Razão de Mortalidade Materna (RMM) para 30 óbitos por 100 mil nascidos vivos até 2030
(ODS 3.1, meta nacional), mas a média nacional segue bem acima disso e **a desigualdade não é distribuída
ao acaso**: mulheres pretas e indígenas morrem mais, em todas as regiões. A violência obstétrica (práticas
desnecessárias, negligência, desassistência) é parte do mesmo problema, mas não tem um campo próprio nos
sistemas oficiais, então precisa ser observada por **indicadores indiretos (proxies)** de assistência.

**Pergunta interseccional central:** *como o risco de morte materna e a qualidade da assistência ao
pré-natal e ao parto variam quando se cruzam gênero, raça/cor, idade e território?*

Perguntas analíticas que o painel responde:

| # | Pergunta | Métrica(s) |
|---|---|---|
| P1 | Quanto maior é o risco de morte materna de mulheres pretas e indígenas em relação às brancas? | RMM por raça/cor, risco relativo (RN-03, RN-09) |
| P2 | O risco racial é igual em todas as regiões e anos (inclusive na pandemia)? | Heatmap de RR região × ano |
| P3 | Adolescentes e mulheres 40+ de cada raça/cor têm riscos diferentes? | Heatmap raça/cor × faixa etária |
| P4 | Onde estão as cesáreas eletivas em gestações de baixo risco e o pré-natal inadequado? | Proxies de violência obstétrica (RN-07) com drill-down até o município |
| P5 | Do que morrem as gestantes e como isso muda por raça/cor? | Treemap de causas, perfil assistencial (RN-02, RN-06) |
| P6 | Qual o peso das agressões e da morte materna entre mulheres em idade fértil, comparadas aos homens? | Óbitos 10–49 anos por sexo × raça/cor (RN-04) |

**Valor gerado.** Gestores municipais/estaduais e comitês de mortalidade materna conseguem localizar onde
e para quem a assistência falha, priorizando territórios e grupos com sobre-risco. Também serve para
controle social e pesquisa.

**Escopo.** 2019–2024 (bases consolidadas mais recentes; 2025 é preliminar e fica fora por padrão).
Brasil inteiro, por município de residência.

---

## 2. Arquitetura da solução

```mermaid
flowchart TB
    subgraph Fontes["Fontes de dados abertos (governo brasileiro)"]
        CKAN["API CKAN · Portal de Dados Abertos do SUS<br/>(metadados JSON)"]
        SIM["SIM · Mortalidade Geral<br/>CSV zipado ~500 MB/ano"]
        SINASC["SINASC · Nascidos Vivos<br/>CSV zipado ~900 MB/ano"]
        IBGE["API de Localidades do IBGE<br/>(JSON)"]
        CID["Tabela CID-10 DATASUS<br/>(texto)"]
    end

    subgraph ETL["Ingestão & ETL · Python/Pandas (local ou GitHub Actions agendado)"]
        E["extract.py<br/>descoberta via API + download em streaming"]
        T["transform.py<br/>leitura em chunks de 250 mil linhas,<br/>dedup por hash, tipagem, LGPD"]
        R["regras_negocio.py<br/>RN-00 a RN-09"]
        P[("data/processed<br/>Parquet por ano")]
        L["load.py<br/>COPY + upsert idempotente"]
    end

    subgraph Aiven["Aiven (Free Tier) · provisionado por Terraform"]
        PG[("Aiven for PostgreSQL<br/>free-1-1gb<br/>esquema estrela + JSONB + full-text")]
        OS[("Aiven for OpenSearch<br/>free-4-20 (opcional)<br/>documentos JSON / busca textual")]
    end

    subgraph Viz["Visualização"]
        ST["Streamlit Community Cloud<br/>filtros cruzados · seletor de métrica · drill-down"]
    end

    CKAN --> E
    SIM --> E
    SINASC --> E
    IBGE --> E
    CID --> E
    E --> T --> R --> P --> L
    L -->|"avnadmin (escrita)"| PG
    L -->|"_bulk API"| OS
    PG -->|"dashboard_leitor (só SELECT)"| ST
    OS -->|"busca"| ST
    GH["GitHub Actions<br/>cron mensal + CI"] -.-> ETL
    TF["Terraform<br/>main.tf · variables.tf · outputs.tf"] -.-> Aiven
```

Fluxo em uma frase: **a API CKAN diz onde estão os arquivos → o ETL baixa e processa em lotes, aplicando
as regras de negócio → só agregados e registros anonimizados chegam ao PostgreSQL (e ao OpenSearch) →
o Streamlit consulta o banco com um usuário somente leitura.**

### Estrutura do repositório

```
├── etl/
│   ├── config.py            # parâmetros e leitura de credenciais do ambiente
│   ├── dominios.py          # tabelas de código (raça/cor, faixas, escolaridade, grupos de causa…)
│   ├── extract.py           # API CKAN, IBGE, CID-10, download em streaming com retry
│   ├── transform.py         # leitura em chunks, deduplicação, limpeza e agregação (SIM e SINASC)
│   ├── regras_negocio.py    # regras RN-00…RN-09 (funções vetorizadas e testadas)
│   ├── load.py              # DDL, COPY no PostgreSQL, GRANTs, controle de volume, OpenSearch
│   ├── pipeline.py          # orquestrador (CLI)
│   ├── sql/schema.sql       # esquema estrela (tabelas, chaves, CHECKs, índices)
│   ├── sql/views.sql        # regras de negócio em SQL (RMM, risco relativo, indicadores)
│   └── tests/               # testes unitários das regras (pytest)
├── terraform/
│   ├── main.tf              # provider Aiven, PostgreSQL, banco, usuário leitor, OpenSearch, .env
│   ├── variables.tf
│   ├── outputs.tf
│   └── terraform.tfvars.example
├── dashboard/
│   ├── app.py               # aplicação Streamlit (6 abas)
│   ├── dados.py             # consultas SQL parametrizadas + busca OpenSearch
│   ├── metricas.py          # catálogo de métricas e paleta de cores
│   └── requirements.txt
├── .github/workflows/
│   ├── etl.yml              # ETL agendado (batch mensal, incremental)
│   └── ci.yml               # testes, terraform validate, varredura de segredos (gitleaks)
├── .streamlit/config.toml   # tema do painel
├── .env.example             # modelo de variáveis de ambiente (sem segredos)
└── requirements.txt         # dependências do ETL
```

---

## 3. Análise dos 5 V's aplicada ao dataset

| V | Como aparece neste projeto | Decisão de engenharia |
|---|---|---|
| **Volume** | 6 anos × (SIM ≈ 1,35–1,8 milhão de óbitos/ano + SINASC ≈ 2,4–2,8 milhões de nascimentos/ano) ≈ **25 milhões de registros**, ~8 GB de CSV descompactado (≈ 1,2 GB zipado). O PostgreSQL gratuito tem **1 GB**. | Leitura **em chunks direto do .zip** (nunca descompacta em disco), seleção só das colunas necessárias e **agregação no ETL** (grão ano × município × raça/cor × faixa etária). Resultado: o banco inteiro ocupa 158 MB (15% do limite). `load.verificar_tamanho()` mede o banco a cada carga e alerta acima de 80%. Amostragem controlada opcional (`ETL_AMOSTRA`) para testes rápidos. |
| **Variedade** | CSV tabular (SIM/SINASC), JSON da API CKAN e da API do IBGE, campos multivalorados codificados em texto (`*O149*R571`), descrições textuais da CID-10. | Cada formato tem um tratamento próprio (seção 4). JSON de metadados vai para coluna **JSONB**; a cadeia de causas vira **JSONB** e documento aninhado no **OpenSearch**; texto vira índice **full-text**. |
| **Velocidade** | As bases são publicadas uma vez por ano e **revisadas** ao longo do tempo (óbitos investigados mudam de causa). | Processamento em **lote (batch)** agendado no GitHub Actions (todo dia 5). Modo `--incremental` compara o `last_modified` do recurso na API CKAN com a última carga e só reprocessa o que mudou. Carga idempotente por ano. |
| **Veracidade** | Campos ignorados (raça/cor da mãe ignorada em 1,9% a 3,5% dos nascimentos, conforme o ano), códigos fora do dicionário, municípios inexistentes, linhas duplicadas, bases preliminares. | Deduplicação por hash entre chunks, normalização de códigos (inválido → "9 Ignorado"), validação do município contra o IBGE, rejeição de bases preliminares, **denominadores válidos** por indicador, `CHECK`s no banco (numerador ≤ denominador), relatório de qualidade por execução gravado em `etl_execucao` e exibido no painel. |
| **Valor** | Indicadores interseccionais acionáveis: RMM e risco relativo por raça/cor, proxies de violência obstétrica, causas evitáveis. | 4+ KPIs principais, 17 métricas selecionáveis, drill-down até o município (ver seção 10). |

Volumes reais processados (saída do ETL):

| Ano | Óbitos lidos (SIM) | Nascidos vivos (SINASC) | Óbitos maternos (RMM) | Óbitos maternos tardios | RMM Brasil |
|---|---:|---:|---:|---:|---:|
| 2019 | 1.349.801 | 2.849.118 | 1.563 | 165 | 54,9 |
| 2020 | 1.556.824 | 2.730.129 | 1.965 | 182 | 72,0 |
| 2021 | 1.832.649 | 2.677.087 | 3.029 | 379 | 113,1 |
| 2022 | 1.544.266 | 2.561.906 | 1.370 | 270 | 53,5 |
| 2023 | 1.465.610 | 2.537.554 | 1.324 | 280 | 52,2 |
| 2024 | 1.527.369 | 2.389.316 | 1.305 | 248 | 54,6 |
| **Total** | **9.276.519** | **15.745.110** | **10.556** | **1.524** | **67,0** |

Deduplicação: 112 linhas repetidas removidas no SIM e 105 no SINASC. Nenhum registro precisou ser descartado
por residência inválida; ~2.500 óbitos/ano tinham município inexistente e foram reatribuídos ao
"município ignorado" da UF (RN-08).

Resultado no banco: `fato_saude_materna` 591.526 linhas (126 MB com índices), `fato_obito_materno` 12.080
linhas (13 MB), `fato_obito_idade_reprodutiva` 70.885 linhas (8 MB). **Banco total: 158 MB = 15% do limite
de 1 GB.** Tempo de processamento: ~3 min por ano.

### Principais achados (2019–2024, Brasil)

* **Desigualdade racial persistente na morte materna.** RMM de mulheres **indígenas: 121,9** e **pretas:
  113,5** por 100 mil nascidos vivos, contra **63,8 das brancas** — risco relativo de **1,91×** e **1,78×**.
* **A pandemia agravou a desigualdade.** Em 2021 a RMM nacional chegou a 113,1 (o dobro de 2019). Entre
  mulheres pretas foi a 195,9.
* **Duas faces da violência obstétrica.** Mulheres **brancas** têm mais cesáreas eletivas em gestações de
  baixo risco (30,5%, contra 18,2% das pretas e 5,5% das indígenas), sinal de **excesso de intervenção**.
  Mulheres **pretas, pardas e indígenas** têm mais **pré-natal inadequado** (20,8%, 19,8% e 38,9%, contra
  12,0% das brancas) e mais **óbitos sem assistência médica**, sinal de **desassistência**. Entre indígenas,
  16,9% dos partos acontecem fora de estabelecimento de saúde.
* **Gênero e violência.** 18.155 mulheres de 10 a 49 anos foram mortas por agressão no período (70% delas
  negras); **528 estavam grávidas ou no puerpério**.
* **Causas evitáveis.** Entre as causas obstétricas diretas, as síndromes hipertensivas (1.875 óbitos) e as
  hemorragias (1.074) lideram: ambas são evitáveis com pré-natal e assistência ao parto adequados.

---

## 4. Classificação dos tipos de dados

| Dado | Tipo | Origem / formato | Tratamento |
|---|---|---|---|
| Microdados do SIM e do SINASC | **Estruturado** | CSV `;` (latin-1) dentro de .zip | Pandas em chunks → tabelas fato relacionais |
| Metadados dos conjuntos de dados (licença, datas de modificação, URLs) | **Semi-estruturado** | JSON da API CKAN (`package_show`) | Guardado em `data/raw/metadata/*.json` e na coluna `etl_execucao.fonte` (**JSONB**); usado no modo incremental |
| Municípios, UFs e regiões | **Semi-estruturado** | JSON da API de Localidades do IBGE | Normalizado em `dim_localidade` |
| Cadeia de causas da Declaração de Óbito (linhas A, B, C, D e parte II) | **Semi-estruturado** | Texto com padrão (`*O159*R571`), multivalorado | Convertido para lista de CIDs (RN-05) → coluna **JSONB** com índice GIN e objeto aninhado no OpenSearch |
| Descrições das causas (CID-10) | **Não estruturado** (texto livre em português) | CSV do DATASUS | Concatenadas em `texto_causas` → índice **full-text** (`tsvector` português sem acentos) e campo `text` com analisador `brazilian` no OpenSearch |
| Dicionário de dados do SIM (PDF) | **Não estruturado** | PDF publicado no CKAN | Usado como referência humana para os domínios em `dominios.py` |

---

## 5. Aspectos legais: LGPD e dados abertos

* **Licença:** SIM e SINASC são publicados no Portal de Dados Abertos do SUS sob **CC-BY** (atribuição),
  já **anonimizados** pelo Ministério da Saúde (sem nome, CPF, endereço ou número da declaração).
* **Base legal:** dados de saúde são **dados pessoais sensíveis** (LGPD art. 5º, II). O tratamento para
  estudo por órgão de pesquisa e para políticas públicas é previsto nos arts. 7º, IV; 11, II, "b" e "c";
  e o art. 7º, §§ 3º e 4º, permite tratar dados tornados públicos respeitando a finalidade e a boa-fé.
  Dados anonimizados não são dados pessoais (art. 12), **desde que a reidentificação não seja razoável**.
* **O que o projeto faz para reduzir o risco de reidentificação** (dados de saúde de pequenos municípios
  podem ser reidentificáveis por combinação de atributos):
  1. **Minimização (art. 6º, III):** das ~90 colunas do SIM e ~60 do SINASC, só as necessárias seguem no
     pipeline. Datas exatas (nascimento, óbito, cadastro), estabelecimento de saúde (CNES), ocupação,
     naturalidade e horário **só existem em memória** durante o cálculo do hash de deduplicação e são
     descartadas no mesmo bloco. **Nada disso é gravado.**
  2. **Generalização:** idade exata → faixa quinquenal; data → ano; nos registros individuais de óbito
     materno, município → **apenas UF**.
  3. **Agregação:** nascimentos e óbitos do município só existem como **contagens agregadas**.
  4. **Identificador não reversível:** `id_obito` é um hash de 64 bits da linha, não o número da DO.
  5. **Alerta de células pequenas:** o painel avisa quando o recorte tem menos de 20 óbitos e oculta, por
     padrão, municípios com menos de 1.000 nascidos vivos no drill-down.
* **Atribuição:** as fontes são citadas no painel e neste README.

---

## 6. Ingestão e ETL

```
python -m etl.pipeline --anos 2019-2024 [--incremental] [--aceitar-preliminar] [--sem-banco] [--sem-opensearch]
```

Para cada ano o orquestrador ([`etl/pipeline.py`](etl/pipeline.py)):

1. **Descobre** o recurso CSV do ano via `GET /api/3/action/package_show` (CKAN) e rejeita bases
   "preliminares" (salvo `--aceitar-preliminar`).
2. **Baixa** em streaming (blocos de 8 MB, retry exponencial, cache local por tamanho) e calcula SHA-256.
3. **Transforma** ([`etl/transform.py`](etl/transform.py)) lendo o CSV de dentro do zip em blocos de 250 mil
   linhas. Em cada bloco: padroniza nomes de colunas → remove duplicatas (hash 64 bits, também entre
   blocos) → amostragem opcional → descarta colunas não usadas (LGPD) → converte tipos e normaliza códigos
   → valida município → aplica as regras de negócio → agrega.
4. **Integra** SIM e SINASC na mesma fato (numerador e denominador da RMM lado a lado).
5. **Persiste** a camada *processed* em Parquet (`data/processed/<tabela>/ano=AAAA.parquet`).
6. **Carrega** no PostgreSQL numa transação por ano: `DELETE` do ano + `COPY` (idempotente).
7. **Registra** a execução e o relatório de qualidade em `etl_execucao` (JSONB).
8. Ao final: recria as views, aplica `GRANT SELECT` ao usuário do dashboard, mede o tamanho do banco e
   indexa os óbitos maternos no OpenSearch.

Desempenho medido (notebook comum): **~2,5 a 3 min por ano** (SIM + SINASC), com uso de memória limitado
pelo tamanho do chunk.

---

## 7. Modelagem e justificativa da escolha dos bancos

### Esquema estrela (PostgreSQL)

```mermaid
erDiagram
    dim_tempo ||--o{ fato_saude_materna : ano
    dim_localidade ||--o{ fato_saude_materna : cod_municipio
    dim_raca_cor ||--o{ fato_saude_materna : cod_raca_cor
    dim_faixa_etaria ||--o{ fato_saude_materna : cod_faixa_etaria

    dim_tempo ||--o{ fato_obito_materno : ano
    dim_raca_cor ||--o{ fato_obito_materno : cod_raca_cor
    dim_faixa_etaria ||--o{ fato_obito_materno : cod_faixa_etaria
    dim_escolaridade ||--o{ fato_obito_materno : cod_escolaridade
    dim_tipo_obstetrico ||--o{ fato_obito_materno : tipo_obstetrico
    dim_grupo_causa_materna ||--o{ fato_obito_materno : grupo_causa

    dim_tempo ||--o{ fato_obito_idade_reprodutiva : ano
    dim_sexo ||--o{ fato_obito_idade_reprodutiva : cod_sexo
    dim_raca_cor ||--o{ fato_obito_idade_reprodutiva : cod_raca_cor
    dim_faixa_etaria ||--o{ fato_obito_idade_reprodutiva : cod_faixa_etaria
    dim_grupo_causa_geral ||--o{ fato_obito_idade_reprodutiva : cod_grupo_causa

    fato_saude_materna {
        smallint ano PK
        char6 cod_municipio PK
        varchar cod_raca_cor PK
        varchar cod_faixa_etaria PK
        int nascidos_vivos
        int obitos_maternos
        int "22 outras medidas"
    }
    fato_obito_materno {
        text id_obito PK
        smallint ano
        char2 cod_uf
        varchar causa_basica
        jsonb cadeia_causas
        tsvector tsv_causas
    }
    fato_obito_idade_reprodutiva {
        smallint ano PK
        char2 cod_uf PK
        varchar cod_sexo PK
        text cod_grupo_causa PK
        int n_obitos
    }
```

Três fatos com grãos diferentes, cada um respondendo a um tipo de pergunta:

| Fato | Grão | Para quê |
|---|---|---|
| `fato_saude_materna` | ano × município × raça/cor × faixa etária | RMM e todos os indicadores obstétricos, drill-down territorial |
| `fato_obito_materno` | 1 linha por morte materna (anonimizada) | Causas, perfil assistencial, busca textual |
| `fato_obito_idade_reprodutiva` | ano × UF × sexo × raça/cor × faixa × grupo de causa | Comparação de gênero (homens × mulheres) |

Otimizações para **Veracidade** e **leitura**: chaves primárias compostas (impedem duplicação), chaves
estrangeiras para todas as dimensões, `CHECK`s de consistência (numerador ≤ denominador), coluna gerada
`cod_uf` indexada, índices compostos `(cod_uf, ano)` e `(cod_raca_cor, ano)`, índice **GIN** em JSONB
(`jsonb_path_ops`) e em `tsvector`.

### Por que relacional **e** não relacional?

| Critério | PostgreSQL (relacional) | OpenSearch (não relacional) |
|---|---|---|
| Natureza do dado | Fatos e dimensões com estrutura fixa e chaves bem definidas | Documentos JSON com listas aninhadas (cadeia de causas) e texto livre |
| Consulta típica | `SUM` + `GROUP BY` com filtros combinados (razões, taxas) | Busca por palavra ("hemorragia", "eclâmpsia") com relevância e agregação por facetas |
| Integridade | FKs, PKs, `CHECK`s, transações ACID → **Veracidade** | Esquema flexível; consistência eventual é aceitável para busca |
| Free tier Aiven | `free-1-1gb` (1 GB) — cabe com folga após agregação | `free-4-20` |
| Papel no projeto | **Fonte da verdade** de todas as métricas | **Índice de busca** derivado do PostgreSQL (pode ser recriado a qualquer momento) |

O OpenSearch é **opcional** (como no guia): `habilitar_opensearch = false` no Terraform desliga o serviço
e o painel passa a usar a busca full-text do próprio PostgreSQL (`tsvector`), sem perder funcionalidade.

---

## 8. Dicionário de dados

Esquema `saude_materna`. Códigos seguem os dicionários oficiais do SIM e do SINASC.

### `fato_saude_materna`

| Coluna | Tipo | Origem | Descrição |
|---|---|---|---|
| `ano` | smallint | arquivo | Ano de registro (FK `dim_tempo`) |
| `cod_municipio` | char(6) | `CODMUNRES` | Município de residência, código IBGE sem dígito verificador (FK `dim_localidade`) |
| `cod_raca_cor` | varchar(1) | SIM `RACACOR` / SINASC `RACACORMAE` | Raça/cor da mulher (FK `dim_raca_cor`) |
| `cod_faixa_etaria` | varchar(5) | SIM `IDADE` / SINASC `IDADEMAE` | Faixa etária da mulher (FK `dim_faixa_etaria`) |
| `cod_uf` | char(2) | gerada | 2 primeiros dígitos do município (coluna gerada e indexada) |
| `nascidos_vivos` | int | SINASC | Total de nascidos vivos |
| `partos_info_valida` / `partos_cesareos` | int | `PARTO` | Partos com tipo informado / cesáreos |
| `robson_classificados` | int | `TPROBSON` | Nascimentos com grupo de Robson 1–10 |
| `robson1_total` / `robson1_cesareas` | int | `TPROBSON`, `PARTO` | Grupo 1 de Robson / cesáreas nesse grupo |
| `baixo_risco_total` | int | `TPROBSON` | Grupos 1 a 4 de Robson |
| `cesareas_eletivas_baixo_risco` | int | `TPROBSON`, `PARTO`, `STCESPARTO` | Cesárea antes do trabalho de parto nos grupos 1–4 |
| `prenatal_classificado` / `prenatal_inadequado` | int | `KOTELCHUCK` | Índice informado (1–5) / não realizou ou inadequado (1–2) |
| `consultas_info_valida` / `menos_7_consultas` | int | `CONSULTAS` | Faixa de consultas informada / menos de 7 consultas |
| `inicio_prenatal_valido` / `inicio_prenatal_tardio` | int | `MESPRENAT` | Mês de início informado / início após o 3º mês |
| `local_info_valida` / `partos_fora_estabelecimento` | int | `LOCNASC` | Local informado / domicílio ou outros |
| `apgar5_valido` / `apgar5_baixo` | int | `APGAR5` | Apgar informado / Apgar < 7 |
| `gestacao_valida` / `prematuros` | int | `SEMAGESTAC`, `GESTACAO` | Idade gestacional informada / < 37 semanas |
| `peso_valido` / `baixo_peso` | int | `PESO` | Peso plausível (300–6.500 g) / < 2.500 g |
| `obitos_maternos` | int | SIM | Mortes maternas que entram na RMM (RN-03) |
| `obitos_maternos_diretos` / `_indiretos` / `_tardios` | int | SIM | Por tipo obstétrico (RN-02) |
| `obitos_sem_assistencia` | int | `ASSISTMED` = 2 | Morte materna sem assistência médica |
| `obitos_fora_estabelecimento` | int | `LOCOCOR` ∈ {3,4,5} | Morte materna em domicílio, via pública ou outros |
| `obitos_investigados` | int | `FONTEINV` ∈ 1–8 | Morte materna investigada |

### `fato_obito_materno`

| Coluna | Tipo | Origem | Descrição |
|---|---|---|---|
| `id_obito` | text | hash | `ANO-hash64` da linha original (não reversível) |
| `ano`, `cod_uf` | | `CODMUNRES` | Ano e **UF** de residência (generalização LGPD) |
| `cod_raca_cor`, `cod_faixa_etaria`, `cod_escolaridade` | | `RACACOR`, `IDADE`, `ESC2010` | Perfil sociodemográfico |
| `causa_basica` / `causa_basica_descricao` | varchar(4) / text | `CAUSABAS` + CID-10 | Causa básica e descrição |
| `tipo_obstetrico` | text | RN-02 | direta, indireta, não especificada, tardia |
| `grupo_causa` | text | RN-02 | aborto, hipertensão, hemorragia, infecção… |
| `cod_momento_obito` | varchar(1) | `TPMORTEOCO` | Gravidez, parto, abortamento, até 42 dias… |
| `cod_local_ocorrencia` | varchar(1) | `LOCOCOR` | Hospital, domicílio, via pública… |
| `cod_assistencia_medica`, `cod_necropsia` | varchar(1) | `ASSISTMED`, `NECROPSIA` | Sim / Não / Ignorado |
| `investigado` | boolean | `FONTEINV` | Óbito investigado pela vigilância |
| `cadeia_causas` | **jsonb** | `LINHAA…LINHAII` | `{"a":["O159"],"b":["O149","R571"],"c":[],"d":[],"ii":[]}` |
| `texto_causas` | text | CID-10 | Descrições concatenadas (busca textual) |
| `tsv_causas` | tsvector (gerada) | | Índice full-text em português, sem acentos |

### `fato_obito_idade_reprodutiva`

| Coluna | Descrição |
|---|---|
| `ano`, `cod_uf`, `cod_sexo`, `cod_raca_cor`, `cod_faixa_etaria` | Dimensões (10 a 49 anos, sexo masculino/feminino) |
| `cod_grupo_causa` | Grupo de causa geral (RN-04) |
| `n_obitos` | Número de óbitos |
| `n_gestante_puerpera` | Óbitos de mulheres grávidas ou puérperas (`OBITOGRAV`=1 ou `OBITOPUERP`∈{1,2}) |

### Dimensões e controle

| Tabela | Conteúdo |
|---|---|
| `dim_tempo` | ano, período (pré-pandemia / pandemia / pós-pandemia), flag de base preliminar |
| `dim_localidade` | 5.571 municípios do IBGE + 27 linhas "Município ignorado – UF" |
| `dim_raca_cor` | 1 Branca, 2 Preta, 3 Amarela, 4 Parda, 5 Indígena, 9 Ignorada + `grupo_ibge` (Negra = Preta + Parda) |
| `dim_faixa_etaria` | <10, 10–14, 15–19, …, 45–49, 50+, IGN (com ordem) |
| `dim_escolaridade` | 0 Sem escolaridade … 5 Superior completo, 9 Ignorada |
| `dim_sexo` | 1 Masculino, 2 Feminino, 9 Ignorado |
| `dim_tipo_obstetrico` | tipo + `entra_rmm` |
| `dim_grupo_causa_materna` | grupo + descrição + intervalo de CIDs |
| `dim_grupo_causa_geral` | materna, COVID-19, agressão, suicídio, transporte, … |
| `dim_dominio` | domínios pequenos do SIM (momento do óbito, local de ocorrência, sim/não) |
| `dim_cid10` | ~14 mil códigos CID-10 com descrição |
| `etl_execucao` | log de cada carga: status, fração de amostra, `relatorio` (JSONB de qualidade), `fonte` (JSONB do CKAN) |

Views de negócio: `vw_fato_saude_materna`, `vw_rmm_uf_raca`, `vw_risco_relativo_racial`,
`vw_indicadores_obstetricos`, `vw_obito_materno_detalhado`, `vw_qualidade_ultima_carga`, `vw_uf`.

---

## 9. Regras de negócio

Todas implementadas em [`etl/regras_negocio.py`](etl/regras_negocio.py) (com testes em
[`etl/tests/`](etl/tests/)) e, para as métricas, também em SQL em [`etl/sql/views.sql`](etl/sql/views.sql).

| Código | Regra | Lógica |
|---|---|---|
| **RN-00** | Padronização e tipagem | Colunas em `snake_case` minúsculo; códigos fora do dicionário → `9` (Ignorado); texto → inteiro com faixa plausível (fora → nulo); `IDADE` do SIM decodificada (1º dígito = unidade: `4`=anos, `5`=100+); datas `DDMMAAAA` → ano |
| **RN-01** | Faixa etária | Idade em anos → faixas quinquenais 10–14 … 45–49, 50+, IGN |
| **RN-02** | Classificação da morte materna | Pré-condição: óbito não fetal e sexo feminino. **Direta:** O00–O92 (exceto indiretas) + A34; F53, M83, D39.2 e E23.0 só com vínculo gestacional declarado. **Indireta:** O10, O24 (exceto O24.4), O25, O98, O99. **Não especificada:** O95. **Tardia:** O96–O97. Grupos: aborto (O00–O08), hipertensão (O10–O16), hemorragia (O20, O44–O46, O67, O72), infecção (O85–O86) etc. |
| **RN-03** | **Razão de Mortalidade Materna** | `RMM = (diretas + indiretas + não especificadas) ÷ nascidos vivos × 100.000`. Tardias **não** entram. Sempre razão de somas, nunca média de razões. |
| **RN-04** | Grupo de causa geral (10–49 anos) | materna → COVID-19 (B34.2/U07) → agressão (X85–Y09) → suicídio (X60–X84) → transporte (V01–V99) → outras externas → neoplasias → circulatório → infecciosas → demais |
| **RN-05** | Cadeia de causas | `*O159*R571` → `["O159","R571"]` por linha da DO (A, B, C, D, II); sufixo `X` de 3 caracteres removido |
| **RN-06** | Assistência ao óbito materno | sem assistência (`ASSISTMED`=2); fora de estabelecimento (`LOCOCOR`∈{3,4,5}); investigado (`FONTEINV`∈1–8) |
| **RN-07** | Proxies de violência obstétrica / assistência | Cesárea (`PARTO`=2) ÷ partos informados; cesárea no **Robson 1**; **cesárea eletiva em baixo risco** = Robson 1–4 ∧ cesárea ∧ `STCESPARTO`=1 (antes do trabalho de parto) ÷ Robson 1–4; **pré-natal inadequado** = Kotelchuck 1–2 ÷ 1–5; < 7 consultas; início após 3º mês; parto em domicílio/outros; Apgar5 < 7; prematuro; baixo peso. **Registros com informação ignorada saem só do denominador daquele indicador**, nunca do total de nascidos vivos. |
| **RN-08** | Validação do município | Código existe no IBGE → mantém; não existe mas a UF é válida → `UU0000` (município ignorado da UF); UF inválida/exterior → descarta e contabiliza |
| **RN-09** | **Risco relativo racial** | `RR = RMM(grupo) ÷ RMM(brancas)`. Grupos: pretas, negras (pretas + pardas), pardas, indígenas. RR > 1 = sobre-risco |
| **RN-10** | Veracidade | Dedup por hash entre chunks; base preliminar rejeitada por padrão; `CHECK`s no banco; alerta < 20 óbitos; mínimo de nascidos vivos no drill-down municipal |

---

## 10. Dashboard dinâmico

[`dashboard/app.py`](dashboard/app.py) · Streamlit + Plotly · consultas agregadas executadas no PostgreSQL.

**KPIs (6):** RMM (com variação anual), risco relativo pretas × brancas, risco relativo indígenas ×
brancas, cesárea eletiva em baixo risco, pré-natal inadequado, óbitos maternos sem assistência médica.

| Requisito do guia | Como foi atendido |
|---|---|
| ≥ 4 KPIs focados no problema interseccional | 6 KPIs no topo + 3 KPIs de gênero na aba Gênero |
| Filtros dinâmicos cruzados (Ano, Estado/Região, Sexo, Raça/Cor, Faixa Etária) | Barra lateral: período, região → UF (cascata), raça/cor, agrupar Negra, faixa etária, sexo. **Todos os filtros afetam todas as abas e KPIs ao mesmo tempo** |
| Seletor que alterna a métrica analisada | Seletor com **17 métricas** (RMM, taxas de cesárea, pré-natal, Apgar, óbitos sem assistência…) nas abas Evolução, Drill-down e Interseccionalidade; "Nº × %" na aba Gênero |
| Drill-down / detalhamento por segmento | **Brasil → Região → UF → Município clicando na barra** (com breadcrumb), detalhamento por raça/cor do segmento, treemap tipo → grupo → CID clicável, tabela de registros por grupo de causa |
| Alteração de eixos/quebras em tempo real | "Comparar por" raça/cor, faixa etária ou região; perfil assistencial alternável |

Abas: **Evolução** · **Drill-down territorial** · **Interseccionalidade** (heatmap raça × idade e mapa de
calor de risco relativo região × ano) · **Causas dos óbitos** (treemap, perfil, busca textual OpenSearch)
· **Gênero (10–49 anos)** · **Qualidade & método** (relatório de cada carga).

Boas práticas de visualização: cores fixas por grupo (não mudam ao filtrar), paleta testada para
daltonismo, escala sequencial de uma só cor para magnitudes, escala divergente com ponto neutro em RR = 1,
tabela de dados disponível em cada gráfico.

---

## 11. Segurança da informação

* **Nenhum segredo no repositório.** Token da Aiven via `TF_VAR_aiven_api_token`; URIs de banco via `.env`
  (local), *Secrets* do GitHub Actions (ETL) e *Secrets* do Streamlit Cloud (dashboard). `.gitignore`
  cobre `.env`, `secrets.toml`, `terraform.tfvars` e **`*.tfstate`** (o state contém senhas).
* **Menor privilégio:** o Terraform cria o usuário `dashboard_leitor`; o ETL concede apenas
  `USAGE` + `SELECT`. O dashboard **não consegue** alterar dados (testado: `DELETE` → *permission denied*).
* **TLS obrigatório** (`sslmode=require`) em todas as conexões com a Aiven.
* **SQL parametrizado** no dashboard; nomes de colunas/dimensões vêm de *whitelist*.
* **Varredura de segredos** (gitleaks) em cada push no CI.
* Senha do usuário leitor gerada pelo Terraform (`random_password`, 32 caracteres).

---

## 12. Guia de reprodução (Deployment Guide)

### Pré-requisitos
* Python 3.12+ · Terraform 1.6+ · Git · conta gratuita na [Aiven](https://console.aiven.io) e no
  [Streamlit Community Cloud](https://share.streamlit.io).

### Passo 1 — Clonar e instalar
```bash
git clone https://github.com/GustavoCruzzz/painel-mortalidade-materna.git
cd painel-mortalidade-materna
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r dashboard/requirements.txt
pytest etl/tests -q                  # 25 testes das regras de negócio
```

### Passo 2 — Token da Aiven
Console Aiven → ícone do usuário → **Tokens** → *Generate token*. Anote também o nome do seu projeto.
```bash
export TF_VAR_aiven_api_token="<token>"     # PowerShell: $env:TF_VAR_aiven_api_token="<token>"
export TF_VAR_aiven_project="<nome-do-projeto>"
```

### Passo 3 — Provisionar a infraestrutura (Terraform)
```bash
cd terraform
terraform init
terraform plan          # mostra: aiven_pg, aiven_pg_database, aiven_pg_user, aiven_opensearch, local_sensitive_file
terraform apply         # ~5–10 min até os serviços ficarem RUNNING
cd ..
```
O `apply` cria o arquivo `.env` na raiz com `DATABASE_URL`, `DASHBOARD_DATABASE_URL` e `OPENSEARCH_URL`.
Para ver os valores: `terraform output -raw database_url_etl`.
Sem OpenSearch: `terraform apply -var="habilitar_opensearch=false"`.

### Passo 4 — Rodar o ETL (carga inicial)
```bash
python -m etl.pipeline --anos 2019-2024      # ~20 min; baixa ~1,2 GB em data/raw (fora do Git)
# teste rápido: ETL_AMOSTRA=0.1 python -m etl.pipeline --anos 2023
```
Ao final o log mostra o tamanho do banco (deve ficar bem abaixo de 1 GB).

### Passo 5 — Rodar o dashboard localmente
```bash
streamlit run dashboard/app.py     # lê DASHBOARD_DATABASE_URL do .env
```

### Passo 6 — Publicar
1. Suba o repositório no GitHub (confira que `.env` e `*.tfstate` **não** aparecem em `git status`).
2. **GitHub → Settings → Secrets and variables → Actions:** crie `DATABASE_URL`, `DASHBOARD_DB_USER`
   (= `dashboard_leitor`) e `OPENSEARCH_URL`. O workflow `ETL agendado` passa a rodar todo mês
   (ou manualmente em *Actions → Run workflow*).
3. **Streamlit Cloud → New app:** repositório, branch `main`, arquivo `dashboard/app.py`.
   Em *Advanced settings → Secrets* cole o conteúdo de `.streamlit/secrets.toml.example` preenchido
   com `terraform output -raw database_url_dashboard` (e `opensearch_url`).
4. Atualize o link do dashboard no topo deste README.

### Destruir tudo
```bash
cd terraform && terraform destroy
```

---

## 13. Roteiro sugerido para o pitch de 10 minutos

| Tempo | Conteúdo | O que mostrar |
|---|---|---|
| 0:00–1:30 | Problema e ODS 5/18 | KPI de RMM e risco relativo de mulheres pretas e indígenas |
| 1:30–3:00 | Arquitetura e 5 V's | Diagrama da seção 2; volumes da seção 3 |
| 3:00–4:30 | Terraform | `terraform plan` / `apply` e serviços no console Aiven |
| 4:30–6:00 | ETL e regras de negócio | Log do pipeline (chunks, dedup, relatório de qualidade); `regras_negocio.py` RN-02/RN-03/RN-07 |
| 6:00–9:00 | Dashboard ao vivo | Filtrar Nordeste + pretas; trocar a métrica para cesárea eletiva; drill-down até um município; heatmap de RR; busca "hemorragia" |
| 9:00–10:00 | LGPD, segurança e conclusões | Seção 5 e 11; achados principais |

---

## 14. Limitações e referências

**Limitações**
* Violência obstétrica não é registrada diretamente nos sistemas; os indicadores são **proxies** de
  assistência (procedimentos sem indicação, desassistência), não diagnósticos de violência.
* Raça/cor do numerador (DO, geralmente informada por terceiros) e do denominador (DNV, informada pela mãe)
  vêm de fontes diferentes; existe subnotificação e classificação ignorada (apresentada na aba Qualidade).
* RMM baseada só em dados diretos do SIM, sem fator de correção do Ministério da Saúde (que estima
  sub-registro); os valores são, portanto, um **limite inferior**.
* Municípios pequenos têm taxas instáveis; o painel aplica mínimo de nascidos vivos e alerta de células
  pequenas.

**Referências**
* Ministério da Saúde. *Guia de Vigilância Epidemiológica do Óbito Materno*. Brasília, 2009.
* Ministério da Saúde. Portal de Dados Abertos do SUS — SIM e SINASC; dicionários de dados.
* OMS. *Robson Classification: Implementation Manual*, 2017.
* Kotelchuck M. An evaluation of the Kessner Adequacy of Prenatal Care Index. *AJPH*, 1994.
* IBGE. API de Localidades. · DATASUS. Tabela CID-10.
* Lei nº 13.709/2018 (LGPD).
