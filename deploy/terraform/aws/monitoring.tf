################################################################################
# CloudWatch Monitoring
################################################################################

# Log Groups
resource "aws_cloudwatch_log_group" "forwarder" {
  name              = "/ecs/${var.project_name}-forwarder"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "${var.project_name}-forwarder-logs"
  }
}

resource "aws_cloudwatch_log_group" "dashboard" {
  name              = "/ecs/${var.project_name}-dashboard"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "${var.project_name}-dashboard-logs"
  }
}

################################################################################
# CloudWatch Alarms
################################################################################

# Forwarder CPU High
resource "aws_cloudwatch_metric_alarm" "forwarder_cpu_high" {
  alarm_name          = "${var.project_name}-forwarder-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "Forwarder CPU utilization is too high"

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.forwarder.name
  }

  tags = {
    Name = "${var.project_name}-forwarder-cpu-alarm"
  }
}

# Forwarder Memory High
resource "aws_cloudwatch_metric_alarm" "forwarder_memory_high" {
  alarm_name          = "${var.project_name}-forwarder-memory-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "MemoryUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "Forwarder memory utilization is too high"

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.forwarder.name
  }

  tags = {
    Name = "${var.project_name}-forwarder-memory-alarm"
  }
}

# Forwarder Task Count
resource "aws_cloudwatch_metric_alarm" "forwarder_running_tasks" {
  alarm_name          = "${var.project_name}-forwarder-no-tasks"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "RunningTaskCount"
  namespace           = "ECS/ContainerInsights"
  period              = 60
  statistic           = "Average"
  threshold           = 1
  alarm_description   = "No forwarder tasks are running"

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.forwarder.name
  }

  tags = {
    Name = "${var.project_name}-forwarder-tasks-alarm"
  }
}

# Dashboard Healthy Hosts
resource "aws_cloudwatch_metric_alarm" "dashboard_healthy_hosts" {
  alarm_name          = "${var.project_name}-dashboard-unhealthy"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Average"
  threshold           = 1
  alarm_description   = "No healthy dashboard instances"

  dimensions = {
    TargetGroup  = aws_lb_target_group.dashboard.arn_suffix
    LoadBalancer = aws_lb.main.arn_suffix
  }

  tags = {
    Name = "${var.project_name}-dashboard-health-alarm"
  }
}

# ALB 5xx Errors
resource "aws_cloudwatch_metric_alarm" "alb_5xx_errors" {
  alarm_name          = "${var.project_name}-alb-5xx-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 10
  alarm_description   = "High number of 5xx errors from dashboard"
  treat_missing_data  = "notBreaching"

  dimensions = {
    TargetGroup  = aws_lb_target_group.dashboard.arn_suffix
    LoadBalancer = aws_lb.main.arn_suffix
  }

  tags = {
    Name = "${var.project_name}-alb-5xx-alarm"
  }
}

################################################################################
# CloudWatch Dashboard
################################################################################

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${var.project_name}-dashboard"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Forwarder CPU & Memory"
          region = var.aws_region
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ServiceName", aws_ecs_service.forwarder.name, "ClusterName", aws_ecs_cluster.main.name],
            ["AWS/ECS", "MemoryUtilization", "ServiceName", aws_ecs_service.forwarder.name, "ClusterName", aws_ecs_cluster.main.name]
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Dashboard CPU & Memory"
          region = var.aws_region
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ServiceName", aws_ecs_service.dashboard.name, "ClusterName", aws_ecs_cluster.main.name],
            ["AWS/ECS", "MemoryUtilization", "ServiceName", aws_ecs_service.dashboard.name, "ClusterName", aws_ecs_cluster.main.name]
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "ALB Request Count"
          region = var.aws_region
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", aws_lb.main.arn_suffix]
          ]
          stat   = "Sum"
          period = 60
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "ALB Response Time"
          region = var.aws_region
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", aws_lb.main.arn_suffix]
          ]
          stat   = "Average"
          period = 60
        }
      },
      {
        type   = "log"
        x      = 0
        y      = 12
        width  = 24
        height = 6
        properties = {
          title  = "Forwarder Logs"
          region = var.aws_region
          query  = "SOURCE '${aws_cloudwatch_log_group.forwarder.name}' | fields @timestamp, @message | sort @timestamp desc | limit 100"
        }
      }
    ]
  })
}
