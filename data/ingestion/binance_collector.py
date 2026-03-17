"""
data/ingestion/binance_collector.py

Collects crypto OHLCV data from Binance via the ccxt library.
Two modes:
  1. Historical REST — fetch past candles (run once for backfill)
  2. Real-time WebSocket — live tick streaming (continuous)

No Binance account needed for public market data.
Account keys are only required for trading (we skip that here).
"""

import asyncio
import io
import json
from datetime import datetime, timezone

import ccxt
import ccxt.pro as ccxtpro   # async WebSocket version
import pandas as pd
from loguru import logger

from config.settings import settings
from data.ingestion.yahoo_collector import S3Uploader


class BinanceCollector:
    """
    Fetches crypto OHLCV from Binance.

    Binance public API is free and does not require API keys for
    read-only market data — great for development/testing.
    """

    def __init__(self):
        # Public market data works without API keys.
        # Only attach keys if they are real (not placeholders).
        placeholders = {"", "your_key_here", "skip"}
        api_key = settings.BINANCE_API_KEY
        secret  = settings.BINANCE_SECRET_KEY

        config = {"enableRateLimit": True}
        if api_key not in placeholders and secret not in placeholders:
            config["apiKey"] = api_key
            config["secret"] = secret

        self.exchange = ccxt.binance(config)
        self.uploader = S3Uploader()

    # ── Historical REST Fetch ─────────────────────

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        since_days: int = 365 * 3,
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV candles via REST API.

        Args:
            symbol:      e.g. 'BTC/USDT'
            timeframe:   '1m','5m','15m','1h','4h','1d','1w'
            since_days:  How many days of history to fetch

        Returns:
            DataFrame with [timestamp, open, high, low, close, volume, symbol, source]
        """
        logger.info(f"Fetching Binance OHLCV | {symbol} | {timeframe} | {since_days}d")

        # Calculate start timestamp in ms
        now_ms = self.exchange.milliseconds()
        since_ms = now_ms - (since_days * 24 * 60 * 60 * 1000)

        all_candles = []
        while since_ms < now_ms:
            try:
                candles = self.exchange.fetch_ohlcv(
                    symbol,
                    timeframe=timeframe,
                    since=since_ms,
                    limit=1000,         # max per request
                )
                if not candles:
                    break

                all_candles.extend(candles)
                since_ms = candles[-1][0] + 1   # advance past last candle
                logger.debug(f"Fetched {len(candles)} candles, total: {len(all_candles)}")

            except ccxt.NetworkError as e:
                logger.warning(f"Network error, retrying: {e}")
                import time; time.sleep(5)
            except ccxt.ExchangeError as e:
                logger.error(f"Exchange error for {symbol}: {e}")
                break

        if not all_candles:
            return pd.DataFrame()

        df = pd.DataFrame(
            all_candles,
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.set_index("timestamp")
        df = df[~df.index.duplicated(keep="first")]     # deduplicate
        df["symbol"] = symbol.replace("/", "-")          # BTC-USDT for file names
        df["source"] = "binance"
        df["ingested_at"] = datetime.now(timezone.utc).isoformat()

        logger.success(f"Fetched {len(df)} candles for {symbol}")
        return df

    # ── WebSocket Streaming ───────────────────────

    async def stream_live(self, symbols: list, timeframe: str = "1m"):
        """
        Subscribe to live OHLCV streams via WebSocket (async).
        Aggregates completed candles and uploads to S3 every 5 minutes.

        Run this in a separate process / EC2 instance for continuous ingestion.

        Usage:
            asyncio.run(collector.stream_live(['BTC/USDT', 'ETH/USDT']))
        """
        exchange_ws = ccxtpro.binance()
        buffer = {s: [] for s in symbols}

        logger.info(f"Starting live WebSocket streams for: {symbols}")
        try:
            while True:
                for symbol in symbols:
                    try:
                        ohlcv = await exchange_ws.watch_ohlcv(symbol, timeframe)
                        # ohlcv is a list of [timestamp, open, high, low, close, volume]
                        latest = ohlcv[-1]

                        candle = {
                            "timestamp": pd.to_datetime(latest[0], unit="ms", utc=True).isoformat(),
                            "open": latest[1],
                            "high": latest[2],
                            "low": latest[3],
                            "close": latest[4],
                            "volume": latest[5],
                            "symbol": symbol.replace("/", "-"),
                            "source": "binance_ws",
                            "ingested_at": datetime.now(timezone.utc).isoformat(),
                        }
                        buffer[symbol].append(candle)
                        logger.debug(f"Live tick | {symbol} | close={latest[4]}")

                        # Flush buffer to S3 every 100 candles
                        if len(buffer[symbol]) >= 100:
                            await self._flush_to_s3(symbol, buffer[symbol])
                            buffer[symbol] = []

                    except Exception as e:
                        logger.error(f"Stream error for {symbol}: {e}")

        finally:
            await exchange_ws.close()

    async def _flush_to_s3(self, symbol: str, candles: list):
        """Convert buffered candles to Parquet and upload to S3."""
        df = pd.DataFrame(candles)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        safe_sym = symbol.replace("/", "-")
        key = f"crypto/live/{safe_sym}/{ts}.parquet"
        self.uploader.upload_parquet(df, key)

    # ── Run Historical ────────────────────────────

    def run_historical(self, symbols: list = None, timeframe: str = "1d"):
        """Backfill 3 years of daily OHLCV for all crypto symbols."""
        symbols = symbols or settings.CRYPTO_SYMBOLS
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        for symbol in symbols:
            df = self.fetch_ohlcv(symbol, timeframe=timeframe)
            if df.empty:
                continue
            safe_sym = symbol.replace("/", "-")
            key = f"crypto/daily/{safe_sym}/{today}.parquet"
            self.uploader.upload_parquet(df, key)

        logger.success("Binance historical backfill complete.")

    def run_live(self, symbols: list = None):
        """Start live WebSocket streaming (blocking)."""
        symbols = symbols or settings.CRYPTO_SYMBOLS
        asyncio.run(self.stream_live(symbols))


if __name__ == "__main__":
    collector = BinanceCollector()

    # Run historical backfill
    logger.info("=== Binance Historical Backfill ===")
    collector.run_historical()

    # To start live streaming (run separately / on EC2):
    # collector.run_live()