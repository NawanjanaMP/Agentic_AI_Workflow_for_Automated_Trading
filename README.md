# Agentic AI Trading Workflow System

> **Data Science Project — Option 1 (Finance Domain)**
> Autonomous market analysis, news retrieval, and Buy/Sell/Hold decision engine powered by Agentic AI.

---

## Project Structure

```
agentic-trading/
├── config/
│   └── settings.py          # Central config — loads from .env
├── data/
│   └── ingestion/
│       ├── yahoo_collector.py        # Stock OHLCV + fundamentals
│       ├── alpha_vantage_collector.py # Technical indicators
│       ├── binance_collector.py       # Crypto OHLCV (REST + WebSocket)
│       └── news_collector.py          # NewsAPI + RSS feeds
├── src/
│   ├── agents/              # LangChain agentic AI (Phase 4)
│   ├── models/              # ML models — XGBoost, GARCH (Phase 3)
│   ├── risk/                # Risk management module (Phase 4)
│   └── pipelines/
│       └── data_collection_dag.py    # Airflow orchestration DAG
├── cloud/
│   └── setup_aws.py         # One-time AWS provisioning
├── notebooks/               # EDA Jupyter notebooks (Phase 2)
├── tests/                   # Unit tests
├── docs/                    # Architecture diagrams, reports
├── .env.example             # Environment variable template
├── requirements.txt         # Python dependencies
└── README.md
```

---

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/YOUR_USERNAME/agentic-trading.git
cd agentic-trading

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your API keys (see API Keys section below)
```

### 3. Set Up AWS (one-time)

```bash
# After adding AWS credentials to .env:
python cloud/setup_aws.py
```

### 4. Run Data Collection

```bash
# Initial historical backfill (run once — downloads 3 years of data)
python data/ingestion/yahoo_collector.py

# Crypto historical data
python data/ingestion/binance_collector.py

# News headlines
python data/ingestion/news_collector.py

# Or run everything at once:
python src/pipelines/data_collection_dag.py
```

---

## API Keys — Free Tier Setup

| Service | Free Tier | Sign Up |
|---------|-----------|---------|
| Yahoo Finance (yfinance) | Unlimited (unofficial) | No key needed |
| Alpha Vantage | 25 req/day | https://alphavantage.co |
| Binance | Public data free | No key for read-only |
| NewsAPI | 100 req/day | https://newsapi.org |
| AWS | 12-month free tier | https://aws.amazon.com/free |

---

## AWS Setup Guide (Free Tier)

### Step 1 — Create AWS Account
1. Go to https://aws.amazon.com/free
2. Sign up (credit card needed but won't be charged on free tier)
3. Enable MFA on root account (security)

### Step 2 — Create IAM User
1. IAM Console → Users → Create User
2. Attach policies: `AmazonS3FullAccess`, `AmazonRDSFullAccess`
3. Create Access Key → copy to `.env`

### Step 3 — Run Setup Script
```bash
python cloud/setup_aws.py
```
This creates S3 buckets + RDS PostgreSQL automatically.

### Step 4 — Open RDS Port
1. AWS Console → RDS → trading-db → Connectivity
2. VPC Security Group → Inbound Rules → Add Rule
3. Type: PostgreSQL, Port: 5432, Source: My IP

---

## Data Pipeline Architecture

```
APIs/WebSocket ─────────────────────────────────┐
  Yahoo Finance (yfinance)                       │
  Alpha Vantage (indicators)                     ▼
  Binance (crypto OHLCV)              Lambda (Validate + Route)
  NewsAPI + RSS (headlines)                      │
                                    ┌────────────┴────────────┐
                                    ▼                         ▼
                             S3 — Raw Zone            RDS PostgreSQL
                             stocks/daily/            fundamentals
                             stocks/indicators/       news_articles
                             crypto/daily/            trade_decisions
                             news/newsapi/
                                    │
                                    ▼
                             S3 — Processed Zone
                             (cleaned + feature-engineered)
                                    │
                                    ▼
                          EC2 — Agentic AI Engine
                          (LangChain + LLM Decision)
```

---

## Project Phases

| Phase | Status | Description |
|-------|--------|-------------|
| **Phase 1** — Data Collection | ✅ Complete | APIs, S3, RDS, Airflow DAG |
| **Phase 2** — EDA | 🔲 Next | Cleaning, features, signals |
| **Phase 3** — ML Models | 🔲 Upcoming | XGBoost, GARCH, clustering |
| **Phase 4** — Agentic AI | 🔲 Upcoming | LangChain agent + RAG |
| **Phase 5** — Backtesting | 🔲 Upcoming | Backtrader, walk-forward |
| **Phase 6** — Reporting | 🔲 Upcoming | Final report + presentation |

---

## Git Workflow

```bash
# Create feature branch
git checkout -b feature/eda-feature-engineering

# Commit with meaningful messages
git add .
git commit -m "feat: add RSI/MACD feature calculation in EDA notebook"

# Push and open Pull Request
git push origin feature/eda-feature-engineering
```

Branch naming:
- `feature/` — new functionality
- `bugfix/` — bug fixes
- `docs/` — documentation
- `infra/` — cloud/infra changes

---

## Running Tests

```bash
pytest tests/ -v --cov=src --cov-report=term-missing
```
