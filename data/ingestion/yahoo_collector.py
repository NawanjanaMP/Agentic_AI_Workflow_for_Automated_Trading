"""
data/ingestion/yahoo_collector.py

Collects OHLCV + fundamentals from Yahoo Finance via yfinance.
Stores raw data to AWS S3 (raw zone) as Parquet files.

Usage:
    python data/ingestion/yahoo_collector.py
"""

import io
import json
from datetime import datetime, timezone

import boto3
import pandas as pd
import yfinance as yf
from loguru import logger

from config.settings import settings


# ─────────────────────────────────────────────────
# S3 Helper
# ─────────────────────────────────────────────────

class S3Uploader:
    """Thin wrapper around boto3 for uploading DataFrames to S3."""

    def __init__(self):
        self.client = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_DEFAULT_REGION,
        )
        self.bucket = settings.S3_RAW_BUCKET

    def upload_parquet(self, df: pd.DataFrame, s3_key: str) -> bool:
        """Upload a DataFrame as Parquet to S3. Returns True on success."""
        try:
            buffer = io.BytesIO()
            df.to_parquet(buffer, index=True, engine="pyarrow")
            buffer.seek(0)
            self.client.put_object(
                Bucket=self.bucket,
                Key=s3_key,
                Body=buffer.getvalue(),
                ContentType="application/octet-stream",
            )
            logger.info(f"Uploaded → s3://{self.bucket}/{s3_key}")
            return True
        except Exception as e:
            logger.error(f"S3 upload failed for {s3_key}: {e}")
            return False

    def upload_json(self, data: dict, s3_key: str) -> bool:
        """Upload a dict as JSON to S3."""
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=s3_key,
                Body=json.dumps(data, default=str),
                ContentType="application/json",
            )
            logger.info(f"Uploaded JSON → s3://{self.bucket}/{s3_key}")
            return True
        except Exception as e:
            logger.error(f"S3 JSON upload failed for {s3_key}: {e}")
            return False


# ─────────────────────────────────────────────────
# Yahoo Finance Collector
# ─────────────────────────────────────────────────

class YahooCollector:
    """
    Fetches OHLCV price data and company fundamentals from Yahoo Finance.

    Data is cleaned, tagged with lineage metadata, and uploaded to S3
    under a date-partitioned path:
        stocks/daily/SYMBOL/YYYY-MM-DD.parquet
        stocks/fundamentals/SYMBOL/YYYY-MM-DD.json
    """

    def __init__(self):
        self.uploader = S3Uploader()

    # ── OHLCV ────────────────────────────────────

    def fetch_ohlcv(self, symbol: str, period: str = "3y", interval: str = "1d") -> pd.DataFrame:
        """
        Download OHLCV data for a single symbol.

        Args:
            symbol:   Ticker string e.g. 'AAPL'
            period:   How far back to fetch: '1d','5d','1mo','3mo','6mo','1y','2y','3y','5y','10y','ytd','max'
            interval: Bar size: '1m','5m','15m','30m','60m','1d','1wk','1mo'

        Returns:
            Cleaned DataFrame with columns:
            [open, high, low, close, adj_close, volume, symbol, source, ingested_at]
        """
        logger.info(f"Fetching Yahoo Finance OHLCV | {symbol} | period={period} interval={interval}")
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval, auto_adjust=False)

            if df.empty:
                logger.warning(f"No data returned for {symbol}")
                return pd.DataFrame()

            # Normalise column names to snake_case
            df.columns = [c.lower().replace(" ", "_") for c in df.columns]
            df = df.rename(columns={"adj_close": "adj_close"})

            # Keep only core OHLCV columns
            keep = [c for c in ["open", "high", "low", "close", "adj_close", "volume"] if c in df.columns]
            df = df[keep].copy()

            # Ensure UTC timestamps
            if df.index.tzinfo is None:
                df.index = df.index.tz_localize("UTC")
            else:
                df.index = df.index.tz_convert("UTC")
            df.index.name = "timestamp"

            # Drop rows where close is NaN (weekends / holidays sometimes slip through)
            df = df.dropna(subset=["close"])

            # Add lineage columns
            df["symbol"] = symbol
            df["source"] = "yahoo_finance"
            df["ingested_at"] = datetime.now(timezone.utc).isoformat()

            logger.success(f"Fetched {len(df)} rows for {symbol}")
            return df

        except Exception as e:
            logger.error(f"Failed to fetch OHLCV for {symbol}: {e}")
            return pd.DataFrame()

    # ── Fundamentals ─────────────────────────────

    def fetch_fundamentals(self, symbol: str) -> dict:
        """
        Fetch key fundamental metrics (P/E, market cap, sector, etc.)
        Returns a flat dict ready for JSON storage.
        """
        logger.info(f"Fetching fundamentals for {symbol}")
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info

            fundamentals = {
                "symbol": symbol,
                "company_name": info.get("longName"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "eps": info.get("trailingEps"),
                "revenue_ttm": info.get("totalRevenue"),
                "gross_margin": info.get("grossMargins"),
                "debt_to_equity": info.get("debtToEquity"),
                "current_ratio": info.get("currentRatio"),
                "dividend_yield": info.get("dividendYield"),
                "52w_high": info.get("fiftyTwoWeekHigh"),
                "52w_low": info.get("fiftyTwoWeekLow"),
                "avg_volume_10d": info.get("averageVolume10days"),
                "beta": info.get("beta"),
                "source": "yahoo_finance",
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            }
            return fundamentals

        except Exception as e:
            logger.error(f"Failed to fetch fundamentals for {symbol}: {e}")
            return {}

    # ── Upload Helpers ────────────────────────────

    def _ohlcv_s3_key(self, symbol: str, date_str: str, interval: str) -> str:
        """Build partitioned S3 key for OHLCV data."""
        freq = "daily" if interval == "1d" else "intraday"
        return f"stocks/{freq}/{symbol}/{date_str}.parquet"

    def _fundamentals_s3_key(self, symbol: str, date_str: str) -> str:
        return f"stocks/fundamentals/{symbol}/{date_str}.json"

    # ── Main Run ──────────────────────────────────

    def run(self, symbols: list = None, period: str = "3y", interval: str = "1d"):
        """
        Collect and store data for a list of symbols.

        Args:
            symbols:  List of ticker strings. Defaults to settings.STOCK_SYMBOLS
            period:   Historical window (passed to yfinance)
            interval: Bar interval (passed to yfinance)
        """
        symbols = symbols or settings.STOCK_SYMBOLS
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        results = {"success": [], "failed": []}

        for symbol in symbols:
            # ── OHLCV ──
            df = self.fetch_ohlcv(symbol, period=period, interval=interval)
            if not df.empty:
                key = self._ohlcv_s3_key(symbol, today, interval)
                ok = self.uploader.upload_parquet(df, key)
                if ok:
                    results["success"].append(symbol)
                else:
                    results["failed"].append(symbol)
            else:
                results["failed"].append(symbol)

            # ── Fundamentals (daily only) ──
            if interval == "1d":
                fundamentals = self.fetch_fundamentals(symbol)
                if fundamentals:
                    key = self._fundamentals_s3_key(symbol, today)
                    self.uploader.upload_json(fundamentals, key)

        # Summary
        logger.info(
            f"Collection complete | "
            f"Success: {len(results['success'])} | "
            f"Failed: {len(results['failed'])}"
        )
        if results["failed"]:
            logger.warning(f"Failed symbols: {results['failed']}")

        return results


# ─────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────

if __name__ == "__main__":
    collector = YahooCollector()

    # Initial 3-year historical backfill (run once)
    logger.info("=== Starting historical backfill ===")
    collector.run(period="3y", interval="1d")

    # For daily updates (run via Airflow/Lambda after initial backfill):
    # collector.run(period="5d", interval="1d")
    # For intraday (1-hour bars):
    # collector.run(period="60d", interval="1h")
