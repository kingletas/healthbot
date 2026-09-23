/**
* Good ways to check for security or visualize what's going on
* checkov -d .
* terraform graph -type=plan | dot -Tpng -o graph.png
*/
module "secret" {
  source = "github.com/kingletas/terraform-aws-modules//modules/secrets-manager-secret?ref=71e3b4bc696910d279cce526c215208cd9b28c42" # v0.5.0

  name        = local.secret_name
  kms_key_arn = module.kms.arn

  # Written once, at creation; the module ignores later changes, so a value
  # rotated in Secrets Manager is never overwritten. The first write still
  # lands in state in clear, which stopping the seeding is what fixes.
  initial_version = {
    json = {
      topic_arn           = data.aws_sns_topic.this.arn
      dbClusterIdentifier = data.aws_rds_cluster.this.id
      twilio_account      = var.twilio_account
      twilio_token        = var.twilio_token
      twilio_from         = var.twilio_from
      twilio_to           = var.twilio_to
      slack_channel       = var.slack_channel
      slack_token         = var.slack_token
      king_slack_token    = var.king_slack_token
      user_slack_token    = var.user_slack_token
      ga_property_id      = var.ga_property_id
      ga_auth_secrets     = base64encode(file(pathexpand(var.secrets_path)))
      new_relic_api       = var.new_relic_api
    }
  }

  tags = local.tags
}

# Adopts the secret and its first version, so the plan moves them rather than
# deleting the secret the bot reads on every run.
moved {
  from = aws_secretsmanager_secret.this
  to   = module.secret.aws_secretsmanager_secret.this
}

moved {
  from = aws_secretsmanager_secret_version.this
  to   = module.secret.aws_secretsmanager_secret_version.this[0]
}

resource "aws_ssm_parameter" "hb_secret_name" {
  #checkov:skip=CKV2_AWS_34:The value names a resource and holds no secret; the credentials are in Secrets Manager under the KMS key.
  name        = format("%ssecret_name", local.sm_prefix)
  description = "The secret name "
  type        = "String"
  value       = local.secret_name

  tags = merge(local.tags, {
    Name = upper(format("%sssm-secret-name-param", local.prefix))
  })
}

resource "aws_ssm_parameter" "hb_db_identifier" {
  #checkov:skip=CKV2_AWS_34:The value names a resource and holds no secret; the credentials are in Secrets Manager under the KMS key.
  name        = format("%sdb_identifier", local.sm_prefix)
  description = "The app aws profile or credentials"
  type        = "String"
  value       = data.aws_rds_cluster.this.id

  tags = merge(local.tags, {
    Name = upper(format("%sssm-db-identifier-param", local.prefix))
  })
}

resource "aws_ssm_parameter" "hb_tag_name" {
  #checkov:skip=CKV2_AWS_34:The value names a resource and holds no secret; the credentials are in Secrets Manager under the KMS key.
  name        = format("%stag_name", local.sm_prefix)
  description = "The tag name to filter by"
  type        = "String"
  value       = var.app_environment_tag_name

  tags = merge(local.tags, {
    Name = upper(format("%sssm-tag-name-param", local.prefix))
  })
}

resource "aws_ssm_parameter" "hb_environment" {
  #checkov:skip=CKV2_AWS_34:The value names a resource and holds no secret; the credentials are in Secrets Manager under the KMS key.
  name        = format("%senvironment", local.sm_prefix)
  description = "The environment name"
  type        = "String"
  value       = var.app_environment_name

  tags = merge(local.tags, {
    Name = upper(format("%sssm-environment-param", local.prefix))
  })
}
