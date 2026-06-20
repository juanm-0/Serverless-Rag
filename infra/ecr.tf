resource "aws_ecr_repository" "ingest" {
  name                 = "${var.prefix}-ingest"
  image_tag_mutability = "MUTABLE"
  force_delete         = true # let `terraform destroy` remove the repo even with images
  image_scanning_configuration {
    scan_on_push = true
  }
}

output "ingest_image_repo" {
  value = aws_ecr_repository.ingest.repository_url
}
