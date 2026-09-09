terraform {
  # use_lockfile in backend.tf needs 1.10+; state what the config assumes so
  # an older CLI errors clearly instead of confusingly
  required_version = "~> 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~>6.61.0"
    }
  }
}

provider "aws" {}
provider "aws" {
  profile = var.profile
  region  = var.region
  alias   = "us_east_2"
}

provider "aws" {
  profile = var.production_profile
  region  = var.region
  alias   = "aws_production"
}

provider "aws" {
  alias = "alternate"
}
