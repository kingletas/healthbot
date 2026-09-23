terraform {
  # The write-only secret value needs 1.11 or later, and use_lockfile in
  # backend.tf needs 1.10; an older CLI then errors clearly.
  required_version = "~> 1.11"

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
