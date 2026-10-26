# Network: the account's default VPC, and three firewalls (security groups) that chain together.
#
#   internet --80--> [load balancer] --3000--> [app task] --5432--> [database]
#
# Each group accepts traffic only from the one before it. We use the default VPC and public subnets on purpose:
# a private network would need a NAT gateway (about $32 a month on its own). The task has a public IP, but
# nothing except the load balancer is allowed to talk to it. A production setup would use private subnets.

data "aws_caller_identity" "current" {}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

resource "aws_security_group" "alb" {
  name        = "${var.name}-alb"
  description = "Load balancer: HTTP from the internet"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP from anywhere"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "task" {
  name        = "${var.name}-task"
  description = "App task: only the load balancer may connect"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "The web container, from the load balancer only"
    from_port       = 3000
    to_port         = 3000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  # The task must reach out: the image registry, S3, Secrets Manager, the database and the OpenAI API.
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "db" {
  name        = "${var.name}-db"
  description = "Database: only the app task may connect"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "Postgres, from the app task only"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.task.id]
  }
}
