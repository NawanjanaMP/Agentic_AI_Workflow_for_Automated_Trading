#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# deploy/scripts/ec2_setup.sh
#
# One-time EC2 instance bootstrap for Agentic AI Trading System.
# Run as ubuntu user on a fresh Amazon Linux 2023 or Ubuntu 22.04 AMI.
#
# Usage:
#   chmod +x ec2_setup.sh
#   ./ec2_setup.sh
# ─────────────────────────────────────────────────────────────────
set -euo pipefail

echo "======================================================"
echo " Agentic AI Trading — EC2 Bootstrap"
echo "======================================================"

# ── 1. System update ──────────────────────────────────────────────
echo "[1/8] Updating system packages..."
sudo apt-get update -y
sudo apt-get upgrade -y

# ── 2. Install Docker ─────────────────────────────────────────────
echo "[2/8] Installing Docker..."
sudo apt-get install -y \
    ca-certificates curl gnupg lsb-release git

# Docker official GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Docker apt repo
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update -y
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin

# Allow ubuntu user to run docker without sudo
sudo usermod -aG docker "$USER"

# Enable Docker on boot
sudo systemctl enable docker
sudo systemctl start docker

echo "Docker version: $(docker --version)"

# ── 3. Clone repository ───────────────────────────────────────────
echo "[3/8] Cloning repository..."
REPO_DIR="/home/ubuntu/trading"

if [ -d "$REPO_DIR" ]; then
    echo "Directory $REPO_DIR already exists — pulling latest..."
    cd "$REPO_DIR" && git pull origin main
else
    # Replace with your actual repo URL
    git clone https://github.com/YOUR_USERNAME/agentic-trading.git "$REPO_DIR"
    cd "$REPO_DIR"
fi

# ── 4. Create .env from template ─────────────────────────────────
echo "[4/8] Setting up environment variables..."
if [ ! -f "$REPO_DIR/.env" ]; then
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
    echo ""
    echo "  ⚠️  IMPORTANT: Edit $REPO_DIR/.env and add your API keys before continuing!"
    echo "  Required: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, OPENAI_API_KEY"
    echo "  Run: nano $REPO_DIR/.env"
    echo ""
    read -p "Press ENTER after you have set your .env values..." _
fi

# ── 5. SSL certificate (self-signed for dev, Let's Encrypt for prod) ─
echo "[5/8] Setting up SSL certificates..."
SSL_DIR="$REPO_DIR/deploy/nginx/ssl"
mkdir -p "$SSL_DIR"

if [ ! -f "$SSL_DIR/fullchain.pem" ]; then
    echo "  Generating self-signed certificate (replace with Let's Encrypt for production)..."
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "$SSL_DIR/privkey.pem" \
        -out "$SSL_DIR/fullchain.pem" \
        -subj "/C=US/ST=State/L=City/O=Trading/CN=localhost" \
        2>/dev/null
    echo "  Self-signed SSL cert created at $SSL_DIR/"
fi

# ── 6. Build and start containers ────────────────────────────────
echo "[6/8] Building Docker image (this takes 5-10 minutes first time)..."
cd "$REPO_DIR"

# Build frontend first
echo "  Building React frontend..."
cd webapp/frontend && npm ci --silent && npm run build && cd ../..

# Build and start with Docker Compose
docker compose build --no-cache
docker compose up -d

echo "  Waiting for backend health check..."
sleep 15

if docker compose ps | grep -q "healthy"; then
    echo "  ✅ Backend is healthy"
else
    echo "  ⚠️  Backend not yet healthy — check logs: docker compose logs backend"
fi

# ── 7. Configure firewall (UFW) ───────────────────────────────────
echo "[7/8] Configuring firewall..."
sudo apt-get install -y ufw
sudo ufw allow 22/tcp   comment "SSH"
sudo ufw allow 80/tcp   comment "HTTP"
sudo ufw allow 443/tcp  comment "HTTPS"
sudo ufw --force enable
echo "  UFW status:"
sudo ufw status

# ── 8. Install systemd service for auto-restart on reboot ────────
echo "[8/8] Installing systemd service..."
sudo cp "$REPO_DIR/deploy/scripts/trading.service" /etc/systemd/system/trading.service
sudo systemctl daemon-reload
sudo systemctl enable trading.service
echo "  Systemd service 'trading' enabled (auto-starts on reboot)"

echo ""
echo "======================================================"
echo " ✅  Setup complete!"
echo "======================================================"
echo ""
echo " Application URLs:"
EC2_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "YOUR_EC2_IP")
echo "   Dashboard:  https://$EC2_IP"
echo "   API Health: https://$EC2_IP/api/health"
echo "   API Docs:   https://$EC2_IP/docs"
echo ""
echo " Useful commands:"
echo "   View logs:    docker compose -f $REPO_DIR/docker-compose.yml logs -f"
echo "   Restart:      docker compose -f $REPO_DIR/docker-compose.yml restart"
echo "   Stop:         docker compose -f $REPO_DIR/docker-compose.yml down"
echo "   Update code:  cd $REPO_DIR && git pull && docker compose up --build -d"
echo ""
