# To Do

Everything genuinely open, grouped by what unblocks it. What's already shipped is in [CHANGELOG.md](CHANGELOG.md).

| Area | Item | Blocked on |
|---|---|---|
| Runtime | R4 — Python / AMI pairing | a decision |
| Terraform | v6 plan diff against real state | AWS credentials |
| Terraform | simplify the build | the plan diff |
| Delivery | DORA deploy hook in the playbook | a deploy target |
| Alerting | route burn-rate alerts | 30 days of real telemetry |
| IT/local | auto-feed CloudWatch | nothing — just work |

## Needs a decision

- [ ] **R4 — the runtime Python / AMI pairing.** `requires-python` says ≥3.12 while the playbook installs stock apt Python; the Python bump and the Packer base rebuild are one piece of work, decided together.

## Needs live AWS

- [ ] **Run the v6 provider plan diff against real state.** The tree validates clean, but three provider majors deserve a real `terraform plan` before any apply.
- [ ] **Simplify the Terraform build** (after the plan diff, so refactors diff against a known-good baseline):
    - [ ] remove the variables complexities
    - [ ] collapse the four AWS providers to one default + one aliased reader
    - [ ] stop seeding secret values entirely — `ignore_changes` is already in place

## Needs a deploy target

- [ ] **Wire `healthbot-dora record deploy --sha …` into the playbook.** One line at the end of the play; deliberately not added until a deploy actually runs, so an unwired journal can never read as elite performance.

## Needs time and data

- [ ] **Route the burn-rate alerts** (Alertmanager) — only after the thresholds survive a backtest over 30 days of real telemetry. The clock starts when the bot runs somewhere real with `HB_OTEL_ENABLED=1`.

## IT/local

- [ ] **Auto-feed CloudWatch** — a feeder container or compose service around `healthbot-local feed`, so a local run needs no manual step between seeds.
