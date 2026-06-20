variable "region" {
  default = "ca-central-1"
}

variable "prefix" {
  default = "serverless-rag"
}

variable "account_id" {
  default = "585242447302"
}

variable "github_repo" {
  default = "juanm-0/Serverless-Rag"
}

variable "ingest_image_tag" {
  description = "Tag of the ingest container image in ECR"
  default     = "latest"
}
