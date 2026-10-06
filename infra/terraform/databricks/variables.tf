variable "aws_region" {
  description = "Region containing the S3 bucket and KMS key."
  type        = string
  default     = "us-west-2"
}

variable "environment" {
  description = "Environment name used in AWS role and UC object names."
  type        = string
  default     = "dev"
}

variable "databricks_profile" {
  description = "Explicit Databricks CLI profile for the target workspace."
  type        = string
}

variable "private_bucket_name" {
  description = "Existing KMS-encrypted bucket created by the AWS Terraform root."
  type        = string
}

variable "data_kms_key_arn" {
  description = "KMS key ARN used by the source bucket."
  type        = string
}

variable "source_prefix" {
  description = "Narrow S3 prefix exposed through Unity Catalog."
  type        = string
  default     = "raw"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9/_-]*[a-z0-9]$", var.source_prefix))
    error_message = "source_prefix must be a relative S3 prefix without leading or trailing slash."
  }
}

variable "catalog_name" {
  description = "Unity Catalog catalog to create."
  type        = string
  default     = "tidetrack_private"
}

variable "data_classification" {
  description = "Non-sensitive classification label used in metadata."
  type        = string
  default     = "health-sensitive"
}

variable "catalog_owner" {
  description = "Optional account group that will own UC objects. Null leaves the applying identity as owner for a personal trial."
  type        = string
  default     = null
  nullable    = true
}

variable "pipeline_principal" {
  description = "Optional pipeline service-principal application ID."
  type        = string
  default     = null
  nullable    = true
}

variable "app_principal" {
  description = "Optional app service-principal application ID. It receives Gold read access only."
  type        = string
  default     = null
  nullable    = true
}
