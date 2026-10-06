resource "databricks_external_location" "raw" {
  name            = local.external_location_name
  url             = local.source_url
  credential_name = databricks_storage_credential.raw.name
  comment         = "Read-only TideTrack source data; managed by Terraform"
  owner           = var.catalog_owner
  read_only       = true
  skip_validation = false
  isolation_mode  = "ISOLATION_MODE_ISOLATED"

  encryption_details {
    sse_encryption_details {
      algorithm       = "AWS_SSE_KMS"
      aws_kms_key_arn = var.data_kms_key_arn
    }
  }

  depends_on = [aws_iam_role_policy.uc_raw_read]
}

resource "databricks_catalog" "this" {
  name           = var.catalog_name
  comment        = "TideTrack governed personal analytics catalog"
  owner          = var.catalog_owner
  isolation_mode = "ISOLATED"
  force_destroy  = false

  properties = {
    domain              = "personal-health-analytics"
    data_classification = var.data_classification
  }
}

resource "databricks_schema" "this" {
  for_each = local.schemas

  catalog_name  = databricks_catalog.this.name
  name          = each.key
  comment       = each.value
  owner         = var.catalog_owner
  force_destroy = false

  properties = {
    layer               = each.key
    data_classification = var.data_classification
  }
}

resource "databricks_volume" "raw_landing" {
  name             = "raw_landing"
  catalog_name     = databricks_catalog.this.name
  schema_name      = databricks_schema.this["bronze"].name
  volume_type      = "EXTERNAL"
  storage_location = databricks_external_location.raw.url
  comment          = "Read-only source volume for Auto Loader"
  owner            = var.catalog_owner
}

resource "databricks_grant" "pipeline_catalog" {
  count = var.pipeline_principal == null ? 0 : 1

  catalog    = databricks_catalog.this.name
  principal  = var.pipeline_principal
  privileges = ["USE_CATALOG"]
}

resource "databricks_grant" "pipeline_schemas" {
  for_each = var.pipeline_principal == null ? {} : databricks_schema.this

  schema     = each.value.id
  principal  = var.pipeline_principal
  privileges = ["USE_SCHEMA", "CREATE_TABLE", "CREATE_FUNCTION", "CREATE_VOLUME", "SELECT", "MODIFY", "REFRESH"]
}

resource "databricks_grant" "pipeline_external_location" {
  count = var.pipeline_principal == null ? 0 : 1

  external_location = databricks_external_location.raw.id
  principal         = var.pipeline_principal
  privileges        = ["READ_FILES"]
}

resource "databricks_grant" "pipeline_raw_volume" {
  count = var.pipeline_principal == null ? 0 : 1

  volume     = databricks_volume.raw_landing.id
  principal  = var.pipeline_principal
  privileges = ["READ_VOLUME"]
}

resource "databricks_grant" "app_catalog" {
  count = var.app_principal == null ? 0 : 1

  catalog    = databricks_catalog.this.name
  principal  = var.app_principal
  privileges = ["USE_CATALOG"]
}

resource "databricks_grant" "app_gold" {
  count = var.app_principal == null ? 0 : 1

  schema     = databricks_schema.this["gold"].id
  principal  = var.app_principal
  privileges = ["USE_SCHEMA", "SELECT"]
}
