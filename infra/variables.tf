variable "region" {
  description = "AWS region — keep next to the S3 bucket (ap-south-1 = Mumbai)."
  type        = string
  default     = "ap-south-1"
}

variable "webhook_domain" {
  description = "Custom domain Meta delivers webhooks to."
  type        = string
  default     = "hooks.munimjee.in"
}

variable "meta_verify_token" {
  description = "Challenge token for Meta's GET verification handshake (== app's META_VERIFY_TOKEN)."
  type        = string
  sensitive   = true
}

variable "meta_webhook_secret" {
  description = "HMAC-SHA256 key for POST signature verification (== app's META_WEBHOOK_SECRET)."
  type        = string
  sensitive   = true
}

variable "name_prefix" {
  description = "Prefix for resource names."
  type        = string
  default     = "sellerbot-webhook"
}
