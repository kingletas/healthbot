# To Do

Everything genuinely open, grouped by what unblocks it. What's already shipped is in [CHANGELOG.md](CHANGELOG.md).

| Area | Item | Blocked on |
|---|---|---|
| Terraform | v6 plan diff against real state | AWS credentials; proved against MiniStack |
| Packer | an AMI build against real AWS | AWS credentials |
| Terraform | simplify the build | the plan diff |
| Alerting | route burn-rate alerts | 30 days of real telemetry |

## Needs live AWS

- [ ] **Build the AMI once against real AWS.** The template validates and the playbook it runs is proven against a 24.04 container, but an AMI hasn't been built since the base moved to noble. Check the image filter resolves before trusting it:

    ```bash
    aws ec2 describe-images --owners 099720109477 \
      --filters 'Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*' \
      --query 'reverse(sort_by(Images,&CreationDate))[:3].[Name,ImageId]' --output table
    ```

- [ ] **Run the v6 provider plan diff against real state.** The tree validates clean, but don't apply three provider majors without a real `terraform plan` first. Against MiniStack, the tree as it stood before the module-library moves applied 14 of its 17 resources, and the current tree then planned over that state with the KMS key, its alias, the secret and its version moved rather than replaced, and kept their ids through the apply. MiniStack cannot launch the instance, so the instance and the two alarms were never created there. We need more testing against a real account.
- [ ] **Simplify the Terraform build** (what is left needs the plan diff, so a refactor diffs against a known-good baseline):
    - [x] ~~remove the variables complexities~~. Two unused variables and three unused locals are gone. Safe without the plan diff for a reason that doesn't extend to the rest: **variables and locals are never recorded in state**, so removing one nothing references cannot change a plan. tflint went 9 findings to 4.
    - [ ] collapse the four AWS providers to one default + one aliased reader. **This one does need state.** A provider alias *is* recorded, as the provider address of every resource created through it, so an alias unused in the configuration can still be the address a resource in state is bound to, and the local `terraform.tfstate` can't tell you, because it's empty: the real state is in the S3 backend.
    - [ ] stop seeding secret values entirely; `ignore_changes` is already in place. Changes real resources; needs the plan diff.
- [ ] **Give the KMS key an explicit policy.** It runs on the default policy, which lets any IAM principal in the account use it if their own policy allows. A policy changes who can use the live key, so it needs the plan diff first. `kms.tf` passes that default to the library module as `policy_json`, so the gap is written where the key is declared. checkov does not read into a module fetched from git, so `CKV2_AWS_64` no longer reports it.
- [x] ~~**The cloud-init payload is base64-encoded twice and very likely never runs.**~~ **Settled 2026-09-19: it does not happen.** The AWS provider calls `Base64EncodeOnce`, which returns an already-encoded blob unchanged, confirmed three ways: the rendered value is 564 characters and decodes once to a 422-byte MIME body; a `RunInstances` request captured under `TF_LOG=TRACE` carries that exact value; and cloud-init's own processor, run against the decoded bytes, resolves `write_files -> /etc/healthbot.env`. A plan-time precondition now asserts the payload decodes in one step to a cloud-config that writes that file.

    **The claim that `user_data` has a StateFunc hashing it is also wrong for the pinned provider, and this note used to say it did.** The 6.61.0 binary carries the string `user_data attribute is set as cleartext in state` and 5.100.0 does not: v6 removed the hashing. So both `user_data` and `user_data_base64` put the payload in state in clear, and that is no longer a reason to prefer one over the other.

- [ ] **Rotate the secret's tokens automatically.** Secrets Manager rotation needs a function per vendor token, one each for Twilio, Slack, New Relic and Google, and there isn't one yet. The secret's module call in `main.tf` sets no `rotation`. checkov does not read into a module fetched from git, so `CKV2_AWS_57` no longer reports this.

## Needs time and data

- [ ] **Route the burn-rate alerts** (Alertmanager), only after the thresholds survive a backtest over 30 days of real telemetry. The clock starts when the bot runs somewhere real with `HB_OTEL_ENABLED=1`.
