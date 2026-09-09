build {
  sources = ["source.amazon-ebs.ubuntu_latest"]

  provisioner "shell" {
    script = "bin/install"
  }

  provisioner "ansible-local" {

    playbook_dir  = format("%s/../ansible/", abspath(path.root))
    playbook_file = format("%s/../ansible/playbook.yml", abspath(path.root))
  }

  provisioner "shell" {
    script = "bin/cleanup"
  }

  error-cleanup-provisioner "shell" {
    script = "bin/cleanup"
  }
}
