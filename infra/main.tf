terraform {
  required_version = ">= 1.5"
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 5.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.4" }
  }
}

provider "aws" {
  region = var.region
}

# ---------------------------------------------------------------------------
# SQS — FIFO queue + dead-letter queue
# ---------------------------------------------------------------------------

resource "aws_sqs_queue" "dlq" {
  name                        = "${var.name_prefix}-dlq.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
  message_retention_seconds   = 1209600 # 14 days
}

resource "aws_sqs_queue" "main" {
  name                        = "${var.name_prefix}.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
  message_retention_seconds   = 1209600 # 14 days — max outage we can survive
  visibility_timeout_seconds  = 60

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 5
  })
}

# Alarm: oldest message age climbing means the VPS consumer is down / backed up.
resource "aws_cloudwatch_metric_alarm" "backlog_age" {
  alarm_name          = "${var.name_prefix}-backlog-age"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateAgeOfOldestMessage"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = 600 # seconds — alert if anything sits unprocessed > 10 min
  dimensions          = { QueueName = aws_sqs_queue.main.name }
}

# ---------------------------------------------------------------------------
# Lambda — ingress handler
# ---------------------------------------------------------------------------

data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/lambda"
  output_path = "${path.module}/build/ingress.zip"
}

resource "aws_iam_role" "lambda" {
  name = "${var.name_prefix}-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "lambda" {
  name = "${var.name_prefix}-lambda"
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = aws_sqs_queue.main.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

resource "aws_lambda_function" "ingress" {
  function_name    = "${var.name_prefix}-ingress"
  role             = aws_iam_role.lambda.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  timeout          = 10

  environment {
    variables = {
      META_VERIFY_TOKEN   = var.meta_verify_token
      META_WEBHOOK_SECRET = var.meta_webhook_secret
      SQS_QUEUE_URL       = aws_sqs_queue.main.url
    }
  }
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingress.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}

# ---------------------------------------------------------------------------
# API Gateway — HTTP API + routes
# ---------------------------------------------------------------------------

resource "aws_apigatewayv2_api" "http" {
  name          = "${var.name_prefix}-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.ingress.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "verify" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "GET /webhooks/instagram"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "event" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "POST /webhooks/instagram"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true
}

# ---------------------------------------------------------------------------
# ACM certificate + custom domain (DNS-validated, manual records)
# ---------------------------------------------------------------------------

resource "aws_acm_certificate" "webhook" {
  domain_name       = var.webhook_domain
  validation_method = "DNS"
  lifecycle { create_before_destroy = true }
}

# NOTE: the domain's DNS is not assumed to be in Route 53. terraform apply will
# WAIT here until you add the validation CNAME (see the acm_validation output)
# at your DNS provider. Add it, and apply proceeds automatically.
resource "aws_acm_certificate_validation" "webhook" {
  certificate_arn = aws_acm_certificate.webhook.arn
}

resource "aws_apigatewayv2_domain_name" "webhook" {
  domain_name = var.webhook_domain
  domain_name_configuration {
    certificate_arn = aws_acm_certificate_validation.webhook.certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy  = "TLS_1_2"
  }
}

resource "aws_apigatewayv2_api_mapping" "webhook" {
  api_id      = aws_apigatewayv2_api.http.id
  domain_name = aws_apigatewayv2_domain_name.webhook.id
  stage       = aws_apigatewayv2_stage.default.id
}

# ---------------------------------------------------------------------------
# IAM user for the VPS consumer (receive + delete on the queue)
# ---------------------------------------------------------------------------

resource "aws_iam_user" "consumer" {
  name = "${var.name_prefix}-consumer"
}

resource "aws_iam_user_policy" "consumer" {
  name = "${var.name_prefix}-consumer"
  user = aws_iam_user.consumer.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
      Resource = aws_sqs_queue.main.arn
    }]
  })
}

resource "aws_iam_access_key" "consumer" {
  user = aws_iam_user.consumer.name
}
