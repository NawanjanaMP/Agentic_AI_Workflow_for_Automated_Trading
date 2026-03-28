#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# deploy/scripts/update.sh
#
# Zero-downtime update: pull latest code → rebuild → restart.
# Run on the EC2 instance to deploy new code.
# ─────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="/home/ubuntu/trading"
cd "$REPO_DIR"

echo "[1/4] Pulling latest code..."
git pull origin main

echo "[2/4] Rebuilding Docker image..."
docker compose build --no-cache backend

echo "[3/4] Restarting containers..."
docker compose up -d --force-recreate backend

echo "[4/4] Waiting for health check..."
sleep 15
if docker compose ps | grep -q "healthy"; then
    echo "✅  Update complete — backend is healthy"
else
    echo "⚠️  Backend not healthy — check: docker compose logs backend"
    exit 1
fi
