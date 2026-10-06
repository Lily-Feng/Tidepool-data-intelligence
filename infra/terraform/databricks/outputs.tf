output "unity_catalog_iam_role_arn" {
  value = aws_iam_role.uc_raw_read.arn
}

output "storage_credential_name" {
  value = databricks_storage_credential.raw.name
}

output "external_location_name" {
  value = databricks_external_location.raw.name
}

output "raw_volume_path" {
  value = databricks_volume.raw_landing.volume_path
}

output "catalog_name" {
  value = databricks_catalog.this.name
}

output "schema_names" {
  value = sort([for schema in databricks_schema.this : schema.id])
}
