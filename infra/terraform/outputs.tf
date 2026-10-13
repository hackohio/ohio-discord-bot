output "public_ip" {
  description = "Public IP of the bot server. Changes every time the server is recreated."
  value       = aws_lightsail_instance.bot.public_ip_address
}

output "webhook_url" {
  description = "URL to give the registration/intake system."
  value       = "https://${aws_lightsail_instance.bot.public_ip_address}/post/user"
}

output "cloudwatch_agent_access_key_id" {
  description = "Access key for the least-privilege CloudWatch Agent user."
  value       = aws_iam_access_key.cloudwatch_agent.id
  sensitive   = true
}

output "cloudwatch_agent_secret_access_key" {
  description = "Secret key for the least-privilege CloudWatch Agent user."
  value       = aws_iam_access_key.cloudwatch_agent.secret
  sensitive   = true
}
