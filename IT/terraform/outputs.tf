output "ec2-healthbot-instance" {
  description = "The instance's public IP address, or null when it has none."
  value       = lookup(module.instance.public_ips, local.instance_name, null)

  # A payload cloud-init cannot read boots a machine with no environment file,
  # and nothing on the instance reports that.
  precondition {
    condition     = strcontains(local.boot_payload, "#cloud-config") && strcontains(local.boot_payload, local.etc_env_file)
    error_message = "The user_data payload does not decode to a cloud-config that writes ${local.etc_env_file}, so a fresh instance would come up without its environment file. Check data.cloudinit_config.this: this assertion reads an uncompressed payload, so gzip has to stay off for it to hold."
  }

  # HealthBot finds its fleet by the Environment tag it also carries, then by a
  # case-sensitive Name glob of *<TAG NAME>*. Only the name keeps it from
  # monitoring itself.
  precondition {
    condition     = !strcontains(local.instance_name, upper(var.app_environment_tag_name))
    error_message = "The instance would be named ${local.instance_name}, which matches HealthBot's own fleet filter *${upper(var.app_environment_tag_name)}*, so it would start monitoring itself. Choose a name or app_environment_tag_name that does not overlap."
  }
}
