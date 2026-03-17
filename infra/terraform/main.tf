terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.119"
    }
  }
}

provider "azurerm" {
  features {}
}

data "azurerm_client_config" "current" {}

variable "location" {
  type        = string
  description = "Azure region for all resources."
  default     = "eastus"
}

variable "resource_group_name" {
  type        = string
  description = "Name of the resource group that hosts the app."
}

variable "base_name" {
  type        = string
  description = "Short prefix applied to resource names."
}

variable "key_vault_admin_object_id" {
  type        = string
  description = "AAD object ID that will receive admin rights to Key Vault."
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Optional resource tags."
}

resource "azurerm_resource_group" "fdsc" {
  name     = var.resource_group_name
  location = var.location
  tags     = var.tags
}

resource "azurerm_user_assigned_identity" "fdsc" {
  name                = "${var.base_name}-uami"
  location            = azurerm_resource_group.fdsc.location
  resource_group_name = azurerm_resource_group.fdsc.name
  tags                = var.tags
}

resource "azurerm_storage_account" "datasets" {
  name                     = lower("${var.base_name}data")
  resource_group_name      = azurerm_resource_group.fdsc.name
  location                 = azurerm_resource_group.fdsc.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  allow_nested_items_to_be_public = false
  cross_tenant_replication_enabled = false
  min_tls_version                = "TLS1_2"
  tags                           = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.fdsc.id]
  }
}

resource "azurerm_storage_container" "tir_datasets" {
  name                  = "tir-datasets"
  storage_account_name  = azurerm_storage_account.datasets.name
  container_access_type = "private"
}

resource "azurerm_storage_container" "tir_results" {
  name                  = "tir-results"
  storage_account_name  = azurerm_storage_account.datasets.name
  container_access_type = "private"
}

resource "azurerm_storage_container" "fdsc_docs" {
  name                  = "fdsc-docs"
  storage_account_name  = azurerm_storage_account.datasets.name
  container_access_type = "private"
}

resource "azurerm_cognitive_account" "openai" {
  name                = "${var.base_name}-openai"
  location            = azurerm_resource_group.fdsc.location
  resource_group_name = azurerm_resource_group.fdsc.name
  kind                = "OpenAI"
  sku_name            = "S0"
  custom_subdomain_name = "${var.base_name}-openai"
  tags                = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.fdsc.id]
  }
}

resource "azurerm_cognitive_account" "docintel" {
  name                  = "${var.base_name}-docintel"
  location              = azurerm_resource_group.fdsc.location
  resource_group_name   = azurerm_resource_group.fdsc.name
  kind                  = "FormRecognizer"
  sku_name              = "S0"
  custom_subdomain_name = "${var.base_name}-docintel"
  tags                  = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.fdsc.id]
  }
}

resource "azurerm_search_service" "fdsc" {
  name                = "${var.base_name}-search"
  location            = azurerm_resource_group.fdsc.location
  resource_group_name = azurerm_resource_group.fdsc.name
  sku                 = "standard"
  replica_count       = 1
  partition_count     = 1
  public_network_access_enabled = true
  local_authentication_enabled  = false
  tags = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.fdsc.id]
  }
}

resource "azurerm_cosmosdb_account" "fdsc" {
  name                = "${var.base_name}-cosmos"
  location            = azurerm_resource_group.fdsc.location
  resource_group_name = azurerm_resource_group.fdsc.name
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"
  enable_free_tier    = false
  mongo_server_version = "4.2"
  tags                = var.tags
  public_network_access_enabled = true
  access_key_metadata_writes_enabled = false

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.fdsc.id]
  }

  consistency_policy {
    consistency_level       = "Session"
    max_interval_in_seconds = 5
    max_staleness_prefix    = 100
  }

  geo_location {
    location          = azurerm_resource_group.fdsc.location
    failover_priority = 0
  }
}

resource "azurerm_cosmosdb_sql_database" "app" {
  name                = "${var.base_name}-db"
  resource_group_name = azurerm_resource_group.fdsc.name
  account_name        = azurerm_cosmosdb_account.fdsc.name
}

resource "azurerm_cosmosdb_sql_container" "chat_history" {
  name                = "chat_history"
  resource_group_name = azurerm_resource_group.fdsc.name
  account_name        = azurerm_cosmosdb_account.fdsc.name
  database_name       = azurerm_cosmosdb_sql_database.app.name
  partition_key_path  = "/session_id"
}

resource "azurerm_cosmosdb_sql_container" "tir_scores" {
  name                = "tir_scores"
  resource_group_name = azurerm_resource_group.fdsc.name
  account_name        = azurerm_cosmosdb_account.fdsc.name
  database_name       = azurerm_cosmosdb_sql_database.app.name
  partition_key_path  = "/session_id"
}

resource "azurerm_cosmosdb_sql_container" "fdsc_documents" {
  name                = "fdsc_documents"
  resource_group_name = azurerm_resource_group.fdsc.name
  account_name        = azurerm_cosmosdb_account.fdsc.name
  database_name       = azurerm_cosmosdb_sql_database.app.name
  partition_key_path  = "/id"
}

resource "azurerm_key_vault" "fdsc" {
  name                        = "${var.base_name}-kv"
  location                    = azurerm_resource_group.fdsc.location
  resource_group_name         = azurerm_resource_group.fdsc.name
  tenant_id                   = data.azurerm_client_config.current.tenant_id
  sku_name                    = "standard"
  soft_delete_retention_days  = 90
  purge_protection_enabled    = true
  public_network_access_enabled = true
  tags                        = var.tags

  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = var.key_vault_admin_object_id

    secret_permissions = ["Get", "List", "Set"]
    key_permissions    = ["Get", "Create"]
  }

  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = azurerm_user_assigned_identity.fdsc.principal_id

    secret_permissions = ["Get", "List"]
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.fdsc.id]
  }
}

output managed_identity_id {
  value       = azurerm_user_assigned_identity.fdsc.id
  description = "Resource ID for the managed identity bound to the app."
}

output managed_identity_principal_id {
  value       = azurerm_user_assigned_identity.fdsc.principal_id
  description = "Principal ID used for role assignments."
}

output key_vault_uri {
  value       = azurerm_key_vault.fdsc.vault_uri
  description = "Key Vault URI used by the backend."
}

output storage_account_primary_blob_endpoint {
  value       = azurerm_storage_account.datasets.primary_blob_endpoint
  description = "Blob endpoint for dataset/result containers."
}

output search_service_endpoint {
  value       = "https://${azurerm_search_service.fdsc.name}.search.azure.us"
  description = "Search service endpoint expected by backend code."
}

output cosmos_endpoint {
  value       = azurerm_cosmosdb_account.fdsc.endpoint
  description = "Cosmos DB account endpoint."
}

output cosmos_database_name {
  value       = azurerm_cosmosdb_sql_database.app.name
  description = "Cosmos DB SQL database name used by the app."
}

output openai_endpoint {
  value       = azurerm_cognitive_account.openai.endpoint
  description = "Azure OpenAI endpoint."
}

output docintel_endpoint {
  value       = azurerm_cognitive_account.docintel.endpoint
  description = "Azure Document Intelligence endpoint."
}
