terraform {
  required_version = ">= 1.8.0"
  required_providers { aws = { source = "hashicorp/aws", version = "~> 6.0" } }
}
provider "aws" { region = var.region }
variable "region" { type = string, default = "eu-west-2" }
variable "cluster_name" { type = string, default = "aegisllm" }
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.0"
  name = var.cluster_name
  kubernetes_version = "1.33"
  endpoint_public_access = true
  enable_cluster_creator_admin_permissions = true
  eks_managed_node_groups = {
    general = { instance_types = ["t3.large"], min_size=2, max_size=4, desired_size=2 }
  }
}
resource "aws_ecr_repository" "aegisllm" { name = "aegisllm" image_tag_mutability = "IMMUTABLE" }
resource "aws_s3_bucket" "artifacts" { bucket_prefix = "aegisllm-artifacts-" }
