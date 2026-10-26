output "app_url" {
  description = "Open this in a browser once the service is running."
  value       = "http://${aws_lb.main.dns_name}"
}

output "ecr_api_repository" {
  value = aws_ecr_repository.api.repository_url
}

output "ecr_web_repository" {
  value = aws_ecr_repository.web.repository_url
}

output "ecr_registry" {
  description = "The host part to log Docker in to."
  value       = split("/", aws_ecr_repository.api.repository_url)[0]
}

output "uploads_bucket" {
  value = aws_s3_bucket.uploads.bucket
}

output "openai_secret_name" {
  description = "Put your OpenAI key in this secret from your terminal (see infra/README.md)."
  value       = aws_secretsmanager_secret.openai.name
}

output "run_bootstrap_command" {
  description = "Run once after pushing the images: creates the app role and the tables in the empty database."
  value       = <<-EOT
    aws ecs run-task --region ${var.region} --cluster ${aws_ecs_cluster.main.name} --launch-type FARGATE \
      --task-definition ${aws_ecs_task_definition.bootstrap.family} \
      --network-configuration "awsvpcConfiguration={subnets=[${join(",", data.aws_subnets.default.ids)}],securityGroups=[${aws_security_group.task.id}],assignPublicIp=ENABLED}"
  EOT
}

output "redeploy_command" {
  description = "After pushing new images under the same tag, make the service restart on them."
  value       = "aws ecs update-service --region ${var.region} --cluster ${aws_ecs_cluster.main.name} --service ${aws_ecs_service.app.name} --force-new-deployment"
}

output "logs_command" {
  description = "Follow the logs of all containers."
  value       = "aws logs tail ${aws_cloudwatch_log_group.app.name} --region ${var.region} --follow"
}
