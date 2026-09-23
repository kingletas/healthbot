/**
* Good ways to check for security or visualize what's going on
* checkov -d .
* terraform graph -type=plan | dot -Tpng -o graph.png
*/
module "secret" {
  source = "github.com/kingletas/terraform-aws-modules//modules/secrets-manager-secret?ref=5e0ae490c797bb1e8178bea00c41cc9d4c060111" # v0.6.0

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

# The four settings the bot reads at run time, under the deployment's prefix.
module "parameters" {
  source = "github.com/kingletas/terraform-aws-modules//modules/ssm-parameter?ref=5e0ae490c797bb1e8178bea00c41cc9d4c060111" # v0.6.0

  path_prefix = trimsuffix(local.sm_prefix, "/")

  parameters = {
    secret_name   = { description = "The secret name " }
    db_identifier = { description = "The app aws profile or credentials" }
    tag_name      = { description = "The tag name to filter by" }
    environment   = { description = "The environment name" }
  }

  values = {
    secret_name   = local.secret_name
    db_identifier = data.aws_rds_cluster.this.id
    tag_name      = var.app_environment_tag_name
    environment   = var.app_environment_name
  }

  tags = local.tags
}

moved {
  from = aws_ssm_parameter.hb_secret_name
  to   = module.parameters.aws_ssm_parameter.this["secret_name"]
}

moved {
  from = aws_ssm_parameter.hb_db_identifier
  to   = module.parameters.aws_ssm_parameter.this["db_identifier"]
}

moved {
  from = aws_ssm_parameter.hb_tag_name
  to   = module.parameters.aws_ssm_parameter.this["tag_name"]
}

moved {
  from = aws_ssm_parameter.hb_environment
  to   = module.parameters.aws_ssm_parameter.this["environment"]
}
