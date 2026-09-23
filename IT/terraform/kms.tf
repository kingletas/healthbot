
resource "random_string" "this" {
  length    = 5
  special   = false
  numeric   = true
  min_lower = 2
  min_upper = 2
}

# The role behind the deploying session, which is what a key policy can name stably.
data "aws_iam_session_context" "deployer" {
  arn = data.aws_caller_identity.current.arn
}

module "kms" {
  #checkov:skip=CKV_AWS_109:A key policy's Resource "*" is the key itself, and the kms:* grant is the admin statement, limited to the named admins.
  #checkov:skip=CKV_AWS_111:A key policy's Resource "*" is the key itself, so the write actions cannot reach any other resource.
  #checkov:skip=CKV_AWS_356:A key policy's Resource "*" is the key itself; a key policy cannot name its own ARN before the key exists.
  source = "github.com/kingletas/terraform-aws-modules//modules/kms-key?ref=af6f00f1646e1e99e635df03b09f9753da8fe59d" # v0.7.0

  name        = local.name
  description = format("%s KMS key", var.environment)

  deletion_window_in_days = 15

  # The module builds the policy: whoever runs the deploy administers the key,
  # and only the instance role may use it. Without an admin the account root would be.
  admin_arns = distinct(concat(var.kms_admin_arns, [data.aws_iam_session_context.deployer.issuer_arn]))
  user_arns  = [module.role.arn]

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
