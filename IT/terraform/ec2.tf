resource "aws_iam_role" "this" {
  name = format("%srole", local.prefix)

  assume_role_policy = data.aws_iam_policy_document.assume-policy.json

  tags = local.tags
}

resource "aws_iam_instance_profile" "this" {
  name = format("%sprofile", local.prefix)
  role = aws_iam_role.this.name
}


resource "aws_iam_role_policy" "this" {
  name = format("%ssm-policy", local.prefix)
  role = aws_iam_role.this.id

  policy = data.aws_iam_policy_document.allow-policy.json

}

resource "aws_instance" "this" {
  ami                  = data.aws_ami.this.id
  instance_type        = var.instance_type
  iam_instance_profile = aws_iam_instance_profile.this.name
  key_name             = aws_key_pair.this.key_name

  vpc_security_group_ids      = [aws_security_group.this["ssh"].id]
  subnet_id                   = data.aws_subnet.this.id
  associate_public_ip_address = var.associate_public_ip_address

  availability_zone = data.aws_availability_zones.this.names[0]

  user_data = data.cloudinit_config.this.rendered

  //not applicable to the smallish instances
  ebs_optimized = var.ebs_enabled

  monitoring = true
  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  root_block_device {
    volume_type           = var.volume_type
    volume_size           = var.volume_size
    delete_on_termination = var.delete_on_termination
    # gp2 takes no provisioned iops: the v3 provider tolerated iops = 0 here,
    # later majors reject it at plan time; null omits the argument entirely
    iops      = (var.volume_type == "gp2" ? null : var.iops)
    encrypted = true

    kms_key_id = module.kms.key_id

    tags = merge(local.tags,
      {
        "Name" = format("%s EBS", var.name)
      }
    )
  }

  lifecycle {
    create_before_destroy = true

    # A payload cloud-init cannot read boots a machine with no environment
    # file, and nothing on the instance reports that.
    precondition {
      condition     = strcontains(local.boot_payload, "#cloud-config") && strcontains(local.boot_payload, local.etc_env_file)
      error_message = "The user_data payload does not decode to a cloud-config that writes ${local.etc_env_file}, so a fresh instance would come up without its environment file. Check data.cloudinit_config.this: this assertion reads an uncompressed payload, so gzip has to stay off for it to hold."
    }
  }

  tags = merge(local.tags,
    {
      "Name" = format("%s EC2 Instance", var.name)
    }
  )
}

# Keyed by the deployment name, which is known at plan time; the instance id
# goes in dimensions, where an unknown value is fine.
module "alarms" {
  source = "github.com/kingletas/terraform-aws-modules//modules/cloudwatch-alarm?ref=5e0ae490c797bb1e8178bea00c41cc9d4c060111" # v0.6.0

  alarms = {
    (format("%sstatus-check", local.prefix)) = {
      description         = "Status Check Fail"
      metric_name         = "StatusCheckFailed"
      namespace           = "AWS/EC2"
      dimensions          = { InstanceId = aws_instance.this.id }
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
      dimensions          = { InstanceId = aws_instance.this.id }
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
