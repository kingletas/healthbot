terraform {
  # use_lockfile in backend.tf needs 1.10+; state what the config assumes so
  # an older CLI errors clearly instead of confusingly
  required_version = "~> 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~>6.61.0"
    }
    # Both are used (cloudinit in data.tf, random in kms.tf) and were never
    # declared, so `init -upgrade` was free to cross a major. The lock file
    # was the only thing holding them.
    cloudinit = {
      source  = "hashicorp/cloudinit"
      version = "~>2.4"
    }
    random = {
      source  = "hashicorp/random"
      version = "~>3.9"
    }
  }
}

provider "aws" {}
