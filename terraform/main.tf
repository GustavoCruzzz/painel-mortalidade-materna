# =============================================================================
# Infraestrutura como Código — camada de dados na Aiven (Free Tier)
#
#   terraform init
#   terraform plan
#   terraform apply
#
# O token da Aiven NUNCA fica neste arquivo: exporte TF_VAR_aiven_api_token
# (ou use terraform.tfvars, que está no .gitignore).
# =============================================================================

terraform {
  required_version = ">= 1.6"

  required_providers {
    aiven = {
      source  = "aiven/aiven"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }
}

provider "aiven" {
  api_token = var.aiven_api_token
}

# Projeto já existente na conta Aiven (contas gratuitas já vêm com um projeto)
data "aiven_project" "projeto" {
  project = var.aiven_project
}

# -----------------------------------------------------------------------------
# Banco RELACIONAL — Aiven for PostgreSQL (plano gratuito: 1 CPU, 1 GB RAM, 1 GB disco)
# Armazena o esquema estrela (dimensões + fatos) usado pelo dashboard.
# -----------------------------------------------------------------------------
resource "aiven_pg" "pg" {
  project      = data.aiven_project.projeto.project
  service_name = "${var.prefixo}-pg"
  plan         = var.plano_postgres
  cloud_name   = var.cloud_name

  # Serviços free ficam na Internet pública com TLS obrigatório (sslmode=require),
  # o que permite a conexão do Streamlit Cloud e do GitHub Actions.
  # Configurações avançadas (pg_user_config) não são liberadas no plano gratuito.
  termination_protection = false

  tag {
    key   = "projeto"
    value = "mortalidade-materna-ods5-ods18"
  }

  timeouts {
    create = "20m"
    update = "15m"
  }
}

# Banco lógico dedicado ao projeto
resource "aiven_pg_database" "saude_materna" {
  project       = aiven_pg.pg.project
  service_name  = aiven_pg.pg.service_name
  database_name = var.nome_banco
}

# Usuário SOMENTE LEITURA para o dashboard (princípio do menor privilégio).
# Os GRANTs de SELECT são aplicados pelo ETL (etl/load.py::conceder_leitura).
resource "random_password" "leitor" {
  length  = 32
  special = false
}

resource "aiven_pg_user" "dashboard" {
  project      = aiven_pg.pg.project
  service_name = aiven_pg.pg.service_name
  username     = var.usuario_dashboard
  password     = random_password.leitor.result
}

# -----------------------------------------------------------------------------
# Banco NÃO RELACIONAL — Aiven for OpenSearch (plano gratuito, opcional)
# Índice de documentos JSON com as causas de óbito (busca full-text + agregações).
# Desligue com:  -var="habilitar_opensearch=false"
# -----------------------------------------------------------------------------
resource "aiven_opensearch" "os" {
  count = var.habilitar_opensearch ? 1 : 0

  project                = data.aiven_project.projeto.project
  service_name           = "${var.prefixo}-os"
  plan                   = var.plano_opensearch
  cloud_name             = var.cloud_name_opensearch
  termination_protection = false

  tag {
    key   = "projeto"
    value = "mortalidade-materna-ods5-ods18"
  }

  timeouts {
    create = "20m"
  }
}

# -----------------------------------------------------------------------------
# Gera o arquivo .env local (fora do Git) com as credenciais provisionadas,
# para que o ETL e o dashboard rodem sem que ninguém copie senhas à mão.
# -----------------------------------------------------------------------------
locals {
  pg_admin_uri = replace(
    aiven_pg.pg.service_uri, "/defaultdb", "/${aiven_pg_database.saude_materna.database_name}"
  )
  pg_leitor_uri = format(
    "postgres://%s:%s@%s:%d/%s?sslmode=require",
    aiven_pg_user.dashboard.username,
    random_password.leitor.result,
    aiven_pg.pg.service_host,
    aiven_pg.pg.service_port,
    aiven_pg_database.saude_materna.database_name,
  )
  opensearch_uri = var.habilitar_opensearch ? aiven_opensearch.os[0].service_uri : ""
}

resource "local_sensitive_file" "env" {
  count           = var.gerar_arquivo_env ? 1 : 0
  filename        = "${path.module}/../.env"
  file_permission = "0600"
  content         = <<-EOT
    # Gerado pelo Terraform em ${timestamp()} — NÃO versionar (está no .gitignore)
    DATABASE_URL=${local.pg_admin_uri}
    DASHBOARD_DATABASE_URL=${local.pg_leitor_uri}
    DASHBOARD_DB_USER=${aiven_pg_user.dashboard.username}
    OPENSEARCH_URL=${local.opensearch_uri}
    OPENSEARCH_INDICE=obitos-maternos
  EOT

  lifecycle {
    ignore_changes = [content] # evita recriar o arquivo a cada plan por causa do timestamp
  }
}
