data "aws_iam_policy_document" "collector_trust" {
  count = var.create_collector_role ? 1 : 0

  statement {
    sid     = "TrustedOperatorRoles"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = var.collector_trusted_principal_arns
    }
  }
}

resource "aws_iam_role" "collector" {
  count = var.create_collector_role ? 1 : 0

  name                 = "${local.name_prefix}-collector"
  description          = "Uploads immutable TideTrack batches without finalized raw reads or deletes"
  assume_role_policy   = data.aws_iam_policy_document.collector_trust[0].json
  max_session_duration = 3600

  lifecycle {
    precondition {
      condition     = length(var.collector_trusted_principal_arns) > 0
      error_message = "collector_trusted_principal_arns must contain at least one stable IAM role ARN when create_collector_role is true."
    }
  }
}

data "aws_iam_policy_document" "collector" {
  count = var.create_collector_role ? 1 : 0

  statement {
    sid       = "ReadBucketLocation"
    effect    = "Allow"
    actions   = ["s3:GetBucketLocation"]
    resources = [aws_s3_bucket.data["private"].arn]
  }

  statement {
    sid    = "ListStagingUploads"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:ListBucketMultipartUploads",
    ]
    resources = [aws_s3_bucket.data["private"].arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        "staging",
        "staging/*",
      ]
    }
  }

  statement {
    sid    = "WriteStagingAndFinalizedBatches"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
      "s3:PutObject",
    ]
    resources = [
      "${aws_s3_bucket.data["private"].arn}/staging/*",
      "${aws_s3_bucket.data["private"].arn}/raw/*",
    ]
  }

  statement {
    sid       = "VerifyStagingOnly"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data["private"].arn}/staging/*"]
  }

  statement {
    sid    = "UseDataKey"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:DescribeKey",
      "kms:Encrypt",
      "kms:GenerateDataKey",
    ]
    resources = [aws_kms_key.data.arn]
  }

  dynamic "statement" {
    for_each = var.create_tidepool_secret ? [1] : []

    content {
      sid       = "ReadTidepoolSecret"
      effect    = "Allow"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = [aws_secretsmanager_secret.tidepool[0].arn]
    }
  }
}

resource "aws_iam_role_policy" "collector" {
  count = var.create_collector_role ? 1 : 0

  name   = "${local.name_prefix}-collector-access"
  role   = aws_iam_role.collector[0].id
  policy = data.aws_iam_policy_document.collector[0].json
}
