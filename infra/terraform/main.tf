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

  # Caddy terminates HTTPS and proxies to the loopback-only registration webhook.
  port_info {
    protocol  = "tcp"
    from_port = 443
    to_port   = 443
    cidrs     = ["0.0.0.0/0"]
  }
}

data "aws_caller_identity" "current" {}

resource "aws_iam_user" "cloudwatch_agent" {
  name = "${var.instance_name}-cloudwatch-agent"
}

resource "aws_iam_user_policy" "cloudwatch_agent" {
  name = "publish-health-metrics"
  user = aws_iam_user.cloudwatch_agent.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "cloudwatch:PutMetricData"
      Resource = "*"
      Condition = {
        StringEquals = {
          "cloudwatch:namespace" = "HackOHIO/Lightsail"
        }
      }
    }]
  })
}

resource "aws_iam_access_key" "cloudwatch_agent" {
  user = aws_iam_user.cloudwatch_agent.name
}

resource "aws_sns_topic" "alerts" {
  name = "${var.instance_name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_sns_topic_policy" "alerts" {
  arn = aws_sns_topic.alerts.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowCloudWatchAlarmsToPublish"
      Effect    = "Allow"
      Principal = { Service = "cloudwatch.amazonaws.com" }
      Action    = "sns:Publish"
      Resource  = aws_sns_topic.alerts.arn
      Condition = {
        ArnLike = {
          "aws:SourceArn" = "arn:aws:cloudwatch:${var.region}:${data.aws_caller_identity.current.account_id}:alarm:${var.instance_name}-*"
        }
        StringEquals = {
          "aws:SourceAccount" = data.aws_caller_identity.current.account_id
        }
      }
    }]
  })
}

resource "aws_cloudwatch_metric_alarm" "low_memory" {
  alarm_name          = "${var.instance_name}-low-memory"
  alarm_description   = "Available memory below 100 MiB."
  namespace           = "HackOHIO/Lightsail"
  metric_name         = "mem_available"
  statistic           = "Minimum"
  period              = 300
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  threshold           = 104857600
  comparison_operator = "LessThanThreshold"
  unit                = "Bytes"
  dimensions          = { host = var.instance_name }
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  depends_on          = [aws_sns_topic_policy.alerts]
}

resource "aws_cloudwatch_metric_alarm" "high_disk" {
  alarm_name          = "${var.instance_name}-high-root-disk"
  alarm_description   = "Root filesystem usage above 85 percent."
  namespace           = "HackOHIO/Lightsail"
  metric_name         = "disk_used_percent"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  threshold           = 85
  comparison_operator = "GreaterThanThreshold"
  unit                = "Percent"
  dimensions          = { host = var.instance_name }
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  depends_on          = [aws_sns_topic_policy.alerts]
}

resource "awscc_lightsail_alarm" "high_cpu" {
  alarm_name              = "${var.instance_name}-high-cpu"
  comparison_operator     = "GreaterThanThreshold"
  contact_protocols       = ["Email"]
  datapoints_to_alarm     = 2
  evaluation_periods      = 3
  metric_name             = "CPUUtilization"
  monitored_resource_name = aws_lightsail_instance.bot.name
  notification_enabled    = true
  notification_triggers   = ["ALARM"]
  threshold               = 80
}

resource "awscc_lightsail_alarm" "low_burst_capacity" {
  alarm_name              = "${var.instance_name}-low-burst-capacity"
  comparison_operator     = "LessThanThreshold"
  contact_protocols       = ["Email"]
  datapoints_to_alarm     = 2
  evaluation_periods      = 3
  metric_name             = "BurstCapacityPercentage"
  monitored_resource_name = aws_lightsail_instance.bot.name
  notification_enabled    = true
  notification_triggers   = ["ALARM"]
  threshold               = 20
}

resource "awscc_lightsail_alarm" "status_check_failed" {
  alarm_name              = "${var.instance_name}-status-check-failed"
  comparison_operator     = "GreaterThanThreshold"
  contact_protocols       = ["Email"]
  datapoints_to_alarm     = 1
  evaluation_periods      = 1
  metric_name             = "StatusCheckFailed"
  monitored_resource_name = aws_lightsail_instance.bot.name
  notification_enabled    = true
  notification_triggers   = ["ALARM"]
  threshold               = 0
}
