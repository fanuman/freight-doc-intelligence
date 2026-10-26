# Two roles, two different jobs. Neither involves an access key: AWS hands the running task short-lived
# credentials automatically.
#
#   execution role   used by ECS itself, BEFORE our code starts: pull the images, write logs, fetch the secrets
#   task role        used by OUR code while it runs: read and write the uploads bucket, nothing else

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# ---- execution role ----

resource "aws_iam_role" "execution" {
  name               = "${var.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

# AWS's ready-made policy: pull from ECR and write to CloudWatch Logs.
resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Our addition: read exactly these four secrets, no others.
data "aws_iam_policy_document" "execution_secrets" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.jwt.arn,
      aws_secretsmanager_secret.app_db.arn,
      aws_secretsmanager_secret.openai.arn,
      aws_db_instance.main.master_user_secret[0].secret_arn,
    ]
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  name   = "read-app-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

# ---- task role ----

resource "aws_iam_role" "task" {
  name               = "${var.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

data "aws_iam_policy_document" "task_uploads" {
  statement {
    sid       = "ReadWriteObjects"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.uploads.arn}/*"]
  }

  statement {
    sid       = "ListBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.uploads.arn]
  }
}

resource "aws_iam_role_policy" "task_uploads" {
  name   = "uploads-bucket"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task_uploads.json
}
