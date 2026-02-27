# Run busco-events-scraper on EC2 (pull latest from Docker Hub)

Run these on the EC2 instance (SSH in as `ec2-user`).

## 1. Install Docker

```bash
sudo yum update -y
sudo yum install -y docker
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker ec2-user
```

Log out and back in (or run `newgrp docker`) so `docker` runs without `sudo`.

## 2. Set DATABASE_URL

The app needs `postgresql+psycopg://...` (not plain `postgresql://`). From your **local machine** (where Terraform runs):

```bash
terraform output -raw database_url
```

Replace `postgresql://` with `postgresql+psycopg://` in that URL. Example:

- Terraform: `postgresql://events:eventspassword@xxx.rds.amazonaws.com:5432/events`
- Use:       `postgresql+psycopg://events:eventspassword@xxx.rds.amazonaws.com:5432/events`

On the **EC2 instance**, create the env file (use your actual URL):

```bash
sudo mkdir -p /etc/busco-events-scraper
echo 'DATABASE_URL=postgresql+psycopg://events:eventspassword@YOUR_RDS_ADDRESS:5432/events' | sudo tee /etc/busco-events-scraper/env
sudo chmod 600 /etc/busco-events-scraper/env
```

Replace `YOUR_RDS_ADDRESS` with the RDS host (from `terraform output -raw rds_address` on your laptop).

## 3. Install the systemd service

On the **EC2 instance**:

```bash
sudo tee /etc/systemd/system/busco-events-scraper.service << 'EOF'
[Unit]
Description=Busco Events Scraper (Docker)
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
EnvironmentFile=/etc/busco-events-scraper/env
ExecStartPre=-/usr/bin/docker pull busco-events-scraper:latest
ExecStart=/usr/bin/docker run --rm --name busco-events-scraper -e DATABASE_URL="$DATABASE_URL" busco-events-scraper:latest
ExecStop=/usr/bin/docker stop -t 10 busco-events-scraper
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable busco-events-scraper
sudo systemctl start busco-events-scraper
```

## 4. Check status and logs

```bash
sudo systemctl status busco-events-scraper
sudo journalctl -u busco-events-scraper -f
```

## 5. Pull and run “latest” again later

To pull a new image and restart the app:

```bash
sudo systemctl restart busco-events-scraper
```

The service runs the pipeline once per start (your Dockerfile `CMD` is `python -m src.app`). If you want it to run on a schedule (e.g. daily), add a cron or systemd timer that runs `sudo systemctl restart busco-events-scraper`.
