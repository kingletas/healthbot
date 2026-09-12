config {
  plugin_dir = "~/.tflint.d/plugins"

  call_module_type    = "all"
  force               = false
  disabled_by_default = false

  ignore_module = {
    "terraform-aws-modules/vpc/aws"            = true
    "terraform-aws-modules/security-group/aws" = true
  }

  # No varfile: every tfvars file is gitignored, so a clone has none to read.
}

plugin "aws" {
  enabled = true
  version = "0.44.0"
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
