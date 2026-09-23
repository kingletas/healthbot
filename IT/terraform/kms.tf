
resource "random_string" "this" {
  length    = 5
  special   = false
  numeric   = true
  min_lower = 2
  min_upper = 2
}

module "kms" {
  source = "github.com/kingletas/terraform-aws-modules//modules/kms-key?ref=5e0ae490c797bb1e8178bea00c41cc9d4c060111" # v0.6.0

  name        = local.name
  description = format("%s KMS key", var.environment)

  deletion_window_in_days = 15

  # The policy AWS attaches to a key created without one, written out so adopting
  # the key into the module changes nobody's access. Narrowing it is its own change.
  policy_json = jsonencode({
    Version = "2012-10-17"
    Id      = "key-default-1"
    Statement = [{
      Sid       = "Enable IAM User Permissions"
      Effect    = "Allow"
      Principal = { AWS = format("arn:%s:iam::%s:root", data.aws_partition.current.partition, data.aws_caller_identity.current.account_id) }
      Action    = "kms:*"
      Resource  = "*"
    }]
  })

  tags = local.tags
}

# Adopts the key and alias created at root addresses, so the plan moves them
# rather than scheduling the key for deletion and creating another.
moved {
  from = aws_kms_key.this
  to   = module.kms.aws_kms_key.this
}

moved {
  from = aws_kms_alias.this
  to   = module.kms.aws_kms_alias.this
}
