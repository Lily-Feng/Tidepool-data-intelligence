variable "aws_region" {
  description = "AWS region for TideTrack resources."
  type        = string
  default     = "us-west-2"
}

variable "project_name" {
  description = "Lowercase name used in resource names."
  type        = string
  default     = "tidetrack"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,20}$", var.project_name))
    error_message = "project_name must be 2-21 lowercase letters, numbers, or hyphens and start with a letter."
  }
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "dev"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,12}$", var.environment))
    error_message = "environment must be 2-13 lowercase letters, numbers, or hyphens and start with a letter."
  }
}

variable "private_bucket_name" {
  description = "Optional globally unique private-data bucket name. Null generates one."
  type        = string
  default     = null
  nullable    = true
}

variable "demo_bucket_name" {
  description = "Optional globally unique synthetic-demo bucket name. Null generates one."
  type        = string
  default     = null
  nullable    = true
}

variable "noncurrent_version_retention_days" {
  description = "Days to retain noncurrent object versions. Current objects do not expire."
  type        = number
  default     = 45

  validation {
    condition     = var.noncurrent_version_retention_days >= 30
    error_message = "Retain noncurrent versions for at least 30 days."
  }
}

variable "enable_account_public_access_block" {
  description = "Enable account-wide S3 Block Public Access. Review unrelated buckets first."
  type        = bool
  default     = false
}

variable "enable_cloudtrail" {
  description = "Create a multi-region trail with private-bucket S3 object data events."
  type        = bool
  default     = false
}

variable "cloudtrail_log_retention_days" {
  description = "Days to retain current CloudTrail log objects."
  type        = number
  default     = 365

  validation {
    condition     = var.cloudtrail_log_retention_days >= 90
    error_message = "Retain CloudTrail logs for at least 90 days."
  }
}

variable "create_collector_role" {
  description = "Create the least-privilege role used to upload Tidepool batches."
  type        = bool
  default     = false
}

variable "collector_trusted_principal_arns" {
  description = "Stable IAM role ARNs allowed to assume the collector role; do not use STS session ARNs."
  type        = list(string)
  default     = []
}

variable "create_tidepool_secret" {
  description = "Create an empty Secrets Manager container. Terraform never creates the secret value."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Additional AWS resource tags. Never put personal or health data in tags."
  type        = map(string)
  default     = {}
}
