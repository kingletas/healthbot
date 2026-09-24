# Adopts the role and profile under the names they already have, so the plan
# moves them rather than replacing the role the instance runs as.
module "role" {
  source = "github.com/kingletas/terraform-aws-modules//modules/iam-role?ref=af6f00f1646e1e99e635df03b09f9753da8fe59d" # v0.7.0

  name                  = format("%srole", local.prefix)
  use_name_prefix       = false
  instance_profile_name = format("%sprofile", local.prefix)

  trusted_services        = ["ec2.amazonaws.com", "cloudwatch.amazonaws.com"]
  create_instance_profile = true

  tags = local.tags
}

# Stays at the root: it names the key and the secret, the key names this role,
# and inside the module that loop would be a dependency cycle.
resource "aws_iam_role_policy" "this" {
  name = format("%ssm-policy", local.prefix)
  role = module.role.id

  policy = data.aws_iam_policy_document.allow-policy.json
}

moved {
  from = aws_iam_role.this
  to   = module.role.aws_iam_role.this
}

moved {
  from = aws_iam_instance_profile.this
  to   = module.role.aws_iam_instance_profile.this[0]
}

# One instance, keyed "01" inside the module, so the moved block below is the
# same literal in every environment. The subnet decides the zone.
module "instance" {
  source = "github.com/kingletas/terraform-aws-modules//modules/ec2-instance?ref=af6f00f1646e1e99e635df03b09f9753da8fe59d" # v0.7.0

  name                 = var.name
  ami_id               = data.aws_ami.this.id
  instance_type        = var.instance_type
  subnet_ids           = [data.aws_subnet.this.id]
  security_group_ids   = [aws_security_group.this["ssh"].id]
  key_name             = aws_key_pair.this.key_name
  iam_instance_profile = module.role.instance_profile_name

  associate_public_ip_address = var.associate_public_ip_address
  # Not applicable to the smallish instances.
  ebs_optimized = var.ebs_enabled
  monitoring    = true

  user_data = data.cloudinit_config.this.rendered

  root_volume = {
    type                  = var.volume_type
    size                  = var.volume_size
    iops                  = var.iops
    delete_on_termination = var.delete_on_termination
  }
  kms_key_id = module.kms.key_id

  tags = local.tags
}

moved {
  from = aws_instance.this
  to   = module.instance.aws_instance.this["01"]
}

locals {
  instance_name = format("%s-01", var.name)
  instance_id   = module.instance.instance_ids[local.instance_name]
}

# Keyed by the deployment name, which is known at plan time; the instance id
# goes in dimensions, where an unknown value is fine.
module "alarms" {
  source = "github.com/kingletas/terraform-aws-modules//modules/cloudwatch-alarm?ref=af6f00f1646e1e99e635df03b09f9753da8fe59d" # v0.7.0

  alarms = {
    (format("%sstatus-check", local.prefix)) = {
      description         = "Status Check Fail"
      metric_name         = "StatusCheckFailed"
      namespace           = "AWS/EC2"
      dimensions          = { InstanceId = local.instance_id }
      comparison_operator = "GreaterThanThreshold"
      threshold           = var.healthbot_status_check_threshold
      evaluation_periods  = var.evaluation_period
      datapoints_to_alarm = var.datapoints_to_alarm
      period              = var.statistic_period
      statistic           = var.statistic
      alarm_actions       = var.alarm_actions
      ok_actions          = var.ok_actions
    }

    (format("%scpu-utilization-high", local.prefix)) = {
      description         = "CPU utilization too high"
      metric_name         = "CPUUtilization"
      namespace           = "AWS/EC2"
      dimensions          = { InstanceId = local.instance_id }
      comparison_operator = "GreaterThanThreshold"
      threshold           = var.healthbot_cpu_utilization_too_high
      evaluation_periods  = var.healthbot_cpu_utilization_evaluation_period
      datapoints_to_alarm = var.healthbot_cpu_utilization_datapoints_to_alarm
      period              = var.statistic_period
      statistic           = var.statistic
      alarm_actions       = concat(var.alarm_actions, [data.aws_sns_topic.this.arn])
      ok_actions          = var.ok_actions
    }
  }

  tags = local.tags
}

resource "aws_key_pair" "this" {
  key_name   = format("%sssh-key", local.prefix)
  public_key = file(var.ssh_key["public"])

  tags = merge(local.tags,
    {
      "Name" = format("%s SSH Key", var.name)
    }
  )
}
