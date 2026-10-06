resource "random_id" "bucket_suffix" {
  byte_length = 4

  keepers = {
    project     = var.project_name
    environment = var.environment
  }
}

locals {
  name_prefix = "${var.project_name}-${var.environment}"

  private_bucket_name = coalesce(
    var.private_bucket_name,
    "${local.name_prefix}-private-${random_id.bucket_suffix.hex}",
  )
  demo_bucket_name = coalesce(
    var.demo_bucket_name,
    "${local.name_prefix}-demo-${random_id.bucket_suffix.hex}",
  )
  audit_bucket_name = "${local.name_prefix}-audit-${random_id.bucket_suffix.hex}"
  trail_name        = "${local.name_prefix}-data-events"
  trail_arn         = "arn:${data.aws_partition.current.partition}:cloudtrail:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:trail/${local.trail_name}"

  data_buckets = {
    private = local.private_bucket_name
    demo    = local.demo_bucket_name
  }
}
