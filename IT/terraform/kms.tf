
resource "random_string" "this" {
  length    = 5
  special   = false
  numeric   = true
  min_lower = 2
  min_upper = 2
}

resource "aws_kms_key" "this" {
  #checkov:skip=CKV2_AWS_64:A declared gap in todos.md: the default key policy delegates to IAM, and an explicit one changes the live key.
  description = format("%s KMS key", var.environment)

  is_enabled = true

  enable_key_rotation     = true
  deletion_window_in_days = 15

  key_usage = "ENCRYPT_DECRYPT"
  tags = merge(local.tags, {
    Name = upper(format("%skms", local.prefix))
  })

}

resource "aws_kms_alias" "this" {
  name          = format("alias/%s", local.name)
  target_key_id = aws_kms_key.this.key_id
}
