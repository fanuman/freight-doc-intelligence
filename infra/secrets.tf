# Secrets live in AWS Secrets Manager. The containers receive them as environment variables when they start;
# they are never in the image, the code or the task definition text.
#
#   database password   created and rotated by RDS itself (see database.tf), so no human or Terraform file ever sees it
#   JWT secret          generated here (signs the login tokens)
#   app role password   generated here (the database login the API uses)
#   OpenAI key          the secret is created EMPTY here; you put the value in from your terminal (see the README)
#
# Terraform keeps the two generated values in its state file, so the state file is private (it is git-ignored).
# recovery_window_in_days = 0 deletes a secret immediately on destroy, so a later apply can reuse the name.

resource "random_password" "jwt" {
  length  = 64
  special = false
}

resource "random_password" "app_db" {
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "jwt" {
  name                    = "${var.name}/jwt-secret"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "jwt" {
  secret_id     = aws_secretsmanager_secret.jwt.id
  secret_string = random_password.jwt.result
}

resource "aws_secretsmanager_secret" "app_db" {
  name                    = "${var.name}/app-db-password"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "app_db" {
  secret_id     = aws_secretsmanager_secret.app_db.id
  secret_string = random_password.app_db.result
}

resource "aws_secretsmanager_secret" "openai" {
  name                    = "${var.name}/openai-api-key"
  recovery_window_in_days = 0
}
