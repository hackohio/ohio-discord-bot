terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # State lives in S3 so every GitHub Actions run (which starts on a blank
  # machine) sees the same server. The bucket name contains the AWS account ID,
  # so the workflows pass it in at init time:
  #   terraform init -backend-config="bucket=ohio-discord-bot-tfstate-<account id>"
  backend "s3" {
    key          = "ohio-discord-bot/terraform.tfstate"
    region       = "us-east-2"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region
}
