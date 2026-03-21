#!/bin/bash
# webapp/deploy_ec2.sh
#
# One-time EC2 setup script.
# Run this on a fresh Ubuntu 22.04 EC2 t2.micro (free tier) instance.
#
# Usage:
#   chmod +x deploy_ec2.sh
#   ./deploy_ec2.sh

set -e
echo "=== Agentic Trading Dashboard — EC2 Deploy ==="

# ── System packages ───────────────────────────────
echo "Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y python3-pip python3-venv nginx nodejs npm git

# ── Clone repo ────────────────────────────────────
echo "Cloning repository..."
cd /home/ubuntu
git clone https://github.com/YOUR_USERNAME/agentic-trading.git app
cd app

# ── Backend setup ─────────────────────────────────
echo "Setting up FastAPI backend..."
python3 -m venv venv
source venv/bin/activate
pip install -r webapp/backend/requirements.txt

# Copy .env
cp .env.example .env
echo "⚠️  Edit /home/ubuntu/app/.env with your actual AWS credentials before starting"

# ── Frontend build ────────────────────────────────
echo "Building React frontend..."
cd webapp/frontend
npm install
VITE_API_URL=http://YOUR_EC2_PUBLIC_IP/api npm run build
cd /home/ubuntu/app

# ── Nginx config ──────────────────────────────────
echo "Configuring Nginx..."
sudo tee /etc/nginx/sites-available/trading << 'EOF'
server {
    listen 80;
    server_name _;

    # Serve React build
    root /home/ubuntu/app/webapp/frontend/dist;
    index index.html;

    # React Router — serve index.html for all routes
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Proxy /api to FastAPI
    location /api {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_read_timeout 60s;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/trading /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx

# ── Systemd service for FastAPI ───────────────────
echo "Creating systemd service..."
sudo tee /etc/systemd/system/trading-api.service << EOF
[Unit]
Description=Agentic Trading FastAPI
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/app
Environment="PATH=/home/ubuntu/app/venv/bin"
ExecStart=/home/ubuntu/app/venv/bin/uvicorn webapp.backend.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable trading-api
sudo systemctl start  trading-api

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  Deployment complete!                            ║"
echo "║                                                  ║"
echo "║  1. Edit /home/ubuntu/app/.env with AWS keys     ║"
echo "║  2. sudo systemctl restart trading-api           ║"
echo "║  3. Visit http://YOUR_EC2_PUBLIC_IP              ║"
echo "╚══════════════════════════════════════════════════╝"
