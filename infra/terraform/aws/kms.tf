resource "aws_kms_key" "data" {
  description             = "TideTrack private and synthetic object encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  multi_region            = false

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_kms_alias" "data" {
  name          = "alias/${local.name_prefix}-data"
  target_key_id = aws_kms_key.data.key_id
}
