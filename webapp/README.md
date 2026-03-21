# Web Application — Agentic Trading Dashboard

React + FastAPI dashboard connected to your AWS S3 data pipeline.

## Run Locally (Development)

### Backend (FastAPI)
```powershell
# From project root, venv active
pip install -r webapp/backend/requirements.txt
uvicorn webapp.backend.main:app --reload --port 8000
```
API docs available at: http://localhost:8000/docs

### Frontend (React)
```powershell
cd webapp/frontend
npm install
npm run dev
```
Dashboard at: http://localhost:3000

---

## Deploy to AWS EC2 (Free Tier)

### Step 1 — Launch EC2 instance
1. Go to https://console.aws.amazon.com/ec2
2. Launch Instance → Ubuntu 22.04 → t2.micro (Free Tier)
3. Create key pair → download .pem file
4. Security Group: open ports 22 (SSH), 80 (HTTP)

### Step 2 — Connect to EC2
```bash
ssh -i your-key.pem ubuntu@YOUR_EC2_PUBLIC_IP
```

### Step 3 — Run deploy script
```bash
# Upload script
scp -i your-key.pem webapp/deploy_ec2.sh ubuntu@YOUR_EC2_PUBLIC_IP:~

# Run it
ssh -i your-key.pem ubuntu@YOUR_EC2_PUBLIC_IP
chmod +x deploy_ec2.sh
./deploy_ec2.sh
```

### Step 4 — Add your .env
```bash
nano /home/ubuntu/app/.env
# Add your AWS credentials
sudo systemctl restart trading-api
```

### Step 5 — Visit your dashboard
```
http://YOUR_EC2_PUBLIC_IP
```

---

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/symbols` | All tracked symbols |
| `GET /api/price/{symbol}?days=365` | OHLCV + indicators for a symbol |
| `GET /api/signals/latest` | Latest Buy/Sell/Hold for all assets |
| `GET /api/metrics/portfolio` | Portfolio risk metrics |
| `GET /api/news/latest` | Latest news headlines |
| `GET /api/health` | Health check |
| `GET /docs` | Interactive API docs (Swagger UI) |
