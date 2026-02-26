output "ecr_repository_url" {
  description = "ECR repository URL for pushing container images"
  value       = aws_ecr_repository.app.repository_url
}

output "api_endpoint" {
  description = "Base HTTP API endpoint"
  value       = aws_apigatewayv2_api.http_api.api_endpoint
}

output "mcp_endpoint" {
  description = "MCP endpoint URL"
  value       = "${aws_apigatewayv2_api.http_api.api_endpoint}/mcp"
}

output "lambda_function_name" {
  description = "Lambda function name"
  value       = aws_lambda_function.mcp_server.function_name
}
