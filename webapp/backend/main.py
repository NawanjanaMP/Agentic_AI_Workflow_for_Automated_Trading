"""
webapp/backend/main.py

FastAPI backend for the Agentic Trading Dashboard.
Serves price data, signals, agent decisions, and risk metrics from S3/RDS.

Run locally:
    uvicorn webapp.backend.main:app --reload --port 8000

Run on EC2:
    uvicorn webapp.backend.main:app --host 0.0.0.0 --port 8000
"""

import os
import io
from datetime import datetime, timezone, timedelta
from typing import Optional
import numpy as np
import pandas as pd
import boto3
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

# ── App setup ─────────────────────────────────────────────────
app = FastAPI(
    title="Agentic Trading API",
    description="FastAPI backend for the Agentic AI Trading Dashboard",
    version="1.0.0"
)

# Allow React frontend to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # restrict to your domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── S3 client ─────────────────────────────────────────────────
s3 = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
)
RAW_BUCKET       = os.getenv("S3_RAW_BUCKET", "trading-raw-zone")
PROCESSED_BUCKET = os.getenv("S3_PROCESSED_BUCKET", "trading-processed-zone")

STOCK_SYMBOLS = [
    "AAPL","MSFT","GOOGL","AMZN","NVDA",
    "META","TSLA","JPM","GS","BAC","SPY","QQQ","IWM"
]
CRYPTO_SYMBOLS = ["BTC-USDT","ETH-USDT","SOL-USDT","BNB-USDT"]


# ── Helpers ───────────────────────────────────────────────────

def load_parquet_from_s3(bucket: str, key: str) -> pd.DataFrame:
    """Load a Parquet file from S3 into a DataFrame."""
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        df  = pd.read_parquet(io.BytesIO(obj["Body"].read()))
        return df
    except Exception as e:
        logger.warning(f"Could not load s3://{bucket}/{key}: {e}")
        return pd.DataFrame()


def get_latest_date(bucket: str, prefix: str) -> Optional[str]:
    """Find the most recent date-named file under a prefix."""
    try:
        resp  = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
        keys  = [o["Key"] for o in resp.get("Contents", [])]
        dates = sorted([k.split("/")[-1].replace(".parquet", "") for k in keys])
        return dates[-1] if dates else None
    except Exception:
        return None


def add_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Add technical indicators and Buy/Sell/Hold signals to a symbol DataFrame."""
    try:
        import ta
        d = df.copy().sort_index()

        d["sma_20"]  = ta.trend.sma_indicator(d["close"], window=20)
        d["sma_50"]  = ta.trend.sma_indicator(d["close"], window=50)
        d["sma_200"] = ta.trend.sma_indicator(d["close"], window=200)
        d["rsi_14"]  = ta.momentum.rsi(d["close"], window=14)

        macd = ta.trend.MACD(d["close"])
        d["macd"]        = macd.macd()
        d["macd_signal"] = macd.macd_signal()
        d["macd_hist"]   = macd.macd_diff()

        bb = ta.volatility.BollingerBands(d["close"], window=20, window_dev=2)
        d["bb_upper"]  = bb.bollinger_hband()
        d["bb_lower"]  = bb.bollinger_lband()
        d["bb_middle"] = bb.bollinger_mavg()
        d["bb_pct"]    = bb.bollinger_pband()

        d["atr_14"] = ta.volatility.average_true_range(
            d["high"], d["low"], d["close"], window=14
        )

        # Signal scoring
        score = pd.Series(0, index=d.index)
        score += (d["sma_50"]  > d["sma_200"]).astype(int)
        score -= (d["sma_50"]  < d["sma_200"]).astype(int)
        score += (d["close"]   > d["sma_20"]).astype(int)
        score -= (d["close"]   < d["sma_20"]).astype(int)
        score += (d["rsi_14"]  < 30).astype(int)
        score -= (d["rsi_14"]  > 70).astype(int)
        score += (d["macd"]    > d["macd_signal"]).astype(int)
        score -= (d["macd"]    < d["macd_signal"]).astype(int)
        score += (d["bb_pct"]  < 0.2).astype(int)
        score -= (d["bb_pct"]  > 0.8).astype(int)

        d["signal_score"] = score
        d["signal"] = "HOLD"
        d.loc[score >=  2, "signal"] = "BUY"
        d.loc[score <= -2, "signal"] = "SELL"

        return d
    except Exception as e:
        logger.error(f"Signal calculation failed: {e}")
        return df


# ── Routes ────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "message": "Agentic Trading API is running"}


@app.get("/api/symbols")
def get_symbols():
    """Return all tracked symbols."""
    return {
        "stocks": STOCK_SYMBOLS,
        "crypto": CRYPTO_SYMBOLS,
        "total":  len(STOCK_SYMBOLS) + len(CRYPTO_SYMBOLS)
    }


@app.get("/api/price/{symbol}")
def get_price_data(
    symbol: str,
    days: int = Query(default=365, ge=30, le=1095),
):
    """
    Return OHLCV + technical indicators for a symbol.
    Used by the price chart and indicator panels.
    """
    symbol = symbol.upper()
    is_crypto = symbol in [s.upper() for s in CRYPTO_SYMBOLS]

    # Find latest file
    if is_crypto:
        prefix = f"crypto/daily/{symbol}/"
        bucket = RAW_BUCKET
    else:
        prefix = f"stocks/daily/{symbol}/"
        bucket = RAW_BUCKET

    date = get_latest_date(bucket, prefix)
    if not date:
        raise HTTPException(404, f"No data found for {symbol}")

    df = load_parquet_from_s3(bucket, f"{prefix}{date}.parquet")
    if df.empty:
        raise HTTPException(404, f"Empty data for {symbol}")

    # Filter to requested days
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    if df.index.tzinfo is None:
        df.index = df.index.tz_localize("UTC")
    df = df[df.index >= cutoff]

    # Add signals
    df = add_signals(df)

    # Build response
    records = []
    for ts, row in df.iterrows():
        records.append({
            "date":         ts.strftime("%Y-%m-%d"),
            "open":         round(float(row.get("open",  0)), 4),
            "high":         round(float(row.get("high",  0)), 4),
            "low":          round(float(row.get("low",   0)), 4),
            "close":        round(float(row.get("close", 0)), 4),
            "volume":       int(row.get("volume", 0)),
            "sma_20":       round(float(row["sma_20"]),  4) if pd.notna(row.get("sma_20"))  else None,
            "sma_50":       round(float(row["sma_50"]),  4) if pd.notna(row.get("sma_50"))  else None,
            "sma_200":      round(float(row["sma_200"]), 4) if pd.notna(row.get("sma_200")) else None,
            "rsi_14":       round(float(row["rsi_14"]),  2) if pd.notna(row.get("rsi_14"))  else None,
            "macd":         round(float(row["macd"]),    4) if pd.notna(row.get("macd"))     else None,
            "macd_signal":  round(float(row["macd_signal"]), 4) if pd.notna(row.get("macd_signal")) else None,
            "macd_hist":    round(float(row["macd_hist"]),   4) if pd.notna(row.get("macd_hist"))    else None,
            "bb_upper":     round(float(row["bb_upper"]),  4) if pd.notna(row.get("bb_upper"))  else None,
            "bb_lower":     round(float(row["bb_lower"]),  4) if pd.notna(row.get("bb_lower"))  else None,
            "bb_middle":    round(float(row["bb_middle"]), 4) if pd.notna(row.get("bb_middle")) else None,
            "atr_14":       round(float(row["atr_14"]),    4) if pd.notna(row.get("atr_14"))    else None,
            "signal":       row.get("signal", "HOLD"),
            "signal_score": int(row.get("signal_score", 0)),
        })

    return {
        "symbol":  symbol,
        "days":    days,
        "count":   len(records),
        "data":    records,
    }


@app.get("/api/signals/latest")
def get_latest_signals():
    """
    Return the latest Buy/Sell/Hold signal for every symbol.
    Used by the signals summary table on the dashboard.
    """
    results = []

    for symbol in STOCK_SYMBOLS:
        try:
            prefix = f"stocks/daily/{symbol}/"
            date   = get_latest_date(RAW_BUCKET, prefix)
            if not date:
                continue
            df = load_parquet_from_s3(RAW_BUCKET, f"{prefix}{date}.parquet")
            if df.empty:
                continue
            df = add_signals(df)
            latest = df.iloc[-1]

            prev_close = float(df.iloc[-2]["close"]) if len(df) > 1 else None
            curr_close = float(latest["close"])
            change_pct = ((curr_close - prev_close) / prev_close * 100) if prev_close else 0

            results.append({
                "symbol":       symbol,
                "type":         "stock",
                "close":        round(curr_close, 2),
                "change_pct":   round(change_pct, 2),
                "rsi_14":       round(float(latest["rsi_14"]),  2) if pd.notna(latest.get("rsi_14"))  else None,
                "macd_hist":    round(float(latest["macd_hist"]), 4) if pd.notna(latest.get("macd_hist")) else None,
                "signal":       latest.get("signal", "HOLD"),
                "signal_score": int(latest.get("signal_score", 0)),
                "atr_14":       round(float(latest["atr_14"]), 4) if pd.notna(latest.get("atr_14")) else None,
            })
        except Exception as e:
            logger.warning(f"Skipping {symbol}: {e}")

    for symbol in CRYPTO_SYMBOLS:
        try:
            prefix = f"crypto/daily/{symbol}/"
            date   = get_latest_date(RAW_BUCKET, prefix)
            if not date:
                continue
            df = load_parquet_from_s3(RAW_BUCKET, f"{prefix}{date}.parquet")
            if df.empty:
                continue
            df = add_signals(df)
            latest = df.iloc[-1]

            prev_close = float(df.iloc[-2]["close"]) if len(df) > 1 else None
            curr_close = float(latest["close"])
            change_pct = ((curr_close - prev_close) / prev_close * 100) if prev_close else 0

            results.append({
                "symbol":       symbol,
                "type":         "crypto",
                "close":        round(curr_close, 2),
                "change_pct":   round(change_pct, 2),
                "rsi_14":       round(float(latest["rsi_14"]),  2) if pd.notna(latest.get("rsi_14"))  else None,
                "macd_hist":    round(float(latest["macd_hist"]), 4) if pd.notna(latest.get("macd_hist")) else None,
                "signal":       latest.get("signal", "HOLD"),
                "signal_score": int(latest.get("signal_score", 0)),
                "atr_14":       round(float(latest["atr_14"]), 4) if pd.notna(latest.get("atr_14")) else None,
            })
        except Exception as e:
            logger.warning(f"Skipping {symbol}: {e}")

    # Sort: BUY first, then HOLD, then SELL
    order = {"BUY": 0, "HOLD": 1, "SELL": 2}
    results.sort(key=lambda x: (order.get(x["signal"], 1), -abs(x["signal_score"])))

    return {"count": len(results), "signals": results}


@app.get("/api/metrics/portfolio")
def get_portfolio_metrics():
    """
    Return portfolio-level risk metrics.
    Used by the metrics cards at the top of the dashboard.
    """
    try:
        returns_list = []

        for symbol in STOCK_SYMBOLS[:10]:
            prefix = f"stocks/daily/{symbol}/"
            date   = get_latest_date(RAW_BUCKET, prefix)
            if not date:
                continue
            df = load_parquet_from_s3(RAW_BUCKET, f"{prefix}{date}.parquet")
            if df.empty or "close" not in df.columns:
                continue
            ret = df["close"].pct_change().dropna()
            ret.name = symbol
            returns_list.append(ret)

        if not returns_list:
            raise ValueError("No return data available")

        returns_df = pd.concat(returns_list, axis=1).dropna()

        # Equal-weight portfolio returns
        port_returns = returns_df.mean(axis=1)

        # Metrics
        ann_return  = float(port_returns.mean() * 252 * 100)
        ann_vol     = float(port_returns.std() * np.sqrt(252) * 100)
        sharpe      = ann_return / ann_vol if ann_vol > 0 else 0
        cum_returns = (1 + port_returns).cumprod()
        rolling_max = cum_returns.cummax()
        drawdown    = (cum_returns - rolling_max) / rolling_max
        max_dd      = float(drawdown.min() * 100)

        # Signal counts
        buy_count  = sum(1 for s in STOCK_SYMBOLS[:10] if _get_signal(s) == "BUY")
        sell_count = sum(1 for s in STOCK_SYMBOLS[:10] if _get_signal(s) == "SELL")
        hold_count = len(STOCK_SYMBOLS[:10]) - buy_count - sell_count

        return {
            "annualised_return_pct": round(ann_return, 2),
            "annualised_vol_pct":    round(ann_vol,    2),
            "sharpe_ratio":          round(sharpe,     3),
            "max_drawdown_pct":      round(max_dd,     2),
            "buy_signals":           buy_count,
            "sell_signals":          sell_count,
            "hold_signals":          hold_count,
            "assets_tracked":        len(STOCK_SYMBOLS) + len(CRYPTO_SYMBOLS),
        }

    except Exception as e:
        logger.error(f"Portfolio metrics error: {e}")
        # Return safe defaults if calculation fails
        return {
            "annualised_return_pct": 0,
            "annualised_vol_pct":    0,
            "sharpe_ratio":          0,
            "max_drawdown_pct":      0,
            "buy_signals":           0,
            "sell_signals":          0,
            "hold_signals":          0,
            "assets_tracked":        len(STOCK_SYMBOLS) + len(CRYPTO_SYMBOLS),
        }


def _get_signal(symbol: str) -> str:
    """Helper to get latest signal for a symbol."""
    try:
        prefix = f"stocks/daily/{symbol}/"
        date   = get_latest_date(RAW_BUCKET, prefix)
        if not date:
            return "HOLD"
        df = load_parquet_from_s3(RAW_BUCKET, f"{prefix}{date}.parquet")
        if df.empty:
            return "HOLD"
        df = add_signals(df)
        return df.iloc[-1].get("signal", "HOLD")
    except Exception:
        return "HOLD"


@app.get("/api/news/latest")
def get_latest_news():
    """Return latest news headlines from S3."""
    try:
        import json
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key   = f"news/newsapi/{today}.jsonl"

        obj      = s3.get_object(Bucket=RAW_BUCKET, Key=key)
        lines    = obj["Body"].read().decode("utf-8").strip().split("\n")
        articles = [json.loads(l) for l in lines if l.strip()][:20]

        return {"count": len(articles), "articles": articles}
    except Exception as e:
        logger.warning(f"News fetch failed: {e}")
        return {"count": 0, "articles": []}


@app.get("/api/health")
def health_check():
    """Health check endpoint for EC2 load balancer / monitoring."""
    return {
        "status":    "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version":   "1.0.0"
    }
