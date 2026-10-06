locals {
  name_prefix             = "tidetrack-${var.environment}"
  uc_role_name            = "${local.name_prefix}-uc-raw-read"
  uc_role_arn             = "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/${local.uc_role_name}"
  source_url              = "s3://${var.private_bucket_name}/${var.source_prefix}"
  storage_credential_name = "${replace(local.name_prefix, "-", "_")}_raw_read"
  external_location_name  = "${replace(local.name_prefix, "-", "_")}_raw"

  schemas = {
    bronze = "Immutable ingestion and source-preserving tables"
    silver = "Typed, deduplicated personal event facts"
    gold   = "Approved descriptive analytics and app-facing datasets"
    ops    = "Reconciliation, quality, and freshness metadata"
  }
}
