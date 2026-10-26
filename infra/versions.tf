# Which Terraform and which providers (plugins) this folder needs.
terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.60, < 7.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.region

  # Every resource that supports tags gets these, so the console shows what belongs to this project.
  default_tags {
    tags = {
      Project   = "freightlens"
      ManagedBy = "terraform"
    }
  }
}
