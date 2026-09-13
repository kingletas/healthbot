# A base image: the application is installed afterwards by IT/ansible over SSH.
# The deploy playbook needs a wheel that only exists on the control machine.
build {
  sources = ["source.amazon-ebs.ubuntu_latest"]

  provisioner "shell" {
    script = "bin/install"
  }

  provisioner "shell" {
    script = "bin/cleanup"
  }

  error-cleanup-provisioner "shell" {
    script = "bin/cleanup"
  }
}
