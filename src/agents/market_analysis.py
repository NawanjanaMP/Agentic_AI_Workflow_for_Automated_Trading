"""
src/agents/market_analysis.py

Market Analysis Module — computes signal vectors from S3 price data.
Output feeds directly into the LLM Decision Engine as structured context.
"""

import io
import os
import numpy as np
import pandas as pd
import boto3
import ta
from loguru import logger
from dotenv import load_dotenv

load_dotenv()


class MarketAnalysisModule:
    """
    Reads processed price data from S3 and produces a structured
    signal vector for each symbol. The signal vector is passed to
    the LLM agent as part of its context prompt.
    """

    def __init__(self):
        self.s3 = boto3.client(
            "s3",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        )
        self.bucket = os.getenv("S3_RAW_BUCKET", "trading-raw-zone")

    def _load_symbol(self, symbol: str, asset_type: str = "stocks") -> pd.DataFrame:
        """Load latest price data for a symbol from S3."""
        try:
            prefix = f"{asset_type}/daily/{symbol}/"
            resp   = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
            keys   = sorted([o["Key"] for o in resp.get("Contents", [])])
            if not keys:
                return pd.DataFrame()
            obj = self.s3.get_object(Bucket=self.bucket, Key=keys[-1])
            df  = pd.read_parquet(io.BytesIO(obj["Body"].read()))
            return df.sort_index()
        except Exception as e:
            logger.warning(f"Could not load {symbol}: {e}")
            return pd.DataFrame()

    def _compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add all technical indicators to a price DataFrame."""
        df = df.copy()
        df["sma_20"]  = ta.trend.sma_indicator(df["close"], window=20)
        df["sma_50"]  = ta.trend.sma_indicator(df["close"], window=50)
        df["sma_200"] = ta.trend.sma_indicator(df["close"], window=200)
        df["rsi_14"]  = ta.momentum.rsi(df["close"], window=14)
        macd = ta.trend.MACD(df["close"])
        df["macd"]        = macd.macd()
        df["macd_signal"] = macd.macd_signal()
        df["macd_hist"]   = macd.macd_diff()
        bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
        df["bb_upper"] = bb.bollinger_hband()
        df["bb_lower"] = bb.bollinger_lband()
        df["bb_pct"]   = bb.bollinger_pband()
        df["atr_14"]   = ta.volatility.average_true_range(
            df["high"], df["low"], df["close"], window=14
        )
        df["vol_20d"] = df["close"].pct_change().rolling(20).std() * np.sqrt(252) * 100
        return df

    def analyse(self, symbol: str, asset_type: str = "stocks") -> dict:
        """
        Run full market analysis for one symbol.

        Returns a signal vector dict containing:
        - Current price, volume, returns
        - All technical indicator values
        - Signal score and classification
        - Volatility regime
        - Plain-English summary for the LLM prompt
        """
        df = self._load_symbol(symbol, asset_type)
        if df.empty or len(df) < 30:
            return {"symbol": symbol, "error": "Insufficient data"}

        df  = self._compute_indicators(df)
        row = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else row

        # ── Signal scoring ─────────────────────────────────────
        score = 0
        reasons = []

        # Trend
        if pd.notna(row.get("sma_50")) and pd.notna(row.get("sma_200")):
            if row["sma_50"] > row["sma_200"]:
                score += 1
                reasons.append("SMA50 above SMA200 (bullish trend)")
            else:
                score -= 1
                reasons.append("SMA50 below SMA200 (bearish trend)")

        if pd.notna(row.get("sma_20")):
            if row["close"] > row["sma_20"]:
                score += 1
                reasons.append("Price above SMA20 (short-term bullish)")
            else:
                score -= 1
                reasons.append("Price below SMA20 (short-term bearish)")

        # Momentum — RSI
        if pd.notna(row.get("rsi_14")):
            if row["rsi_14"] < 30:
                score += 1
                reasons.append(f"RSI oversold at {row['rsi_14']:.1f} (potential reversal)")
            elif row["rsi_14"] > 70:
                score -= 1
                reasons.append(f"RSI overbought at {row['rsi_14']:.1f} (potential reversal)")
            else:
                reasons.append(f"RSI neutral at {row['rsi_14']:.1f}")

        # Momentum — MACD
        if pd.notna(row.get("macd")) and pd.notna(row.get("macd_signal")):
            if row["macd"] > row["macd_signal"]:
                score += 1
                reasons.append("MACD above signal line (bullish momentum)")
            else:
                score -= 1
                reasons.append("MACD below signal line (bearish momentum)")

        # Bollinger Bands
        if pd.notna(row.get("bb_pct")):
            if row["bb_pct"] < 0.2:
                score += 1
                reasons.append("Price near Bollinger lower band (oversold zone)")
            elif row["bb_pct"] > 0.8:
                score -= 1
                reasons.append("Price near Bollinger upper band (overbought zone)")

        # ── Signal classification ──────────────────────────────
        if score >= 2:
            signal = "BUY"
        elif score <= -2:
            signal = "SELL"
        else:
            signal = "HOLD"

        # ── Volatility regime ──────────────────────────────────
        vol = float(row.get("vol_20d", 0)) if pd.notna(row.get("vol_20d")) else 0
        if vol > 40:
            vol_regime = "HIGH"
        elif vol > 20:
            vol_regime = "MEDIUM"
        else:
            vol_regime = "LOW"

        # ── 5-day return ───────────────────────────────────────
        ret_5d = ((row["close"] / df.iloc[-6]["close"]) - 1) * 100 if len(df) >= 6 else 0

        # ── Build signal vector ────────────────────────────────
        vector = {
            "symbol":         symbol,
            "close":          round(float(row["close"]), 4),
            "volume":         int(row.get("volume", 0)),
            "return_5d_pct":  round(float(ret_5d), 2),
            "rsi_14":         round(float(row["rsi_14"]), 2)  if pd.notna(row.get("rsi_14"))  else None,
            "macd_hist":      round(float(row["macd_hist"]), 4) if pd.notna(row.get("macd_hist")) else None,
            "bb_pct":         round(float(row["bb_pct"]), 3)  if pd.notna(row.get("bb_pct"))  else None,
            "atr_14":         round(float(row["atr_14"]), 4)  if pd.notna(row.get("atr_14"))  else None,
            "volatility_20d": round(vol, 2),
            "vol_regime":     vol_regime,
            "sma50_vs_200":   "above" if pd.notna(row.get("sma_50")) and pd.notna(row.get("sma_200")) and row["sma_50"] > row["sma_200"] else "below",
            "signal_score":   score,
            "signal":         signal,
            "signal_reasons": reasons,
            "summary": (
                f"{symbol} is trading at ${row['close']:.2f} with a signal score of {score:+d} ({signal}). "
                f"RSI is {row['rsi_14']:.1f}, volatility regime is {vol_regime} ({vol:.1f}% annualised). "
                f"Key factors: {'; '.join(reasons[:3])}."
            ),
        }

        logger.info(f"Market analysis: {symbol} → {signal} (score={score:+d})")
        return vector

    def analyse_all(self, symbols: list, asset_type: str = "stocks") -> list[dict]:
        """Run market analysis for a list of symbols."""
        results = []
        for sym in symbols:
            result = self.analyse(sym, asset_type)
            results.append(result)
        return results
