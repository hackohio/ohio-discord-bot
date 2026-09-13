variable "region" {
  description = "AWS region to run the bot in."
  type        = string
  default     = "us-east-2"
}

variable "instance_name" {
  description = "Name of the Lightsail instance (shows up in the Lightsail console)."
  type        = string
  default     = "ohio-discord-bot"
}

variable "blueprint_id" {
  description = "Operating system image. List options with: aws lightsail get-blueprints"
  type        = string
  default     = "ubuntu_24_04"
}

variable "bundle_id" {
  description = "Server size. nano_3_0 is the cheapest Lightsail plan. List options with: aws lightsail get-bundles"
  type        = string
  default     = "nano_3_0"
}

variable "ssh_public_key" {
  description = "Public half of the SSH key the workflows use to log in (the SSH_PUBLIC_KEY GitHub secret)."
  type        = string
}

variable "ssh_allowed_cidrs" {
  description = "IP ranges allowed to SSH in. SSH only accepts the deploy key, so this is open by default."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "web_port" {
  description = "Port the registration webhook listens on. Must match [web] port in config.ini; the workflows read it from there."
  type        = number
  default     = 5000
}
