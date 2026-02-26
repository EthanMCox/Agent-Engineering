variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-west-2"
}

variable "project_name" {
  description = "Base name for created resources"
  type        = string
  default     = "agent-engineer-opinions-mcp"
}

variable "image_uri" {
  description = "Full ECR image URI for Lambda (example: 123456789012.dkr.ecr.us-west-2.amazonaws.com/repo:latest). Set for deploy/update applies."
  type        = string
  default     = ""
}

variable "lambda_architecture" {
  description = "Lambda architecture for the container image"
  type        = string
  default     = "x86_64"

  validation {
    condition     = contains(["x86_64", "arm64"], var.lambda_architecture)
    error_message = "lambda_architecture must be one of: x86_64, arm64."
  }
}

variable "existing_lambda_role_arn" {
  description = "Optional existing Lambda execution role ARN. If set, Terraform will not create/manage IAM role policies."
  type        = string
  default     = ""
}

variable "stage_name" {
  description = "API Gateway stage name"
  type        = string
  default     = "$default"
}
