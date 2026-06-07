# --- DNS record #1: ACM validation. Add this FIRST so the cert can issue. ---
# Wrapped in try() so partial/targeted applies (before the ACM branch exists)
# don't fail at output evaluation.
output "acm_validation" {
  description = "CNAME to add at your DNS provider to validate the ACM cert."
  value = try({
    for o in aws_acm_certificate.webhook.domain_validation_options :
    o.domain_name => { name = o.resource_record_name, type = o.resource_record_type, value = o.resource_record_value }
  }, null)
}

# --- DNS record #2: point the webhook subdomain at API Gateway. ---
output "webhook_cname_target" {
  description = "CNAME value for hooks.munimjee.in → API Gateway custom domain."
  value       = try(aws_apigatewayv2_domain_name.webhook.domain_name_configuration[0].target_domain_name, null)
}

output "webhook_url" {
  description = "Set this as the Meta webhook Callback URL."
  value       = "https://${var.webhook_domain}/webhooks/instagram"
}

output "sqs_queue_url" {
  description = "Set as SQS_QUEUE_URL in the VPS .env."
  value       = aws_sqs_queue.main.url
}

output "consumer_access_key_id" {
  description = "AWS_ACCESS_KEY_ID for the VPS sqs_consumer."
  value       = aws_iam_access_key.consumer.id
}

output "consumer_secret_access_key" {
  description = "AWS_SECRET_ACCESS_KEY for the VPS sqs_consumer."
  value       = aws_iam_access_key.consumer.secret
  sensitive   = true
}

output "raw_api_endpoint" {
  description = "Direct API Gateway URL (for testing before DNS/cert is ready)."
  value       = aws_apigatewayv2_api.http.api_endpoint
}
