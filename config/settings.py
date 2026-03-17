"""
config/settings.py
Central configuration — loads from .env automatically.
Usage: from config.settings import settings
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # ── API Keys ──────────────────────────────────
    ALPHA_VANTAGE_API_KEY: str = os.getenv("ALPHA_VANTAGE_API_KEY", "")
    BINANCE_API_KEY: str = os.getenv("BINANCE_API_KEY", "")
    BINANCE_SECRET_KEY: str = os.getenv("BINANCE_SECRET_KEY", "")
    NEWS_API_KEY: str = os.getenv("NEWS_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # ── AWS ───────────────────────────────────────
    AWS_ACCESS_KEY_ID: str = os.getenv("AWS_ACCESS_KEY_ID", "")
    AWS_SECRET_ACCESS_KEY: str = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    AWS_DEFAULT_REGION: str = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    S3_RAW_BUCKET: str = os.getenv("S3_RAW_BUCKET", "trading-raw-zone")
    S3_PROCESSED_BUCKET: str = os.getenv("S3_PROCESSED_BUCKET", "trading-processed-zone")

    # ── RDS / Database ────────────────────────────
    RDS_HOST: str = os.getenv("RDS_HOST", "localhost")
    RDS_PORT: int = int(os.getenv("RDS_PORT", "5432"))
    RDS_DATABASE: str = os.getenv("RDS_DATABASE", "trading_db")
    RDS_USER: str = os.getenv("RDS_USER", "trading_user")
    RDS_PASSWORD: str = os.getenv("RDS_PASSWORD", "")

    @property
    def rds_connection_string(self) -> str:
        return (
            f"postgresql://{self.RDS_USER}:{self.RDS_PASSWORD}"
            f"@{self.RDS_HOST}:{self.RDS_PORT}/{self.RDS_DATABASE}"
        )

    # ── Assets to Track ───────────────────────────
    STOCK_SYMBOLS: list = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
        "META", "TSLA", "JPM", "GS", "BAC",
        "SPY", "QQQ", "IWM",              # ETFs
    ]
    CRYPTO_SYMBOLS: list = [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
    ]

    # ── Data Fetch Windows ────────────────────────
    HISTORICAL_PERIOD: str = "3y"          # for initial backfill
    INTRADAY_INTERVAL: str = "1h"

    # ── App ───────────────────────────────────────
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")


settings = Settings()
