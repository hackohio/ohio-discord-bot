output "public_ip" {
  description = "Public IP of the bot server. Changes every time the server is recreated."
  value       = aws_lightsail_instance.bot.public_ip_address
}

output "webhook_url" {
  description = "URL to give the registration/intake system."
  value       = "http://${aws_lightsail_instance.bot.public_ip_address}:${var.web_port}/post/user"
}
