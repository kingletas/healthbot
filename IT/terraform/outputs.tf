output "ec2-healthbot-instance" {
  value = aws_instance.this.public_dns
}
