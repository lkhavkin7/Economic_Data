# The NAT gateway: lets the private subnets start connections to the internet (the
# Lambda calling FRED) without the internet being able to start connections to them.
# It lives in the public subnet and sends traffic out through the internet gateway.
#
# This file is where billing starts: the gateway costs about $0.045 per hour plus
# $0.045 per GB it processes, and its public IP address about $0.005 per hour.
# "terraform destroy" stops all of it.

# The fixed public IP address the gateway uses. Replies from FRED come back to it.
resource "aws_eip" "nat" {
  domain = "vpc"

  tags = { Name = "${var.project}-nat" }
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public.id

  # The gateway needs the internet gateway to exist first, and nothing in this
  # block refers to it, so the order is stated here.
  depends_on = [aws_internet_gateway.main]

  tags = { Name = var.project }
}

# Gives the private route table its way out: everything not inside the VPC goes to the
# NAT gateway. This is the line that was missing from the private route table in network.tf.
resource "aws_route" "private_internet" {
  route_table_id         = aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.main.id
}