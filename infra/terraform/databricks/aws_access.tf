resource "databricks_storage_credential" "raw" {
  name            = local.storage_credential_name
  comment         = "Read-only TideTrack raw S3 access; managed by Terraform"
  owner           = var.catalog_owner
  read_only       = true
  skip_validation = true
  isolation_mode  = "ISOLATION_MODE_ISOLATED"

  aws_iam_role {
    # This ARN is deterministic so UC can create the credential and issue its
    # external ID before Terraform creates the role's final trust policy.
    role_arn = local.uc_role_arn
  }
}

data "databricks_aws_unity_catalog_assume_role_policy" "raw" {
  aws_account_id = data.aws_caller_identity.current.account_id
  role_name      = local.uc_role_name
  external_id    = databricks_storage_credential.raw.aws_iam_role[0].external_id
}

resource "aws_iam_role" "uc_raw_read" {
  name                 = local.uc_role_name
  description          = "Unity Catalog read-only access to the TideTrack source prefix"
  assume_role_policy   = data.databricks_aws_unity_catalog_assume_role_policy.raw.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "uc_raw_read" {
  statement {
    sid       = "ReadBucketLocation"
    effect    = "Allow"
    actions   = ["s3:GetBucketLocation"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::${var.private_bucket_name}"]
  }

  statement {
    sid       = "ListSourcePrefix"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::${var.private_bucket_name}"]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        var.source_prefix,
        "${var.source_prefix}/*",
      ]
    }
  }

  statement {
    sid       = "ReadSourceObjects"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["arn:${data.aws_partition.current.partition}:s3:::${var.private_bucket_name}/${var.source_prefix}/*"]
  }

  statement {
    sid    = "DecryptSourceObjects"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:DescribeKey",
    ]
    resources = [var.data_kms_key_arn]
  }
}

resource "aws_iam_role_policy" "uc_raw_read" {
  name   = "${local.name_prefix}-uc-raw-read"
  role   = aws_iam_role.uc_raw_read.id
  policy = data.aws_iam_policy_document.uc_raw_read.json
}
