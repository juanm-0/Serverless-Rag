output "invoke_url" {
  value = aws_api_gateway_stage.prod.invoke_url
}

output "api_key_id" {
  value = aws_api_gateway_api_key.key.id
}

output "ci_role_arn" {
  value = aws_iam_role.ci.arn
}

output "index_bucket" {
  value = aws_s3_bucket.index.bucket
}

output "chunks_table" {
  value = aws_dynamodb_table.chunks.name
}
