# The whole server: one Lightsail instance, the SSH key it trusts, and its
# firewall. `terraform apply` creates it, `terraform destroy` deletes it (and
# stops the billing).

resource "aws_lightsail_key_pair" "bot" {
  name       = "${var.instance_name}-key"
  public_key = var.ssh_public_key
}

resource "aws_lightsail_instance" "bot" {
  name              = var.instance_name
  availability_zone = "${var.region}a"
  blueprint_id      = var.blueprint_id
  bundle_id         = var.bundle_id
  key_pair_name     = aws_lightsail_key_pair.bot.name

  tags = {
    project    = "ohio-discord-bot"
    managed_by = "terraform"
  }
}

# Replaces Lightsail's default firewall (22 + 80) with exactly the ports the bot needs.
resource "aws_lightsail_instance_public_ports" "bot" {
  instance_name = aws_lightsail_instance.bot.name

  port_info {
    protocol  = "tcp"
    from_port = 22
    to_port   = 22
    cidrs     = var.ssh_allowed_cidrs
  }

  # Registration webhook (web.py). The Discord connection is outbound and needs no open port.
  port_info {
    protocol  = "tcp"
    from_port = var.web_port
    to_port   = var.web_port
    cidrs     = ["0.0.0.0/0"]
  }
}
