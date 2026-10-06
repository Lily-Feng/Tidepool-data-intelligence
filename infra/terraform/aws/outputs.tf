output "aws_account_id" {
  value = data.aws_caller_identity.current.account_id
}

output "aws_region" {
  value = data.aws_region.current.region
}

output "private_bucket_name" {
  value = aws_s3_bucket.data["private"].id
}

output "private_bucket_arn" {
  value = aws_s3_bucket.data["private"].arn
}

output "demo_bucket_name" {
  value = aws_s3_bucket.data["demo"].id
}

output "data_kms_key_arn" {
  value = aws_kms_key.data.arn
}

output "collector_role_arn" {
  value = try(aws_iam_role.collector[0].arn, null)
}

output "tidepool_secret_arn" {
  value = try(aws_secretsmanager_secret.tidepool[0].arn, null)
}

output "cloudtrail_arn" {
  value = try(aws_cloudtrail.this[0].arn, null)
}

output "next_step" {
  value = "Pass private_bucket_name and data_kms_key_arn to ../databricks/terraform.tfvars."
}
