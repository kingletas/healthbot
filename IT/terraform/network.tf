resource "aws_security_group" "this" {
  #checkov:skip=CKV2_AWS_5:aws_instance.this attaches the ssh group, and checkov cannot follow a for_each key. Any other key in ingress_map makes a group nothing uses.

  for_each    = var.ingress_map
  description = format("%s %s sg", local.name, each.key)
  name        = format("%s%s-sg", local.prefix, each.key)
  vpc_id      = data.aws_vpc.this.id


  ingress {
    from_port   = each.value.from_port
    to_port     = each.value.to_port
    protocol    = each.value.protocol
    cidr_blocks = each.value.cidr_blocks
    description = format("%s %s ingress port: %s", local.name, each.key, each.value.from_port)
  }

  egress {
    from_port   = var.egress_map.from_port
    to_port     = var.egress_map.to_port
    protocol    = var.egress_map.protocol
    cidr_blocks = var.egress_map.cidr_blocks
    description = format("%s %s egress port: %s", local.name, each.key, var.egress_map.from_port)
  }

  tags = merge(local.tags,
    {
      "Name" = format("%s%s-sg", local.prefix, each.key)
    }
  )
}
