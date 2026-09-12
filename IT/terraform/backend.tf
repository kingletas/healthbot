terraform {
  # Partial configuration: the bucket, key and region name one deployment's
  # state, so they are supplied at init time rather than committed. Copy
  # backend.hcl.example, fill it in, and run:
  #
  #     terraform init -backend-config=backend.hcl
  #
  # CI passes -backend=false and never touches state at all.
  backend "s3" {
    encrypt      = true
    use_lockfile = true
  }
}
