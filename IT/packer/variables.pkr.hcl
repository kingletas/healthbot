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
#variable "default" { type = string }
variable "aws" { type = string }
variable "skip_create_ami" {
  type        = string
  default     = false
  description = "Setting to make sure we don't create the ami during the test/development"
}

variable "vpc_id" {
  type        = string
  default     = env("PACKER_VPC_ID")
  description = "The VPC ID to work with"
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
variable "ubuntu_focal" {
  type    = string
  default = "ubuntu/images/hvm-ssd/ubuntu-focal-20.04-amd64-server-*"
}

variable "ubuntu_bionic" {
  type    = string
  default = "ubuntu/images/hvm-ssd/ubuntu-bionic-18.04-amd64-server-*"
}
variable "ubuntu_groovy" {
  type    = string
  default = "ubuntu/images/hvm-ssd/ubuntu-groovy-20.10-amd64-server-*"
}

variable "ubuntu_latest" {
  type    = string
  default = "ubuntu/images/hvm-ssd/ubuntu-impish-21.10-amd64-server-*"
}

variable "ubuntu_ami_id" {
  type    = string
  default = "099720109477"
}
