################################################################################
# TradeLab — AWS App Runner + S3 deployment (Free Tier conscious)
#
# Services used:
#   - AWS App Runner   : FastAPI backend (auto-scale to 0 when idle)
#   - Amazon S3        : Static frontend hosting
#   - Amazon CloudFront: HTTPS CDN for the frontend + API reverse proxy
#   - Amazon ECR       : Docker image registry (500 MB free tier)
#   - AWS Secrets Manager : Runtime secrets (< 100 requests/month stay free)
#
# Not used (cost reasons):
#   - ECS/Fargate, EKS, ALB, NAT Gateway, RDS (all incur costs on free tier)
#
# NOTE: App Runner charges ~$5/month minimum even when idle.
# For zero-cost development, prefer the "stop service" option via Console.
################################################################################

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

variable "aws_region"         { default = "ap-south-1" }   # Mumbai — lowest latency for India
variable "app_name"           { default = "tradelab" }
variable "ecr_image_uri"      { description = "Full ECR image URI, e.g. 123456789.dkr.ecr.ap-south-1.amazonaws.com/tradelab:latest" }
variable "gemini_api_key_arn" { description = "Secrets Manager ARN for GEMINI_API_KEY" }
variable "groq_api_key_arn"   { description = "Secrets Manager ARN for GROQ_API_KEY" }
variable "allowed_origin"     { default = "" }   # CloudFront distribution URL set after first deploy

provider "aws" {
  region = var.aws_region
}

# ── ECR repository ────────────────────────────────────────────────────────────
resource "aws_ecr_repository" "tradelab" {
  name                 = var.app_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration { scan_on_push = true }

  # Free tier: 500 MB storage included; lifecycle policy avoids accumulation.
  lifecycle_policy {
    policy = jsonencode({
      rules = [{
        rulePriority = 1
        description  = "Keep last 3 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 3
        }
        action = { type = "expire" }
      }]
    })
  }
}

# ── IAM role for App Runner to pull from ECR ─────────────────────────────────
resource "aws_iam_role" "apprunner_ecr" {
  name = "${var.app_name}-apprunner-ecr-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "build.apprunner.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "apprunner_ecr_attach" {
  role       = aws_iam_role.apprunner_ecr.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"
}

# ── IAM role for the App Runner instance (runtime) ───────────────────────────
resource "aws_iam_role" "apprunner_instance" {
  name = "${var.app_name}-apprunner-instance-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "tasks.apprunner.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Allow the running container to read its own secrets
resource "aws_iam_role_policy" "secrets_read" {
  name = "secrets-read"
  role = aws_iam_role.apprunner_instance.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue"]
      Resource = [
        var.gemini_api_key_arn,
        var.groq_api_key_arn,
      ]
    }]
  })
}

# ── App Runner service ────────────────────────────────────────────────────────
resource "aws_apprunner_service" "tradelab" {
  service_name = var.app_name

  source_configuration {
    authentication_configuration {
      access_role_arn = aws_iam_role.apprunner_ecr.arn
    }
    image_repository {
      image_identifier      = var.ecr_image_uri
      image_repository_type = "ECR"
      image_configuration {
        port = "8000"
        runtime_environment_variables = {
          APP_ENV        = "production"
          DEBUG          = "false"
          # Data directories inside the container (ephemeral — see DEPLOYMENT.md)
          PARQUET_STORAGE_DIR   = "/app/data/ohlcv"
          METADATA_DATABASE_URL = "sqlite:////app/data/metadata.db"
          DATABASE_URL          = "sqlite:////app/data/metadata.db"
          LOG_DIRECTORY         = "/app/data/logs"
          # AI keys injected at runtime via secrets (not env vars here)
        }
        runtime_environment_secrets = {
          GEMINI_API_KEY = var.gemini_api_key_arn
          GROQ_API_KEY   = var.groq_api_key_arn
        }
      }
    }
    auto_deployments_enabled = false   # manual deploys only
  }

  instance_configuration {
    cpu    = "0.25 vCPU"   # minimum; scale up if Monte Carlo is slow
    memory = "0.5 GB"
  }

  # Health check on /health endpoint
  health_check_configuration {
    protocol            = "HTTP"
    path                = "/health"
    interval            = 20
    timeout             = 5
    healthy_threshold   = 1
    unhealthy_threshold = 5
  }

  instance_role_arn = aws_iam_role.apprunner_instance.arn

  tags = { Project = "TradeLab" }
}

# ── S3 bucket for static frontend ────────────────────────────────────────────
resource "aws_s3_bucket" "frontend" {
  bucket = "${var.app_name}-frontend-${data.aws_caller_identity.current.account_id}"
  tags   = { Project = "TradeLab" }
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  versioning_configuration { status = "Enabled" }
}

# ── CloudFront OAC for S3 ─────────────────────────────────────────────────────
resource "aws_cloudfront_origin_access_control" "frontend_oac" {
  name                              = "${var.app_name}-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowCloudFront"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.frontend.arn}/*"
      Condition = {
        StringEquals = {
          "AWS:SourceArn" = aws_cloudfront_distribution.tradelab.arn
        }
      }
    }]
  })
}

# ── CloudFront distribution (frontend + API proxy) ────────────────────────────
resource "aws_cloudfront_distribution" "tradelab" {
  enabled             = true
  default_root_object = "index.html"
  comment             = "TradeLab SPA + API"

  # Origin 1: S3 frontend
  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = "s3-frontend"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend_oac.id
  }

  # Origin 2: App Runner backend
  origin {
    domain_name = replace(aws_apprunner_service.tradelab.service_url, "https://", "")
    origin_id   = "apprunner-backend"
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # Default behaviour → S3 frontend
  default_cache_behavior {
    target_origin_id       = "s3-frontend"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    cache_policy_id        = "658327ea-f89d-4fab-a63d-7e88639e58f6"  # CachingOptimized
  }

  # /api/* and /ws/* → App Runner
  ordered_cache_behavior {
    path_pattern           = "/api/*"
    target_origin_id       = "apprunner-backend"
    viewer_protocol_policy = "https-only"
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    forwarded_values {
      query_string = true
      headers      = ["Origin", "Accept", "Content-Type", "Authorization"]
      cookies { forward = "all" }
    }
    min_ttl     = 0
    default_ttl = 0
    max_ttl     = 0
    compress    = true
  }

  # SPA fallback — all unknown paths return index.html
  custom_error_response {
    error_code         = 403
    response_code      = 200
    response_page_path = "/index.html"
  }
  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate { cloudfront_default_certificate = true }

  tags = { Project = "TradeLab" }
}

# ── Outputs ───────────────────────────────────────────────────────────────────
output "app_runner_url"      { value = aws_apprunner_service.tradelab.service_url }
output "cloudfront_url"      { value = "https://${aws_cloudfront_distribution.tradelab.domain_name}" }
output "ecr_repository_url"  { value = aws_ecr_repository.tradelab.repository_url }
output "s3_bucket_name"      { value = aws_s3_bucket.frontend.bucket }
