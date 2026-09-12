### General

variable "communicator" {
  type        = string
  default     = "ssh"
  description = "The Packer Communicator to use"
}


####
# AWS Required
####
variable "profile" {
  default     = env("PACKER_AWS_PROFILE")
  type        = string
  description = "AWS Profile to work with if using different keys"
}
variable "skip_create_ami" {
  type        = string
  default     = false
  description = "Setting to make sure we don't create the ami during the test/development"
}

variable "subnet_id" {
  type        = string
  default     = env("PACKER_SUBNET_ID")
  description = "The subnet where we want to create this AMI"
}


variable "ami_name" {
  type        = string
  description = "The name we want to use with the AMI"
}
variable "instance_type" {
  type        = string
  default     = "t2.micro"
  description = "The Instance Type"
}
variable "tag_environment" {
  type        = string
  description = "The environment for this ami/instance"
}
variable "tag_owner" {
  type        = string
  description = "The owner for this ami/instance"
}
variable "tag_name" {
  type        = string
  description = "The name of the instance/ami"
}
variable "tag_service" {
  type        = string
  description = "The type of service we are creating"
}
variable "ssh_username" {
  type        = string
  default     = "ubuntu"
  description = "default ssh user"
}
variable "ssh_timeout" {
  type        = string
  default     = "15m"
  description = "How long do we want to wait for the SSH connection"
}


####
# Ubuntu AMI information
####
# 24.04 noble, because that is the pairing the wheel forces: pyproject
# requires Python >= 3.12 and noble is the first LTS whose stock python3 is
# 3.12, so bin/install needs no deadsnakes PPA. The filter was impish 21.10,
# which reached end of life in July 2022. That is an unpatched base image, and a
# Python three minors below what the package will install on.
# Canonical moved noble images to hvm-ssd-gp3; earlier releases are hvm-ssd.
variable "ubuntu_latest" {
  type    = string
  default = "ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"
}

# Canonical's AWS account. AMIs are matched by owner as well as name so a
# lookalike name in somebody else's account cannot be picked up.
variable "ubuntu_ami_id" {
  type    = string
  default = "099720109477"
}
