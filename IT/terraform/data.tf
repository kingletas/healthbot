# The AWS region currently being used.
data "aws_region" "current" {
}

# The AWS account id
data "aws_caller_identity" "current" {
}

# The AWS partition (commercial or govcloud)
data "aws_partition" "current" {}
data "aws_ami" "this" {
  most_recent = true
  owners      = ["self"]

  filter {
    name   = "tag:Service"
    values = ["SRE"]
  }

}

data "aws_iam_policy_document" "assume-policy" {

  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com", "cloudwatch.amazonaws.com"]
    }
  }
}
data "aws_vpc" "this" {
  id = var.vpc_id
}

data "aws_subnet" "this" {
  id = var.subnet_id
}

data "aws_availability_zones" "this" {
  state = "available"
}

data "aws_rds_cluster" "this" {
  cluster_identifier = var.db_cluster_identifier
}

data "aws_sns_topic" "this" {
  name = var.sns_name
}

data "aws_iam_policy_document" "allow-policy" {

  statement {
    sid = "HealthBotAccessToSM"

    actions = [
      "secretsmanager:GetSecretValue"
    ]

    resources = [
      aws_secretsmanager_secret.this.arn
    ]
  }

  statement {
    sid = "HealthBotAccessToKMS"

    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt",
      "kms:GenerateDataKey",
      "kms:DescribeKey"
    ]
    resources = [aws_kms_key.this.arn]
  }

  statement {
    sid = "HealthBotAccessToCloudWatch"

    actions = [
      "cloudwatch:GetMetricData",
      "cloudwatch:GetMetricStatistics",
      "cloudwatch:GetMetricStream",
    ]
    resources = [format("arn:%s:cloudwatch:%s:%s:*",
      data.aws_partition.current.partition,
      data.aws_region.current.region,
      data.aws_caller_identity.current.account_id)
    ]

  }

  statement {
    sid = "HealthBotDescribeFleet"

    actions = [
      "ec2:DescribeInstances"
    ]
    # checks/aws.py finds the fleet by tag on every run. DescribeInstances
    # takes no resource-level permission, so the tag pair is the filter and
    # IAM cannot narrow this further.
    resources = ["*"]
  }

  statement {
    sid = "HealthBotPublishToTopic"

    actions = [
      "sns:Publish"
    ]
    resources = [data.aws_sns_topic.this.arn]
  }

  statement {
    sid = "HealthBotAccessToSSM"

    actions = [
      "ssm:DescribeParameters",
      "ssm:GetParameters",
      "ssm:GetParametersByPath",
      "ssm:GetParameter",
    ]
    resources = [format("arn:%s:ssm:%s:%s:parameter/%s*",
      data.aws_partition.current.partition,
      data.aws_region.current.region,
      data.aws_caller_identity.current.account_id,
      local.prefix)
    ]

  }
}

data "cloudinit_config" "this" {
  # base64_encode stays on: the AWS provider encodes user_data only when it is
  # not already base64, so this is passed to the API unchanged.
  base64_encode = true
  gzip          = false
  part {
    # Declared rather than left to the provider's text/plain default, which
    # works only because cloud-init re-reads the type off the first line.
    content_type = "text/cloud-config"
    content      = <<EOF
#cloud-config
---
users:
  - default
runcmd:
  - apt update -y && apt install -y jq
write_files:
- path: ${local.etc_env_file}
  content: |
    HB_PARAM_PREFIX="${local.sm_prefix}"
    HB_ENVIRONMENT="${var.app_environment_name}"
  append: true
EOF
  }
}
