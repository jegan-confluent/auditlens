################################################################################
# Outputs
################################################################################

# VPC
output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = aws_subnet.private[*].id
}

output "public_subnet_ids" {
  description = "Public subnet IDs"
  value       = aws_subnet.public[*].id
}

# ECR
output "ecr_forwarder_url" {
  description = "ECR repository URL for forwarder"
  value       = aws_ecr_repository.forwarder.repository_url
}

output "ecr_dashboard_url" {
  description = "ECR repository URL for dashboard"
  value       = aws_ecr_repository.dashboard.repository_url
}

# ECS
output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.main.name
}

output "ecs_cluster_arn" {
  description = "ECS cluster ARN"
  value       = aws_ecs_cluster.main.arn
}

output "forwarder_service_name" {
  description = "Forwarder ECS service name"
  value       = aws_ecs_service.forwarder.name
}

output "dashboard_service_name" {
  description = "Dashboard ECS service name"
  value       = aws_ecs_service.dashboard.name
}

# Load Balancer
output "alb_dns_name" {
  description = "ALB DNS name (use this to access the dashboard)"
  value       = aws_lb.main.dns_name
}

output "alb_zone_id" {
  description = "ALB zone ID (for Route53 alias records)"
  value       = aws_lb.main.zone_id
}

output "dashboard_url" {
  description = "Dashboard URL"
  value       = "http://${aws_lb.main.dns_name}"
}

# Monitoring
output "cloudwatch_dashboard_url" {
  description = "CloudWatch dashboard URL"
  value       = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${aws_cloudwatch_dashboard.main.dashboard_name}"
}

output "forwarder_log_group" {
  description = "Forwarder CloudWatch log group"
  value       = aws_cloudwatch_log_group.forwarder.name
}

output "dashboard_log_group" {
  description = "Dashboard CloudWatch log group"
  value       = aws_cloudwatch_log_group.dashboard.name
}

# Secrets
output "kafka_source_secret_arn" {
  description = "ARN of Kafka source credentials secret"
  value       = aws_secretsmanager_secret.kafka_source.arn
  sensitive   = true
}

output "kafka_dest_secret_arn" {
  description = "ARN of Kafka destination credentials secret"
  value       = aws_secretsmanager_secret.kafka_dest.arn
  sensitive   = true
}

# Quick Commands
output "push_commands" {
  description = "Commands to push images to ECR"
  value       = <<-EOT
    # Login to ECR
    aws ecr get-login-password --region ${var.aws_region} | docker login --username AWS --password-stdin ${aws_ecr_repository.forwarder.repository_url}

    # Push forwarder
    docker tag audit-forwarder:${var.forwarder_image_tag} ${aws_ecr_repository.forwarder.repository_url}:${var.forwarder_image_tag}
    docker push ${aws_ecr_repository.forwarder.repository_url}:${var.forwarder_image_tag}

    # Push dashboard
    docker tag audit-dashboard:${var.dashboard_image_tag} ${aws_ecr_repository.dashboard.repository_url}:${var.dashboard_image_tag}
    docker push ${aws_ecr_repository.dashboard.repository_url}:${var.dashboard_image_tag}
  EOT
}
