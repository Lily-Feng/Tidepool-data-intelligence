provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Application = "TideTrack-Studio"
      Environment = var.environment
      ManagedBy   = "Terraform"
      DataClass   = var.data_classification
    }
  }
}

provider "databricks" {
  profile = var.databricks_profile
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
