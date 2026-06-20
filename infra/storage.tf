# Vector index blobs (vectors.npy + chunk_ids.json)
resource "aws_s3_bucket" "index" {
  bucket = "${var.prefix}-index-${var.account_id}"
}

resource "aws_s3_bucket_public_access_block" "index" {
  bucket                  = aws_s3_bucket.index.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Chunk text/metadata, keyed by chunk id
resource "aws_dynamodb_table" "chunks" {
  name         = "${var.prefix}-chunks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"
  attribute {
    name = "id"
    type = "S"
  }
}

# One record per eval run
resource "aws_dynamodb_table" "eval_results" {
  name         = "${var.prefix}-eval-results"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "run_id"
  attribute {
    name = "run_id"
    type = "S"
  }
}
