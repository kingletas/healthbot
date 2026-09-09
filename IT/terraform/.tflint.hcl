config {
  plugin_dir = "~/.tflint.d/plugins"

  module              = true
  force               = false
  disabled_by_default = false

  ignore_module = {
    "terraform-aws-modules/vpc/aws"            = true
    "terraform-aws-modules/security-group/aws" = true
  }

  varfile = ["stage.tfvars"]

}

plugin "aws" {
  enabled = true
  version = "0.9.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}

rule "aws_instance_invalid_type" {
  enabled = false
}

rule "terraform_unused_declarations" {
  enabled = true
}

rule "aws_resource_missing_tags" {
  enabled = true
  tags = [
    "Environment",
    "Owner",
    "Name",
  ]
}
