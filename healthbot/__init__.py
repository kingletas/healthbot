#!/usr/bin/env python3

# Standard Library imports
from os import path

__version__ = "0.1.2"
__app_name__ = "healthbot"

main_path = path.dirname(__file__)
config_d = path.join(main_path, "config")
templates_d = path.join(main_path, "templates")


# Appended to the titled environment to form the EC2 tag:Environment value —
# "Production" plus this becomes "Production-FLEET". Terraform tags the fleet
# with the same suffix and local_env seeds it, so all three must agree;
# site.yml's environment_tag_suffix overrides it for a deployment.
DEFAULT_ENV_TAG_SUFFIX = "FLEET"
