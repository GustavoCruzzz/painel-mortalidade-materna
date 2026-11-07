# =============================================================================
# Variáveis de entrada. Valores sensíveis vêm de variáveis de ambiente
# (TF_VAR_aiven_api_token) ou de terraform.tfvars (ignorado pelo Git).
# =============================================================================

variable "aiven_api_token" {
  description = "Token de API da Aiven (Console > User profile > Tokens). Nunca commitar."
  type        = string
  sensitive   = true
}

variable "aiven_project" {
  description = "Nome do projeto existente na Aiven onde os serviços serão criados."
  type        = string
}

variable "prefixo" {
  description = "Prefixo dos nomes dos serviços (único dentro do projeto)."
  type        = string
  default     = "materna"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.prefixo))
    error_message = "Use letras minúsculas, números e hífen (3 a 31 caracteres)."
  }
}

variable "nome_servico_pg" {
  description = <<-EOT
    Nome de um PostgreSQL que já existe na Aiven (ex.: criado pelo assistente do console).
    Vazio = usa "<prefixo>-pg". Para trazer um serviço existente para o Terraform:
      terraform import aiven_pg.pg <projeto>/<nome_do_servico>
  EOT
  type        = string
  default     = ""
}

variable "plano_postgres" {
  description = "Plano do PostgreSQL. free-1-1gb = Free Tier (1 GB de disco)."
  type        = string
  default     = "free-1-1gb"
}

variable "cloud_name" {
  description = "Nuvem/região do PostgreSQL. Regiões aceitas pelo plano free incluem do-nyc, aws-us-east-1, do-fra etc."
  type        = string
  default     = "do-nyc"
}

variable "nome_banco" {
  description = "Banco lógico criado para o projeto."
  type        = string
  default     = "saude_materna"
}

variable "usuario_dashboard" {
  description = "Usuário somente leitura usado pelo Streamlit."
  type        = string
  default     = "dashboard_leitor"
}

variable "habilitar_opensearch" {
  description = "Cria o Aiven for OpenSearch (banco não relacional, opcional no guia)."
  type        = bool
  default     = true
}

variable "plano_opensearch" {
  description = "Plano do OpenSearch. free-4-20 = Free Tier."
  type        = string
  default     = "free-4-20"
}

variable "cloud_name_opensearch" {
  description = "Região do OpenSearch (o plano free só existe em regiões DigitalOcean, ex.: do-nyc)."
  type        = string
  default     = "do-nyc"
}

variable "gerar_arquivo_env" {
  description = "Se true, escreve ../.env com as URIs de conexão (arquivo ignorado pelo Git)."
  type        = bool
  default     = true
}
