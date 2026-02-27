#!/bin/bash
# Install Docker and run busco-events-scraper from Docker Hub (runs on first boot only).
# Log to /var/log/busco-user-data.log for debugging.
exec > >(tee -a /var/log/busco-user-data.log) 2>&1
set -x

yum update -y
yum install -y docker
systemctl start docker
systemctl enable docker
usermod -aG docker ec2-user

mkdir -p /etc/busco-events-scraper
echo 'DATABASE_URL=${database_url_psycopg}' > /etc/busco-events-scraper/env
chmod 600 /etc/busco-events-scraper/env

cat > /etc/systemd/system/busco-events-scraper.service << 'SVC'
[Unit]
Description=Busco Events Scraper (Docker)
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
EnvironmentFile=/etc/busco-events-scraper/env
ExecStartPre=-/usr/bin/docker pull ${docker_image}
ExecStart=/usr/bin/docker run --rm --name busco-events-scraper -e DATABASE_URL=$$DATABASE_URL ${docker_image}
ExecStop=/usr/bin/docker stop -t 10 busco-events-scraper
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
SVC

systemctl daemon-reload
systemctl enable busco-events-scraper
systemctl start busco-events-scraper
echo "busco-events-scraper user_data finished at $(date)" >> /var/log/busco-user-data.log
