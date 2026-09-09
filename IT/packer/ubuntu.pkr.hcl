data "amazon-ami" "ubuntu_latest" {
  filters = {
    name                = var.ubuntu_latest
    root-device-type    = "ebs"
    virtualization-type = "hvm"
  }
  most_recent = true
  owners      = [var.ubuntu_ami_id]
}

/*data "sshkey" "install" {
  name = var.ami_name
}
data "amazon-secretsmanager" "basic-example" {
  name          = "packer_test_secret"
  key           = "packer_test_key"
  version_stage = "example"
}*/
source "amazon-ebs" "ubuntu_latest" {
  ami_name                     = var.ami_name
  profile                      = var.profile
  skip_create_ami              = var.skip_create_ami
  associate_public_ip_address  = true
  communicator                 = var.communicator
  force_deregister             = true
  instance_type                = var.instance_type
  run_tags                     = local.tags
  run_volume_tags              = local.tags
  snapshot_tags                = local.tags
  source_ami                   = data.amazon-ami.ubuntu_latest.id
  ssh_disable_agent_forwarding = true
  ssh_clear_authorized_keys    = true
  encrypt_boot                 = true

  //ssh_private_key_file         = pathexpand(var.ssh_private_key_file)
  ssh_timeout  = var.ssh_timeout
  ssh_username = var.ssh_username
  subnet_id    = var.subnet_id
  tags         = local.tags
}
