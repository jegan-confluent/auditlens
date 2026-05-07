# AWS Terraform — security notes

This document captures the egress hardening AuditLens needs but has not yet
applied to live infrastructure. Each section calls out the current state, the
risk, and the Terraform change required.

## ECS task egress is currently `0.0.0.0/0`

**File:** `deploy/terraform/aws/vpc.tf` (`aws_security_group.ecs_tasks`,
`egress { ... cidr_blocks = ["0.0.0.0/0"] }`)

**Risk:** A compromised ECS task can connect to any public host — exfiltrate
audit data, call out to a C2 server, etc. The Confluent Cloud and AWS service
endpoints we actually need are a small subset.

**Recommended replacement:**

```hcl
# Egress to Confluent Cloud Kafka (port 9092) and Schema Registry / IAM (443).
# Replace 0.0.0.0/0 with the Confluent Cloud CIDR list for your region:
#   https://docs.confluent.io/cloud/current/networking/network-overview.html#cidr-ranges
egress {
  description = "Confluent Cloud Kafka brokers"
  from_port   = 9092
  to_port     = 9092
  protocol    = "tcp"
  cidr_blocks = var.confluent_cloud_cidrs   # e.g. ["52.x.x.x/24", "54.x.x.x/24"]
}

egress {
  description = "Confluent Cloud Schema Registry / Admin API (HTTPS)"
  from_port   = 443
  to_port     = 443
  protocol    = "tcp"
  cidr_blocks = var.confluent_cloud_cidrs
}

# AWS Secrets Manager / ECR / CloudWatch via VPC endpoints (no public IP).
egress {
  description     = "AWS service endpoints"
  from_port       = 443
  to_port         = 443
  protocol        = "tcp"
  prefix_list_ids = [
    aws_vpc_endpoint.secretsmanager.prefix_list_id,
    aws_vpc_endpoint.ecr_api.prefix_list_id,
    aws_vpc_endpoint.ecr_dkr.prefix_list_id,
    aws_vpc_endpoint.logs.prefix_list_id,
  ]
}

# RDS Postgres in the same VPC.
egress {
  description     = "RDS Postgres"
  from_port       = 5432
  to_port         = 5432
  protocol        = "tcp"
  security_groups = [aws_security_group.rds.id]
}

# DNS — required so Confluent / AWS hostnames resolve.
egress {
  description = "DNS"
  from_port   = 53
  to_port     = 53
  protocol    = "udp"
  cidr_blocks = [var.vpc_cidr]
}
```

**New variables to add to `variables.tf`:**

```hcl
variable "confluent_cloud_cidrs" {
  description = "Confluent Cloud egress CIDR ranges for the deployment region."
  type        = list(string)
}
```

**New resources to add (e.g. in `vpc.tf` or a new `endpoints.tf`):**

```hcl
resource "aws_vpc_endpoint" "secretsmanager" { ... }
resource "aws_vpc_endpoint" "ecr_api"        { ... }
resource "aws_vpc_endpoint" "ecr_dkr"        { ... }
resource "aws_vpc_endpoint" "logs"           { ... }
```

**Verification after apply:**

```bash
# From inside the ECS task:
curl -m 5 https://example.com    # MUST fail
curl -m 5 https://<your-cluster>.confluent.cloud   # MUST succeed
```

## ALB HTTPS listener is commented out

**File:** `deploy/terraform/aws/alb.tf` (the `aws_lb_listener` block for port
443 is wrapped in `/* ... */`).

**Risk:** Audit data and any future authentication tokens travel over HTTP
between the client and ALB. Anyone on-path can read or modify them.

**Recommended replacement:** uncomment the listener block, point it at an
ACM certificate (managed in `acm.tf` or imported), and add a redirect from
port 80 to 443:

```hcl
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.acm_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}
```

## How to apply these changes safely

1. Add `confluent_cloud_cidrs` to `terraform.tfvars` for your region.
2. Add the VPC endpoint resources in a separate apply *before* tightening
   the egress rule, so existing tasks keep working during the transition.
3. Apply the egress change in a maintenance window with a rollback plan
   (`terraform apply -target=aws_security_group.ecs_tasks`).
4. Verify with the curl checks above.
5. Apply the HTTPS listener and redirect together — never deploy the
   redirect alone, that breaks all clients until the cert is live.

## Out of scope for this document

* Routing logs into a SIEM.
* WAF rules in front of the ALB.
* IAM least-privilege review of the ECS task role (separate audit).
