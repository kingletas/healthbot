locals {
  name      = format("%s-%s", var.name, var.environment)
  prefix    = lower(format("%s-", local.name))
  sm_prefix = lower(format("/%s-sm/manager/", local.name))

  tags = {
    "Name"        = local.name
    "Owner"       = var.owner_tag
    "Environment" = format("%s-%s", title(var.environment), var.environment_tag_suffix)
  }

  secret_name = format("%ssm-%s", local.prefix,
    random_string.this.result
  )

  etc_env_file = lower(format("/etc/%s.env", var.name))

}
