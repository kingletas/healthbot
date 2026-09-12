locals {
  timestamp = regex_replace(timestamp(), "[- TZ:]", "")
  Name      = format("%s %s %s", var.tag_name, var.tag_service, local.timestamp)

  tags = {
    Environment = var.tag_environment
    Name        = local.Name
    Owner       = var.tag_owner
    Service     = var.tag_service
  }

}
