# Container registries (where the images are kept) and the bucket for uploaded documents.

resource "aws_ecr_repository" "api" {
  name                 = "${var.name}-api"
  image_tag_mutability = "MUTABLE"
  force_delete         = true # lets `terraform destroy` remove the repository even though it holds images

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "web" {
  name                 = "${var.name}-web"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Uploaded quotes and invoices. The bucket name must be unique worldwide, so it includes the account and region.
resource "aws_s3_bucket" "uploads" {
  bucket        = "${var.name}-uploads-${data.aws_caller_identity.current.account_id}-${var.region}"
  force_destroy = true # demo only: `terraform destroy` empties the bucket first
}

resource "aws_s3_bucket_public_access_block" "uploads" {
  bucket                  = aws_s3_bucket.uploads.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
