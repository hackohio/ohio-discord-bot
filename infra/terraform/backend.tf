terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # State lives in S3 so every GitHub Actions run (which starts on a blank
  # machine) sees the same server. The workflows supply both the account-specific
  # bucket and an event-specific key at init time so deployments stay isolated.
  backend "s3" {
    region       = "us-east-2"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region
}
