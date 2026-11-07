# Base de dados tratada

Versão **resultante do tratamento**, exportada do Aiven for PostgreSQL (esquema `saude_materna`) depois da
carga de 07/11/2026. É exatamente o que está armazenado no banco e o que o dashboard consulta.

* **Origem:** microdados do SIM e do SINASC 2019–2024 (Portal de Dados Abertos do SUS, licença CC-BY).
  A versão original de cada arquivo (URL, data de publicação, SHA-256) está em
  [`controle/versao_fontes_e_qualidade.json`](controle/versao_fontes_e_qualidade.json).
* **Como foi gerada:** `python -m etl.pipeline --anos 2019-2024` (tratamento e carga) e depois
  `python -m etl.exportar_base_tratada` (esta exportação). O código está em [`../etl/`](../etl/).
* **Integridade:** [`MANIFESTO.json`](MANIFESTO.json) lista linhas, colunas e SHA-256 de cada arquivo.

| Pasta | Conteúdo | Formato |
|---|---|---|
| `fatos/` | As 3 tabelas fato completas | Parquet (zstd) |
| `amostras_csv/` | As 1.000 primeiras linhas de cada fato, para abrir no Excel ou no navegador | CSV UTF-8 |
| `dimensoes/` | As 11 dimensões completas | CSV UTF-8 |
| `controle/` | Versão de cada arquivo de origem e relatório de qualidade de cada carga | JSON |

| Tabela | Linhas | Grão |
|---|---:|---|
| `fato_saude_materna` | 591.526 | ano × município × raça/cor × faixa etária |
| `fato_obito_materno` | 12.080 | uma morte materna, anonimizada |
| `fato_obito_idade_reprodutiva` | 70.885 | ano × UF × sexo × raça/cor × faixa etária × grupo de causa |
| `dim_cid10` | 14.236 | código CID-10 |
| `dim_localidade` | 5.598 | município (5.571 do IBGE + 27 "município ignorado", um por UF) |
| Demais 9 dimensões | 73 | código |

Para ler os Parquet:

```python
import pandas as pd
fato = pd.read_parquet("dados_tratados/fatos/fato_saude_materna.parquet")
```

O dicionário de dados de cada coluna está na seção 10 do [README principal](../README.md#10-dicionário-de-dados).

**LGPD.** Nenhum arquivo traz nome, data exata, município de residência de um óbito individual, número da
Declaração de Óbito ou estabelecimento de saúde. Nascimentos e óbitos por município só aparecem como contagens.
Os registros individuais de morte materna estão generalizados (UF, faixa etária, ano) e identificados por um
hash não reversível. O nível de detalhe é menor que o dos microdados públicos de origem.
