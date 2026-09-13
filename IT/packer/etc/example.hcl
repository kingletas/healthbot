# A working var file you can validate against as-is. For a real build,
# copy it and set your own values:
#   cp etc/example.hcl etc/dev.hcl
#
# The AWS profile and subnet come from the environment instead, so nothing
# about your account is written down here:
#   PACKER_AWS_PROFILE=...  PACKER_SUBNET_ID=subnet-...
ami_name        = "healthbot"
instance_type   = "t2.micro"
tag_name        = "healthbot"
tag_service     = "SRE"
tag_owner       = "platform"
tag_environment = "healthbot-dev"
