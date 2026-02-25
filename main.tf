# configured aws provider with proper credentials
provider "aws" {
  region  = "us-east-1"
  profile =  "default"
}

# Allow your IP (or 0.0.0.0/0 for any) to reach RDS on 5432 for dump/restore and local access.
# Restrict in production: -var="db_allowed_cidr=YOUR_IP/32"
variable "db_allowed_cidr" {
  description = "CIDR allowed to connect to RDS (e.g. your IP/32 for local access)"
  type        = string
  default     = "0.0.0.0/0"
}


# create default vpc if one does not exit
resource "aws_default_vpc" "default_vpc" {

  tags = {
    Name = "default vpc"
  }
}


# use data source to get all avalablility zones in region
data "aws_availability_zones" "available_zones" {}


# create a default subnet in the first az if one does not exit
resource "aws_default_subnet" "subnet_az1" {
  availability_zone = data.aws_availability_zones.available_zones.names[0]
}

# create a default subnet in the second az if one does not exit
resource "aws_default_subnet" "subnet_az2" {
  availability_zone = data.aws_availability_zones.available_zones.names[1]
}

# create security group for the web server
resource "aws_security_group" "webserver_security_group" {
  name        = "webserver security group"
  description = "enable http access on port 80"
  vpc_id      = aws_default_vpc.default_vpc.id

  ingress {
    description      = "http access"
    from_port        = 80
    to_port          = 80
    protocol         = "tcp"
    cidr_blocks      = ["0.0.0.0/0"]
  }

  egress {
    from_port        = 0
    to_port          = 0
    protocol         = -1
    cidr_blocks      = ["0.0.0.0/0"]
  }

  tags   = {
    Name = "webserver security group"
  }
}

# create security group for the database
resource "aws_security_group" "database_security_group" {
  name        = "database security group"
  description = "enable postgres access on port 5432"
  vpc_id      = aws_default_vpc.default_vpc.id

  ingress {
    description      = "postgres from webserver"
    from_port        = 5432
    to_port          = 5432
    protocol         = "tcp"
    security_groups  = [aws_security_group.webserver_security_group.id]
  }

  ingress {
    description      = "postgres from allowed CIDR (local / dump)"
    from_port        = 5432
    to_port          = 5432
    protocol         = "tcp"
    cidr_blocks      = [var.db_allowed_cidr]
  }

  egress {
    from_port        = 0
    to_port          = 0
    protocol         = -1
    cidr_blocks      = ["0.0.0.0/0"]
  }

  tags   = {
    Name = "database security group"
  }
}


# create the subnet group for the rds instance
resource "aws_db_subnet_group" "database_subnet_group" {
  name         = "database-subnets"
  subnet_ids   = [aws_default_subnet.subnet_az1.id, aws_default_subnet.subnet_az2.id]
  description  = "subnets for database instance"

  tags   = {
    Name = "database-subnets"
  }
}


# create the rds instance (PostgreSQL)
resource "aws_db_instance" "db_instance" {
  engine                  = "postgres"
  # engine_version omitted: use RDS default PostgreSQL for this region
  multi_az                = false
  identifier              = "events-db"
  username                = "events"
  password                = "eventspassword"
  instance_class          = "db.t3.micro"
  allocated_storage       = 200
  db_subnet_group_name    = aws_db_subnet_group.database_subnet_group.name
  vpc_security_group_ids  = [aws_security_group.database_security_group.id]
  availability_zone       = data.aws_availability_zones.available_zones.names[0]
  db_name                 = "events"
  skip_final_snapshot     = true
  publicly_accessible     = true # required for DBeaver, QuickSight, and dump from local
}

output "rds_endpoint" {
  description = "RDS instance endpoint (host:port)"
  value       = aws_db_instance.db_instance.endpoint
}

output "rds_address" {
  description = "RDS host (for DATABASE_URL)"
  value       = aws_db_instance.db_instance.address
}

output "database_url" {
  description = "PostgreSQL URL for the app (password in Terraform state)"
  value       = "postgresql://${aws_db_instance.db_instance.username}:${aws_db_instance.db_instance.password}@${aws_db_instance.db_instance.address}:${aws_db_instance.db_instance.port}/${aws_db_instance.db_instance.db_name}"
  sensitive   = true
}