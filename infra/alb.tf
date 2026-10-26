# The load balancer: the one public door. It listens on port 80 and forwards to the web container (port 3000).
# The web container forwards /api/* to the API container on the same task, so the API is never exposed directly.
#
# Plain HTTP on purpose for this demo (no domain name, no certificate). Real traffic would use HTTPS (port 443
# with a certificate from AWS Certificate Manager) and port 80 would only redirect to it.

resource "aws_lb" "main" {
  name               = var.name
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = data.aws_subnets.default.ids
}

resource "aws_lb_target_group" "web" {
  name        = "${var.name}-web"
  port        = 3000
  protocol    = "HTTP"
  vpc_id      = data.aws_vpc.default.id
  target_type = "ip" # Fargate tasks are registered by their own network address

  deregistration_delay = 10 # seconds; the default of 300 makes every stop and destroy wait five minutes

  # The balancer asks this page every 30 seconds. A task that stops answering is replaced.
  health_check {
    path                = "/login"
    matcher             = "200-399"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}
