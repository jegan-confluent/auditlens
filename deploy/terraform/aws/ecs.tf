################################################################################
# ECS Cluster and Services
################################################################################

# ECS Cluster
resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-cluster"

  setting {
    name  = "containerInsights"
    value = var.enable_container_insights ? "enabled" : "disabled"
  }

  tags = {
    Name = "${var.project_name}-cluster"
  }
}

# Cluster Capacity Providers
resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name = aws_ecs_cluster.main.name

  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = var.use_fargate_spot ? "FARGATE_SPOT" : "FARGATE"
    weight            = 1
  }
}

################################################################################
# Forwarder Task Definition
################################################################################

resource "aws_ecs_task_definition" "forwarder" {
  family                   = "${var.project_name}-forwarder"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.forwarder_cpu
  memory                   = var.forwarder_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "forwarder"
      image     = "${aws_ecr_repository.forwarder.repository_url}:${var.forwarder_image_tag}"
      essential = true

      portMappings = [
        {
          containerPort = 8003
          protocol      = "tcp"
        }
      ]

      environment = [
        { name = "AUDIT_TOPIC", value = var.audit_topic },
        { name = "GROUP_ID", value = var.consumer_group_id },
        { name = "ENABLE_MULTI_TOPIC_ROUTING", value = tostring(var.enable_multi_topic_routing) },
        { name = "DROP_LOW_EVENTS", value = tostring(var.drop_low_events) },
        { name = "ENABLE_DLQ", value = tostring(var.enable_dlq) },
        { name = "METRICS_PORT", value = "8003" },
        { name = "OFFSET_FILE", value = "/tmp/offsets.json" }
      ]

      secrets = [
        {
          name      = "AUDIT_BOOTSTRAP"
          valueFrom = "${aws_secretsmanager_secret.kafka_source.arn}:AUDIT_BOOTSTRAP::"
        },
        {
          name      = "AUDIT_API_KEY"
          valueFrom = "${aws_secretsmanager_secret.kafka_source.arn}:AUDIT_API_KEY::"
        },
        {
          name      = "AUDIT_API_SECRET"
          valueFrom = "${aws_secretsmanager_secret.kafka_source.arn}:AUDIT_API_SECRET::"
        },
        {
          name      = "DEST_BOOTSTRAP"
          valueFrom = "${aws_secretsmanager_secret.kafka_dest.arn}:DEST_BOOTSTRAP::"
        },
        {
          name      = "DEST_API_KEY"
          valueFrom = "${aws_secretsmanager_secret.kafka_dest.arn}:DEST_API_KEY::"
        },
        {
          name      = "DEST_API_SECRET"
          valueFrom = "${aws_secretsmanager_secret.kafka_dest.arn}:DEST_API_SECRET::"
        }
      ]

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8003/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.forwarder.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "forwarder"
        }
      }
    }
  ])

  tags = {
    Name = "${var.project_name}-forwarder"
  }
}

################################################################################
# Dashboard Task Definition
################################################################################

resource "aws_ecs_task_definition" "dashboard" {
  family                   = "${var.project_name}-dashboard"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.dashboard_cpu
  memory                   = var.dashboard_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "dashboard"
      image     = "${aws_ecr_repository.dashboard.repository_url}:${var.dashboard_image_tag}"
      essential = true

      portMappings = [
        {
          containerPort = 8501
          protocol      = "tcp"
        }
      ]

      secrets = [
        {
          name      = "DEST_BOOTSTRAP"
          valueFrom = "${aws_secretsmanager_secret.kafka_dest.arn}:DEST_BOOTSTRAP::"
        },
        {
          name      = "DEST_API_KEY"
          valueFrom = "${aws_secretsmanager_secret.kafka_dest.arn}:DEST_API_KEY::"
        },
        {
          name      = "DEST_API_SECRET"
          valueFrom = "${aws_secretsmanager_secret.kafka_dest.arn}:DEST_API_SECRET::"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.dashboard.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "dashboard"
        }
      }
    }
  ])

  tags = {
    Name = "${var.project_name}-dashboard"
  }
}

################################################################################
# ECS Services
################################################################################

# Forwarder Service
resource "aws_ecs_service" "forwarder" {
  name            = "${var.project_name}-forwarder"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.forwarder.arn
  desired_count   = var.forwarder_desired_count
  launch_type     = var.use_fargate_spot ? null : "FARGATE"

  dynamic "capacity_provider_strategy" {
    for_each = var.use_fargate_spot ? [1] : []
    content {
      capacity_provider = "FARGATE_SPOT"
      weight            = 1
    }
  }

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = {
    Name = "${var.project_name}-forwarder-service"
  }
}

# Dashboard Service
resource "aws_ecs_service" "dashboard" {
  name            = "${var.project_name}-dashboard"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.dashboard.arn
  desired_count   = var.dashboard_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.dashboard.arn
    container_name   = "dashboard"
    container_port   = 8501
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener.http]

  tags = {
    Name = "${var.project_name}-dashboard-service"
  }
}
