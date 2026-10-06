resource "aws_secretsmanager_secret" "tidepool" {
  count = var.create_tidepool_secret ? 1 : 0

  name                    = "${local.name_prefix}/tidepool/api"
  description             = "Tidepool API credential container; value is managed outside Terraform"
  kms_key_id              = aws_kms_key.data.arn
  recovery_window_in_days = 30

  lifecycle {
    prevent_destroy = true
  }
}

# Deliberately no aws_secretsmanager_secret_version resource. Secret values
# stored by Terraform would also be present in Terraform state.
