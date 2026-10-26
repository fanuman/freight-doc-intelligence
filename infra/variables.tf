variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "name" {
  description = "Prefix for the names of everything created here."
  type        = string
  default     = "freightlens"
}

variable "desired_count" {
  description = "How many app tasks to run. Keep it 0 until the images are pushed and the database is set up."
  type        = number
  default     = 0
}

variable "image_tag" {
  description = "The tag of the images in the registries (the app tasks start whatever is under this tag)."
  type        = string
  default     = "latest"
}

variable "cpu_architecture" {
  description = "ARM64 if your laptop builds ARM images (Apple Silicon), X86_64 if it builds Intel images."
  type        = string
  default     = "ARM64"

  validation {
    condition     = contains(["ARM64", "X86_64"], var.cpu_architecture)
    error_message = "cpu_architecture must be ARM64 or X86_64."
  }
}

variable "db_instance_class" {
  description = "Size of the database server. The smallest one is plenty for a demo."
  type        = string
  default     = "db.t4g.micro"
}

variable "extraction_model" {
  description = "The model that reads the documents."
  type        = string
  default     = "gpt-4o-mini"
}
