terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
  backend "s3" {
    bucket       = "serverless-rag-tfstate-585242447302"
    key          = "phase1/terraform.tfstate"
    region       = "ca-central-1"
    use_lockfile = true # native S3 state locking (replaces the deprecated DynamoDB lock table)
    encrypt      = true
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = var.prefix
      ManagedBy = "terraform"
    }
  }
}
