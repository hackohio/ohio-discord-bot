# ONE-TIME SETUP. Run this once per AWS account from a laptop, using your own
# (admin) AWS login, not the GitHub deployer user:
#
#   cd infra/bootstrap
#   terraform init
#   terraform apply
#
# It creates two private S3 buckets:
#   - a "state" bucket where Terraform remembers what servers it created, so the
#     Stop workflow knows what to delete
#   - a "backups" bucket for records.db copies taken by the Stop workflow
#
# Bucket names end in the AWS account ID so they are globally unique. The GitHub
# workflows work out the same names automatically.
# The state file for this folder is kept locally and doesn't matter much. If it
# is lost, the buckets are still there and nothing breaks.

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

variable "region" {
  description = "AWS region for the buckets. Must match AWS_REGION in the workflows."
  type        = string
  default     = "us-east-2"
}

provider "aws" {
  region = var.region
}

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
}

# --- Terraform state bucket -------------------------------------------------

resource "aws_s3_bucket" "state" {
  bucket = "ohio-discord-bot-tfstate-${local.account_id}"
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# --- records.db backup bucket -----------------------------------------------
# The backups hold participant names and emails, so the bucket stays private and encrypted.

resource "aws_s3_bucket" "backups" {
  bucket = "ohio-discord-bot-backups-${local.account_id}"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "backups" {
  bucket                  = aws_s3_bucket.backups.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

output "state_bucket" {
  value = aws_s3_bucket.state.bucket
}

output "backup_bucket" {
  value = aws_s3_bucket.backups.bucket
}
