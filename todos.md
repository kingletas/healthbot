# To Do

Everything genuinely open, grouped by what unblocks it. What's already shipped is in [CHANGELOG.md](CHANGELOG.md).

| Area | Item | Blocked on |
|---|---|---|
| Terraform | v6 plan diff against real state | AWS credentials |
| Packer | an AMI build against real AWS | AWS credentials |
| Terraform | simplify the build | the plan diff |
| Alerting | route burn-rate alerts | 30 days of real telemetry |

## Needs live AWS

- [ ] **Build the AMI once against real AWS.** The template validates and the playbook it runs is proven against a 24.04 container, but no AMI has been built since the base moved to noble. Check the image filter resolves before trusting it:

    ```bash
    aws ec2 describe-images --owners 099720109477 \
      --filters 'Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*' \
      --query 'reverse(sort_by(Images,&CreationDate))[:3].[Name,ImageId]' --output table
    ```

- [ ] **Run the v6 provider plan diff against real state.** The tree validates clean, but three provider majors deserve a real `terraform plan` before any apply.
- [ ] **Simplify the Terraform build** (what is left needs the plan diff, so a refactor diffs against a known-good baseline):
    - [x] ~~remove the variables complexities~~. Two unused variables and three unused locals are gone. Safe without the plan diff for a reason that does not extend to the rest: **variables and locals are never recorded in state**, so removing one nothing references cannot change a plan. tflint went 9 findings to 4.
    - [ ] collapse the four AWS providers to one default + one aliased reader. **This one does need state.** A provider alias *is* recorded, as the provider address of every resource created through it, so an alias unused in the configuration can still be the address a resource in state is bound to, and the local `terraform.tfstate` is empty because the real state is in the S3 backend.
    - [ ] stop seeding secret values entirely; `ignore_changes` is already in place. Changes real resources; needs the plan diff.
- [ ] **Give the KMS key an explicit policy.** It runs on the default policy, which lets any IAM principal in the account use it if their own policy allows. A policy changes who can use the live key, so it needs the plan diff first. checkov's `CKV2_AWS_64` is skipped in `kms.tf` until then.
- [ ] **Rotate the secret's tokens automatically.** Secrets Manager rotation needs a function per vendor token, one each for Twilio, Slack, New Relic and Google, and none is written. checkov's `CKV2_AWS_57` is skipped in `main.tf` until then.

## Needs time and data

- [ ] **Route the burn-rate alerts** (Alertmanager), only after the thresholds survive a backtest over 30 days of real telemetry. The clock starts when the bot runs somewhere real with `HB_OTEL_ENABLED=1`.
