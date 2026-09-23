# Standard library imports
from os import path

__version__ = "0.2.0"
__app_name__ = "healthbot"

main_path = path.dirname(__file__)
config_d = path.join(main_path, "config")


# Appended to the titled environment to form the EC2 tag:Environment value,
# so "Production" plus this becomes "Production-FLEET". Terraform tags the fleet
# with the same suffix and local_env seeds it, so all three must agree;
# site.yml's environment_tag_suffix overrides it for a deployment.
DEFAULT_ENV_TAG_SUFFIX = "FLEET"
