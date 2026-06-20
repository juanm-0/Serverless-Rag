# SSM SecureString parameters are set out-of-band (CLI); Terraform only
# references them for IAM grants and never sees the values.
data "aws_ssm_parameter" "groq_key" {
  name = "/${var.prefix}/groq-api-key"
}

data "aws_ssm_parameter" "gemini_key" {
  name = "/${var.prefix}/gemini-api-key"
}
