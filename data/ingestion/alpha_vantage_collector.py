"""
data/ingestion/alpha_vantage_collector.py

Fetches technical indicators from Alpha Vantage API:
RSI, MACD, Bollinger Bands, SMA, EMA — stored to S3.

Free tier: 25 requests/day  |  Premium: 75–1200/min
Sign up free: https://www.alphavantage.co/support/#api-key
"""

import time
import io
from datetime import datetime, timezone

import pandas as pd
import requests
from loguru import logger

from config.settings import settings
from data.ingestion.yahoo_collector import S3Uploader


class AlphaVantageCollector:
    """
    Pulls pre-computed technical indicators from Alpha Vantage.

    Why use this alongside yfinance?
    - Alpha Vantage indicators are server-side calculated (consistent)
    - Useful cross-validation against our own TA calculations
    - Also provides intraday data with higher rate limits on paid tiers
    """

    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(self):
        self.api_key = settings.ALPHA_VANTAGE_API_KEY
        self.uploader = S3Uploader()
        self._request_count = 0

    def _get(self, params: dict) -> dict:
        """Make a single API request with rate-limit awareness."""
        params["apikey"] = self.api_key
        try:
            resp = requests.get(self.BASE_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            # Alpha Vantage signals rate limits via JSON messages
            if "Note" in data:
                logger.warning("Alpha Vantage rate limit hit — sleeping 60s")
                time.sleep(61)
                return self._get(params)  # retry once

            if "Error Message" in data:
                logger.error(f"Alpha Vantage error: {data['Error Message']}")
                return {}

            self._request_count += 1
            # Free tier: max 25/day, ~5/min — respect limit
            time.sleep(13)   # ~4.6 req/min, safe for free tier
            return data

        except requests.RequestException as e:
            logger.error(f"Request failed: {e}")
            return {}

    # ── Indicator Fetchers ────────────────────────

    def fetch_rsi(self, symbol: str, interval: str = "daily", time_period: int = 14) -> pd.DataFrame:
        """
        Fetch RSI (Relative Strength Index).
        RSI < 30 = oversold (potential buy), RSI > 70 = overbought (potential sell).
        """
        data = self._get({
            "function": "RSI",
            "symbol": symbol,
            "interval": interval,
            "time_period": time_period,
            "series_type": "close",
        })
        return self._parse_indicator(data, "Technical Analysis: RSI", "RSI", symbol)

    def fetch_macd(self, symbol: str, interval: str = "daily") -> pd.DataFrame:
        """
        Fetch MACD (Moving Average Convergence Divergence).
        Returns MACD line, signal line, and histogram.
        """
        data = self._get({
            "function": "MACD",
            "symbol": symbol,
            "interval": interval,
            "series_type": "close",
            "fastperiod": 12,
            "slowperiod": 26,
            "signalperiod": 9,
        })
        return self._parse_indicator(data, "Technical Analysis: MACD", ["MACD", "MACD_Signal", "MACD_Hist"], symbol)

    def fetch_bbands(self, symbol: str, interval: str = "daily", time_period: int = 20) -> pd.DataFrame:
        """
        Fetch Bollinger Bands.
        Returns upper, middle (SMA), lower bands.
        """
        data = self._get({
            "function": "BBANDS",
            "symbol": symbol,
            "interval": interval,
            "time_period": time_period,
            "series_type": "close",
            "nbdevup": 2,
            "nbdevdn": 2,
        })
        return self._parse_indicator(
            data,
            "Technical Analysis: BBANDS",
            ["Real Upper Band", "Real Middle Band", "Real Lower Band"],
            symbol,
        )

    def fetch_sma(self, symbol: str, interval: str = "daily", time_period: int = 50) -> pd.DataFrame:
        """Fetch Simple Moving Average."""
        data = self._get({
            "function": "SMA",
            "symbol": symbol,
            "interval": interval,
            "time_period": time_period,
            "series_type": "close",
        })
        return self._parse_indicator(data, f"Technical Analysis: SMA", "SMA", symbol)

    # ── Parser ────────────────────────────────────

    def _parse_indicator(self, data: dict, data_key: str, columns, symbol: str) -> pd.DataFrame:
        """Parse Alpha Vantage indicator response into a clean DataFrame."""
        if not data or data_key not in data:
            logger.warning(f"No data for key '{data_key}'")
            return pd.DataFrame()

        records = data[data_key]
        df = pd.DataFrame.from_dict(records, orient="index")
        df.index = pd.to_datetime(df.index, utc=True)
        df.index.name = "timestamp"
        df = df.sort_index()

        # Rename columns to lowercase
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]

        # Cast all to float
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df["symbol"] = symbol
        df["source"] = "alpha_vantage"
        df["ingested_at"] = datetime.now(timezone.utc).isoformat()

        return df

    # ── Run ───────────────────────────────────────

    def run(self, symbols: list = None):
        """
        Fetch RSI, MACD, and Bollinger Bands for all symbols.
        Uploads each indicator as a separate Parquet file to S3.

        NOTE: With the free tier (25 req/day), this can process ~6 symbols
        (4 indicators × 6 = 24 requests). Upgrade to premium for full coverage
        or spread across multiple days.
        """
        symbols = symbols or settings.STOCK_SYMBOLS
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        for symbol in symbols:
            logger.info(f"Processing indicators for {symbol}")

            indicators = {
                "rsi_14": self.fetch_rsi(symbol),
                "macd": self.fetch_macd(symbol),
                "bbands_20": self.fetch_bbands(symbol),
                "sma_50": self.fetch_sma(symbol, time_period=50),
            }

            for name, df in indicators.items():
                if df.empty:
                    continue
                key = f"stocks/indicators/{symbol}/{name}/{today}.parquet"
                self.uploader.upload_parquet(df, key)

            # Check daily limit (free tier)
            if self._request_count >= 20:
                logger.warning(
                    f"Approaching Alpha Vantage free tier limit "
                    f"({self._request_count} requests). Stopping."
                )
                break

        logger.success(
            f"Alpha Vantage collection done. "
            f"Total API calls: {self._request_count}"
        )


if __name__ == "__main__":
    collector = AlphaVantageCollector()
    # Collect for first 5 symbols (free tier safe)
    collector.run(symbols=settings.STOCK_SYMBOLS[:5])
