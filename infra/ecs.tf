# ECS Fargate: runs our containers without us managing any servers.
#
#   cluster          a named group, nothing more
#   task definition  the recipe: which images, how much CPU/memory, which settings and secrets
#   service          keeps `desired_count` copies of the recipe running and connects them to the load balancer
#
# One task runs two containers side by side (web and api). They share one network address, so the web container
# reaches the API at 127.0.0.1:8000, exactly the API_URL baked into the web image at build time.

resource "aws_ecs_cluster" "main" {
  name = var.name
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${var.name}"
  retention_in_days = 7
}

locals {
  # Plain settings (not secret). The names match the Settings class in config.py.
  api_environment = [
    { name = "POSTGRES_USER", value = aws_db_instance.main.username },
    { name = "POSTGRES_DB", value = aws_db_instance.main.db_name },
    { name = "APP_DB_USER", value = "freight_intel_app" },
    { name = "DB_HOST", value = aws_db_instance.main.address },
    { name = "DB_PORT", value = "5432" },
    { name = "STORAGE_BACKEND", value = "s3" },
    { name = "S3_BUCKET", value = aws_s3_bucket.uploads.bucket },
    { name = "AWS_REGION", value = var.region },
    { name = "EXTRACTION_MODEL", value = var.extraction_model },
  ]

  # Secret settings: ECS fetches each one and hands it to the container as an environment variable.
  # The ":password::" suffix picks the "password" field out of the JSON that RDS stores.
  api_secrets_common = [
    { name = "POSTGRES_PASSWORD", valueFrom = "${aws_db_instance.main.master_user_secret[0].secret_arn}:password::" },
    { name = "APP_DB_PASSWORD", valueFrom = aws_secretsmanager_secret.app_db.arn },
    { name = "JWT_SECRET", valueFrom = aws_secretsmanager_secret.jwt.arn },
  ]

  api_secrets = concat(local.api_secrets_common, [
    { name = "OPENAI_API_KEY", valueFrom = aws_secretsmanager_secret.openai.arn },
  ])

  log_options = {
    "awslogs-group"  = aws_cloudwatch_log_group.app.name
    "awslogs-region" = var.region
  }
}

# ---- the app: web + api in one task ----

resource "aws_ecs_task_definition" "app" {
  family                   = "${var.name}-app"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    cpu_architecture        = var.cpu_architecture
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([
    {
      name         = "api"
      image        = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
      essential    = true
      portMappings = [{ containerPort = 8000, protocol = "tcp" }]
      environment  = local.api_environment
      secrets      = local.api_secrets
      healthCheck = {
        command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')\""]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 20
      }
      logConfiguration = {
        logDriver = "awslogs"
        options   = merge(local.log_options, { "awslogs-stream-prefix" = "api" })
      }
    },
    {
      name         = "web"
      image        = "${aws_ecr_repository.web.repository_url}:${var.image_tag}"
      essential    = true
      portMappings = [{ containerPort = 3000, protocol = "tcp" }]
      dependsOn    = [{ containerName = "api", condition = "HEALTHY" }]
      healthCheck = {
        command     = ["CMD-SHELL", "wget -q -O /dev/null http://127.0.0.1:3000/login || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 20
      }
      logConfiguration = {
        logDriver = "awslogs"
        options   = merge(local.log_options, { "awslogs-stream-prefix" = "web" })
      }
    },
  ])
}

# ---- a one-off job: prepare the empty database ----
# Same API image, different command. Run it by hand once after the first apply (see outputs.tf).

resource "aws_ecs_task_definition" "bootstrap" {
  family                   = "${var.name}-bootstrap"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    cpu_architecture        = var.cpu_architecture
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([
    {
      name        = "bootstrap"
      image       = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
      essential   = true
      command     = ["python", "-m", "freight_intel.bootstrap"]
      environment = local.api_environment
      secrets     = local.api_secrets_common
      logConfiguration = {
        logDriver = "awslogs"
        options   = merge(local.log_options, { "awslogs-stream-prefix" = "bootstrap" })
      }
    },
  ])
}

# ---- the service ----

resource "aws_ecs_service" "app" {
  name            = var.name
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  # Give the containers time to start before the load balancer's health checks can fail the task.
  health_check_grace_period_seconds = 90

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.task.id]
    assign_public_ip = true # no NAT gateway, so this is how the task reaches ECR, Secrets Manager and OpenAI
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.web.arn
    container_name   = "web"
    container_port   = 3000
  }

  depends_on = [aws_lb_listener.http]
}
