/**
* Good ways to check for security or visualize what's going on
* checkov -d .
* terraform graph -type=plan | dot -Tpng -o graph.png
*/
resource "aws_secretsmanager_secret" "this" {
  name       = local.secret_name
  kms_key_id = aws_kms_alias.this.target_key_arn

  tags = merge(local.tags, {
    Name = upper(format("%ssecret", local.prefix))
  })
}

resource "aws_ssm_parameter" "hb_secret_name" {
  name        = format("%ssecret_name", local.sm_prefix)
  description = "The secret name "
  type        = "String"
  value       = local.secret_name

  tags = merge(local.tags, {
    Name = upper(format("%sssm-secret-name-param", local.prefix))
  })
}

resource "aws_ssm_parameter" "hb_db_identifier" {
  name        = format("%sdb_identifier", local.sm_prefix)
  description = "The app aws profile or credentials"
  type        = "String"
  value       = data.aws_rds_cluster.this.id

  tags = merge(local.tags, {
    Name = upper(format("%sssm-db-identifier-param", local.prefix))
  })
}

resource "aws_ssm_parameter" "hb_tag_name" {
  name        = format("%stag_name", local.sm_prefix)
  description = "The tag name to filter by"
  type        = "String"
  value       = var.app_environment_tag_name

  tags = merge(local.tags, {
    Name = upper(format("%sssm-tag-name-param", local.prefix))
  })
}

resource "aws_ssm_parameter" "hb_environment" {
  name        = format("%senvironment", local.sm_prefix)
  description = "The environment name"
  type        = "String"
  value       = var.app_environment_name

  tags = merge(local.tags, {
    Name = upper(format("%sssm-environment-param", local.prefix))
  })
}

resource "aws_secretsmanager_secret_version" "this" {
  secret_id = aws_secretsmanager_secret.this.id

  # Seeding runs once, at creation. After that the secret is rotated in
  # Secrets Manager, not through terraform — without ignore_changes every
  # apply would overwrite a rotated credential with the tfvars copy and land
  # the values in state again. Note the initial apply still writes them to
  # state; full stop-seeding is the follow-up once there is a plan diff.
  lifecycle {
    ignore_changes = [secret_string]
  }

  secret_string = jsonencode({
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
  })
}
