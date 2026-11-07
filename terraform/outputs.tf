# =============================================================================
# Saídas. As URIs com senha são marcadas como sensitive: aparecem só com
#   terraform output -raw <nome>
# =============================================================================

output "postgres_host" {
  description = "Host do Aiven for PostgreSQL."
  value       = aiven_pg.pg.service_host
}

output "postgres_port" {
  description = "Porta do Aiven for PostgreSQL."
  value       = aiven_pg.pg.service_port
}

output "postgres_banco" {
  description = "Banco lógico do projeto."
  value       = aiven_pg_database.saude_materna.database_name
}

output "postgres_estado" {
  description = "Estado do serviço (RUNNING quando pronto)."
  value       = aiven_pg.pg.state
}

output "database_url_etl" {
  description = "URI de escrita (avnadmin) para o ETL / GitHub Actions secret DATABASE_URL."
  value       = local.pg_admin_uri
  sensitive   = true
}

output "database_url_dashboard" {
  description = "URI somente leitura para o Streamlit (secret DASHBOARD_DATABASE_URL)."
  value       = local.pg_leitor_uri
  sensitive   = true
}

output "opensearch_url" {
  description = "URI do Aiven for OpenSearch (vazia se desabilitado)."
  value       = local.opensearch_uri
  sensitive   = true
}

output "opensearch_host" {
  description = "Host do OpenSearch (se habilitado)."
  value       = var.habilitar_opensearch ? aiven_opensearch.os[0].service_host : null
}
