# terraform

## Supplying the variables

Every `*.tfvars` file is gitignored, so `terraform.tfvars.example` is the only tracked list of what a plan needs. Copy it and replace the values it marks:

```bash
cp terraform.tfvars.example terraform.tfvars
```

Twenty-four variables are declared with no default, and a plan stops on the first one it cannot find. Six of them name infrastructure or files that must already exist: `vpc_id`, `subnet_id`, `db_cluster_identifier`, `sns_name`, `ssh_key` and `secrets_path`.

`make terraform` runs `tf-vars-check.sh`, which refuses a commit where the example and `variables.tf` disagree in either direction: a required variable the example does not supply, or a name in the example that nothing declares. Terraform itself only catches the first of those, and treats the second as a warning. That asymmetry is how `ga_view_id` outlived the rename to `ga_property_id`, leaving the value supplied under a name that reached nothing.

## Planning without an AWS account

`make tf-local` plans this configuration against a local AWS emulator, so you can check it is coherent with no account and no credentials.

Start a LocalStack-compatible emulator listening on `172.17.0.1:4566`, then:

```bash
make tf-local
```

If yours listens somewhere else, set `HB_LOCAL_AWS_ENDPOINT` to its address. On anything other than Linux you will need to, because `172.17.0.1` is the Docker bridge address and only exists there.

Each run reseeds what the data sources read, plans, and leaves the emulator holding the result. `make tf-local ACTION=apply` applies it and `make tf-local ACTION=clean` destroys it and removes the generated root.

**What it proves:** the configuration parses, every variable resolves, all six data sources it reads are found, and a plan reaches a full diff of seventeen resources. It generates its own root module outside this repository and never loads your `terraform.tfvars`, so no real credential can reach the emulator. It plans with `terraform.tfvars.example`, which is what keeps that file able to plan.

**What it does not prove:** anything about real AWS. An emulator answers the same API shapes, not the same service. Treat a clean local plan as a reason to try a real one, never as a substitute for it.

### What the emulator will not apply

An apply creates fourteen of the seventeen, and a plan afterwards reports a residue that does not shrink. All of it is emulator fidelity rather than anything wrong with the configuration, so a migration is proved by the residue staying exactly the same, not by reaching `No changes`.

| Left over | Why |
| --- | --- |
| `aws_instance.this` | The emulator refuses `RunInstances` against an AMI it registered itself, though it reports that AMI as `available` and launches its own built-in images. `CopyImage` is unimplemented, so a self-owned copy of a built-in image is not available either. |
| both `aws_cloudwatch_metric_alarm` resources | Their dimensions read `aws_instance.this.id`, so they wait on the instance above. |
| `aws_key_pair.this` updated in place | The emulator does not persist tags on a key pair, so the same three tags are planned on every run. |

Nothing is worked around in the deployable configuration for any of these, and none of them is a statement about real EC2.

## State holds your credentials in plaintext

Terraform records every value it manages, and this configuration builds a Secrets Manager secret out of the vendor tokens you pass in. **A state file from this tree is as sensitive as those tokens**, and so is any `.backup` Terraform leaves beside it. Nothing encrypts it for you locally.

Keep state in the S3 backend, which is where `backend.tf` points and where it is encrypted and versioned. A local `terraform.tfstate` only appears when you apply without a backend, which is easy to do by accident on a first run and easy to forget afterwards.

`.gitignore` keeps state out of an ordinary `git add`, and `make tfstate` refuses a forced one, in CI as well as on your machine. **Neither reaches a copy already sitting on your disk.** If you find one, treat every credential in it as exposed for as long as the file has existed, rotate them, then delete it.

## The generated table below is generated

Everything between the markers is written by `terraform-docs` from `variables.tf` and the resources. Change it with `make tf-docs`, not by hand, and `make check` refuses a table that no longer matches.

<!-- BEGIN_TF_DOCS -->
Good ways to check for security or visualize what's going on
checkov -d .
terraform graph -type=plan | dot -Tpng -o graph.png

## Requirements

| Name | Version |
| ---- | ------- |
| <a name="requirement_terraform"></a> [terraform](#requirement\_terraform) | ~> 1.10 |
| <a name="requirement_aws"></a> [aws](#requirement\_aws) | ~>6.61.0 |
| <a name="requirement_cloudinit"></a> [cloudinit](#requirement\_cloudinit) | ~>2.4 |
| <a name="requirement_random"></a> [random](#requirement\_random) | ~>3.9 |

## Providers

| Name | Version |
| ---- | ------- |
| <a name="provider_aws"></a> [aws](#provider\_aws) | 6.61.0 |
| <a name="provider_cloudinit"></a> [cloudinit](#provider\_cloudinit) | 2.4.0 |
| <a name="provider_random"></a> [random](#provider\_random) | 3.9.0 |

## Modules

| Name | Source | Version |
| ---- | ------ | ------- |
| <a name="module_kms"></a> [kms](#module\_kms) | github.com/kingletas/terraform-aws-modules//modules/kms-key | 71e3b4bc696910d279cce526c215208cd9b28c42 |

## Resources

| Name | Type |
| ---- | ---- |
| [aws_cloudwatch_metric_alarm.healthbot_cpu_utilization_too_high](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_metric_alarm) | resource |
| [aws_cloudwatch_metric_alarm.healthbot_status_check_failed](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_metric_alarm) | resource |
| [aws_iam_instance_profile.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_instance_profile) | resource |
| [aws_iam_role.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role_policy.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_instance.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/instance) | resource |
| [aws_key_pair.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/key_pair) | resource |
| [aws_secretsmanager_secret.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/secretsmanager_secret) | resource |
| [aws_secretsmanager_secret_version.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/secretsmanager_secret_version) | resource |
| [aws_security_group.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/security_group) | resource |
| [aws_ssm_parameter.hb_db_identifier](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ssm_parameter) | resource |
| [aws_ssm_parameter.hb_environment](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ssm_parameter) | resource |
| [aws_ssm_parameter.hb_secret_name](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ssm_parameter) | resource |
| [aws_ssm_parameter.hb_tag_name](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ssm_parameter) | resource |
| [random_string.this](https://registry.terraform.io/providers/hashicorp/random/latest/docs/resources/string) | resource |
| [aws_ami.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/ami) | data source |
| [aws_availability_zones.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/availability_zones) | data source |
| [aws_caller_identity.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/caller_identity) | data source |
| [aws_iam_policy_document.allow-policy](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.assume-policy](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_partition.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/partition) | data source |
| [aws_rds_cluster.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/rds_cluster) | data source |
| [aws_region.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/region) | data source |
| [aws_sns_topic.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/sns_topic) | data source |
| [aws_subnet.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/subnet) | data source |
| [aws_vpc.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/vpc) | data source |
| [cloudinit_config.this](https://registry.terraform.io/providers/hashicorp/cloudinit/latest/docs/data-sources/config) | data source |

## Inputs

| Name | Description | Type | Default | Required |
| ---- | ----------- | ---- | ------- | :------: |
| <a name="input_alarm_actions"></a> [alarm\_actions](#input\_alarm\_actions) | The list of actions to execute when this alarm transitions into an ALARM state from any other state. Each action is specified as an Amazon Resource Name (ARN). | `list(string)` | <pre>[<br/>  "arn:aws:automate:us-east-2:ec2:reboot"<br/>]</pre> | no |
| <a name="input_app_environment_name"></a> [app\_environment\_name](#input\_app\_environment\_name) | Healthbot Environment name | `string` | n/a | yes |
| <a name="input_app_environment_tag_name"></a> [app\_environment\_tag\_name](#input\_app\_environment\_tag\_name) | Healthbot Environment tag name to get AWS Resources | `string` | n/a | yes |
| <a name="input_associate_public_ip_address"></a> [associate\_public\_ip\_address](#input\_associate\_public\_ip\_address) | Add a static IP to the instance | `bool` | `false` | no |
| <a name="input_datapoints_to_alarm"></a> [datapoints\_to\_alarm](#input\_datapoints\_to\_alarm) | The number of datapoints that must be breaching to trigger the alarm | `number` | `1` | no |
| <a name="input_db_cluster_identifier"></a> [db\_cluster\_identifier](#input\_db\_cluster\_identifier) | Database cluster to work with | `string` | n/a | yes |
| <a name="input_delete_on_termination"></a> [delete\_on\_termination](#input\_delete\_on\_termination) | Delete any volumes on termination | `bool` | `true` | no |
| <a name="input_ebs_enabled"></a> [ebs\_enabled](#input\_ebs\_enabled) | Enable EBS | `bool` | `true` | no |
| <a name="input_egress_map"></a> [egress\_map](#input\_egress\_map) | Outgoing port maps | <pre>object({<br/>    from_port   = number,<br/>    to_port     = number,<br/>    protocol    = string,<br/>    cidr_blocks = list(string)<br/>  })</pre> | n/a | yes |
| <a name="input_environment"></a> [environment](#input\_environment) | What environment we are deploying to | `string` | n/a | yes |
| <a name="input_environment_tag_suffix"></a> [environment\_tag\_suffix](#input\_environment\_tag\_suffix) | Appended to the titled environment to form the Environment tag HealthBot filters the fleet on | `string` | `"FLEET"` | no |
| <a name="input_evaluation_period"></a> [evaluation\_period](#input\_evaluation\_period) | How many periods would trigger an alarm | `number` | `1` | no |
| <a name="input_ga_property_id"></a> [ga\_property\_id](#input\_ga\_property\_id) | GA4 property to read realtime active users from, numeric or properties/<id> | `string` | n/a | yes |
| <a name="input_healthbot_cpu_utilization_datapoints_to_alarm"></a> [healthbot\_cpu\_utilization\_datapoints\_to\_alarm](#input\_healthbot\_cpu\_utilization\_datapoints\_to\_alarm) | The number of datapoints that must be breaching to trigger the alarm | `number` | `3` | no |
| <a name="input_healthbot_cpu_utilization_evaluation_period"></a> [healthbot\_cpu\_utilization\_evaluation\_period](#input\_healthbot\_cpu\_utilization\_evaluation\_period) | How many periods would trigger an alarm | `number` | `4` | no |
| <a name="input_healthbot_cpu_utilization_too_high"></a> [healthbot\_cpu\_utilization\_too\_high](#input\_healthbot\_cpu\_utilization\_too\_high) | Threshold for the instance to report a high cpu usage | `number` | `90` | no |
| <a name="input_healthbot_status_check_threshold"></a> [healthbot\_status\_check\_threshold](#input\_healthbot\_status\_check\_threshold) | Threshold for the instance to fail a check | `number` | `0.99` | no |
| <a name="input_ingress_map"></a> [ingress\_map](#input\_ingress\_map) | Incoming port maps | <pre>map(object({<br/>    from_port = number,<br/>    to_port   = number,<br/>    protocol  = string,<br/>    cidr_blocks = list(string) }<br/>    )<br/>  )</pre> | n/a | yes |
| <a name="input_instance_type"></a> [instance\_type](#input\_instance\_type) | AWS Instance type | `string` | `"t2.micro"` | no |
| <a name="input_iops"></a> [iops](#input\_iops) | EBS throughput | `string` | `100` | no |
| <a name="input_king_slack_token"></a> [king\_slack\_token](#input\_king\_slack\_token) | Debugging token | `string` | n/a | yes |
| <a name="input_name"></a> [name](#input\_name) | Name of the application | `string` | n/a | yes |
| <a name="input_new_relic_api"></a> [new\_relic\_api](#input\_new\_relic\_api) | New Relic API key to get the data | `string` | n/a | yes |
| <a name="input_ok_actions"></a> [ok\_actions](#input\_ok\_actions) | Actions to perform when the instance is fine | `list(any)` | `[]` | no |
| <a name="input_owner_tag"></a> [owner\_tag](#input\_owner\_tag) | Team the provisioned resources belong to | `string` | `"Platform"` | no |
| <a name="input_production_profile"></a> [production\_profile](#input\_production\_profile) | Profile the aws\_production provider alias authenticates with; null leaves it on the ambient credential chain | `string` | `null` | no |
| <a name="input_profile"></a> [profile](#input\_profile) | Profile to use with Terraform | `string` | n/a | yes |
| <a name="input_region"></a> [region](#input\_region) | Default region where we are deploying the app to | `string` | n/a | yes |
| <a name="input_secrets_path"></a> [secrets\_path](#input\_secrets\_path) | GA secrets file | `string` | n/a | yes |
| <a name="input_slack_channel"></a> [slack\_channel](#input\_slack\_channel) | Slack channel to post messages to | `string` | n/a | yes |
| <a name="input_slack_token"></a> [slack\_token](#input\_slack\_token) | Token for the Bot App | `string` | n/a | yes |
| <a name="input_sns_name"></a> [sns\_name](#input\_sns\_name) | SNS topic to send notifications to | `string` | n/a | yes |
| <a name="input_ssh_key"></a> [ssh\_key](#input\_ssh\_key) | SSH Key Configuration map | `map(any)` | n/a | yes |
| <a name="input_statistic"></a> [statistic](#input\_statistic) | How to calculate the alarm | `string` | `"Average"` | no |
| <a name="input_statistic_period"></a> [statistic\_period](#input\_statistic\_period) | The period in seconds over which the specified statistic is applied. | `number` | `900` | no |
| <a name="input_subnet_id"></a> [subnet\_id](#input\_subnet\_id) | Subnet where to place the resources | `string` | n/a | yes |
| <a name="input_twilio_account"></a> [twilio\_account](#input\_twilio\_account) | Account to use for Twilio | `string` | n/a | yes |
| <a name="input_twilio_from"></a> [twilio\_from](#input\_twilio\_from) | Number sending the SMS provided by twilio | `number` | n/a | yes |
| <a name="input_twilio_to"></a> [twilio\_to](#input\_twilio\_to) | Number to send SMS to | `number` | n/a | yes |
| <a name="input_twilio_token"></a> [twilio\_token](#input\_twilio\_token) | Token to connect with Twilio | `string` | n/a | yes |
| <a name="input_user_slack_token"></a> [user\_slack\_token](#input\_user\_slack\_token) | Token to post as the user instead of the bot | `string` | n/a | yes |
| <a name="input_volume_size"></a> [volume\_size](#input\_volume\_size) | How big should the instance be | `string` | `10` | no |
| <a name="input_volume_type"></a> [volume\_type](#input\_volume\_type) | Type of volume to use with the instances | `string` | `"gp2"` | no |
| <a name="input_vpc_id"></a> [vpc\_id](#input\_vpc\_id) | VPC to place the resources | `string` | n/a | yes |

## Outputs

| Name | Description |
| ---- | ----------- |
| <a name="output_ec2-healthbot-instance"></a> [ec2-healthbot-instance](#output\_ec2-healthbot-instance) | n/a |
<!-- END_TF_DOCS -->
