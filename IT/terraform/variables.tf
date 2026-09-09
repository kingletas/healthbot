variable "name" {
  description = "Name of the application"
  type        = string
}
variable "region" {
  description = "Default region where we are deploying the app to"
  type        = string
}
variable "environment" {
  description = "What environment we are deploying to"
  type        = string
}

variable "app_environment_name" {
  description = "Healthbot Environment name"
  type        = string
}
variable "app_environment_tag_name" {
  description = "Healthbot Environment tag name to get AWS Resources"
  type        = string
}
variable "profile" {
  description = "Profile to use with Terraform"
  type        = string
}

variable "environment_tag_suffix" {
  description = "Appended to the titled environment to form the Environment tag HealthBot filters the fleet on"
  type        = string
  default     = "FLEET"
}
variable "owner_tag" {
  description = "Team the provisioned resources belong to"
  type        = string
  default     = "Platform"
}
variable "db_cluster_identifier" {
  description = "Database cluster to work with"
  type        = string
}

variable "vpc_id" {
  description = "VPC to place the resources"
  type        = string
}
variable "subnet_id" {
  description = "Subnet where to place the resources"
  type        = string
}
variable "ssh_key" {

  description = "SSH Key Configuration map"
  type        = map(any)


}
variable "instance_type" {
  description = "AWS Instance type"
  default     = "t2.micro"

}
variable "volume_type" {
  description = "Type of volume to use with the instances"
  type        = string
  default     = "gp2"

}
variable "volume_size" {
  description = "How big should the instance be"

  type    = string
  default = 10

}
variable "delete_on_termination" {
  description = "Delete any volumes on termination"
  type        = bool
  default     = true
}
variable "enable_deletion_protection" {
  description = "Protect against deletion"
  type        = bool
  default     = false
}
variable "iops" {
  description = "EBS throughput"
  type        = string
  default     = 100

}
variable "enable_dns_hostnames" {
  description = "Enable the DNS hostnames"
  type        = bool
  default     = true

}

variable "associate_public_ip_address" {
  description = "Add a static IP to the instance"
  type        = bool
  default     = false

}

variable "ebs_enabled" {
  description = "Enable EBS"
  type        = bool
  default     = true
}

variable "ingress_map" {
  description = "Incoming port maps"
  type = map(object({
    from_port = number,
    to_port   = number,
    protocol  = string,
    cidr_blocks = list(string) }
    )
  )

}
variable "egress_map" {
  description = "Outgoing port maps"

  type = object({
    from_port   = number,
    to_port     = number,
    protocol    = string,
    cidr_blocks = list(string)
  })
}

/**
* Secrets values
*/
variable "user_slack_token" {
  description = "Token to post as the user instead of the bot"
  type        = string
  sensitive   = true
}
variable "slack_token" {
  description = "Token for the Bot App"
  type        = string
  sensitive   = true
}
variable "king_slack_token" {
  description = "Debugging token"
  type        = string
  sensitive   = true
}
variable "slack_channel" {
  description = "Slack channel to post messages to"
  type        = string
}
variable "twilio_to" {
  description = "Number to send SMS to"
  type        = number
  sensitive   = true
}
variable "twilio_from" {
  description = "Number sending the SMS provided by twilio"
  type        = number
  sensitive   = true
}
variable "twilio_token" {
  description = "Token to connect with Twilio"
  type        = string
  sensitive   = true
}
variable "twilio_account" {
  description = "Account to use for Twilio"
  type        = string
  sensitive   = true
}
variable "ga_view_id" {
  description = "GA View ID to get the data from"
  type        = string
  sensitive   = true
}
variable "secrets_path" {
  description = "GA secrets file"
  type        = string
}
variable "new_relic_api" {
  description = "New Relic API key to get the data"
  type        = string
  sensitive   = true
}

# CloudWatch Alarm
variable "healthbot_status_check_threshold" {
  default     = 0.99
  type        = number
  description = "Threshold for the instance to fail a check"
}
variable "healthbot_cpu_utilization_too_high" {
  default     = 90
  description = "Threshold for the instance to report a high cpu usage"
  type        = number
}
variable "statistic_period" {
  default     = 900
  type        = number
  description = "The period in seconds over which the specified statistic is applied."
}
variable "statistic" {
  default     = "Average"
  type        = string
  description = "How to calculate the alarm"
}
variable "ok_actions" {
  type        = list(any)
  description = "Actions to perform when the instance is fine"
  default     = []
}
variable "evaluation_period" {
  type        = number
  default     = 1
  description = "How many periods would trigger an alarm"

}
variable "datapoints_to_alarm" {
  type        = number
  default     = 1
  description = "The number of datapoints that must be breaching to trigger the alarm"

}
variable "healthbot_cpu_utilization_datapoints_to_alarm" {
  type        = number
  default     = 3
  description = "The number of datapoints that must be breaching to trigger the alarm"

}

variable "healthbot_cpu_utilization_evaluation_period" {
  type        = number
  default     = 4
  description = "How many periods would trigger an alarm"

}
variable "alarm_actions" {
  default     = ["arn:aws:automate:us-east-2:ec2:reboot"]
  type        = list(string)
  description = "The list of actions to execute when this alarm transitions into an ALARM state from any other state. Each action is specified as an Amazon Resource Name (ARN)."
}
variable "sns_name" {
  type        = string
  description = "SNS topic to send notifications to"
}
