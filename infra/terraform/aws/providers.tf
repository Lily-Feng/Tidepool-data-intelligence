provider "aws" {
  region = var.aws_region

  default_tags {
    tags = merge(
      {
        Application = "TideTrack-Studio"
        Environment = var.environment
        ManagedBy   = "Terraform"
        DataClass   = "health-sensitive"
      },
      var.tags,
    )
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}
