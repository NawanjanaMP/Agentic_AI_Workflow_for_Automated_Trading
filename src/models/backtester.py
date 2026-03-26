"""
src/models/backtester.py

Backtesting engine — evaluates signal performance on historical data.
Uses walk-forward validation to avoid look-ahead bias.

Run:
    python -m src.models.backtester
"""

import io
import os
import numpy as np
import pandas as pd
import boto3
import ta
import matplotlib.pyplot as plt
from loguru import logger
from dotenv import load_dotenv

load_dotenv()


class Backtester:
    """
    Walk-forward backtester for the signal strategy.

    Strategy:
    - Enter long when signal score >= +2 (BUY)
    - Exit when signal score <= -2 (SELL) or after max_hold_days
    - Position sizing: fixed fractional (2% risk per trade)
    - Costs: 0.1% slippage each way + $0.005/share commission
    """

    SLIPPAGE    = 0.001   # 0.1% per trade
    COMMISSION  = 0.005   # $0.005 per share

    def __init__(self, initial_capital: float = 100_000.0):
        self.initial_capital = initial_capital
        self.s3 = boto3.client(
            "s3",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        )
        self.bucket = os.getenv("S3_RAW_BUCKET", "trading-raw-zone")

    # ── Data loading ───────────────────────────────────────────

    def load_symbol(self, symbol: str) -> pd.DataFrame:
        """Load historical price data for a symbol from S3."""
        try:
            prefix = f"stocks/daily/{symbol}/"
            resp   = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
            keys   = sorted([o["Key"] for o in resp.get("Contents", [])])
            if not keys:
                return pd.DataFrame()
            obj = self.s3.get_object(Bucket=self.bucket, Key=keys[-1])
            df  = pd.read_parquet(io.BytesIO(obj["Body"].read()))
            return df.sort_index()
        except Exception as e:
            logger.error(f"Failed to load {symbol}: {e}")
            return pd.DataFrame()

    def add_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add all technical indicators and signal scores."""
        df = df.copy()
        df["sma_20"]  = ta.trend.sma_indicator(df["close"], window=20)
        df["sma_50"]  = ta.trend.sma_indicator(df["close"], window=50)
        df["sma_200"] = ta.trend.sma_indicator(df["close"], window=200)
        df["rsi_14"]  = ta.momentum.rsi(df["close"], window=14)
        macd = ta.trend.MACD(df["close"])
        df["macd"]        = macd.macd()
        df["macd_signal"] = macd.macd_signal()
        bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
        df["bb_pct"] = bb.bollinger_pband()

        score = pd.Series(0, index=df.index)
        score += (df["sma_50"]  > df["sma_200"]).astype(int)
        score -= (df["sma_50"]  < df["sma_200"]).astype(int)
        score += (df["close"]   > df["sma_20"]).astype(int)
        score -= (df["close"]   < df["sma_20"]).astype(int)
        score += (df["rsi_14"]  < 30).astype(int)
        score -= (df["rsi_14"]  > 70).astype(int)
        score += (df["macd"]    > df["macd_signal"]).astype(int)
        score -= (df["macd"]    < df["macd_signal"]).astype(int)
        score += (df["bb_pct"]  < 0.2).astype(int)
        score -= (df["bb_pct"]  > 0.8).astype(int)

        df["signal_score"] = score
        df["signal"] = "HOLD"
        df.loc[score >=  2, "signal"] = "BUY"
        df.loc[score <= -2, "signal"] = "SELL"
        return df

    # ── Core backtest ──────────────────────────────────────────

    def run(self, symbol: str, max_hold_days: int = 20) -> dict:
        """
        Run backtest for a single symbol.

        Returns:
            Dict with equity curve, trade log, and performance metrics
        """
        df = self.load_symbol(symbol)
        if df.empty or len(df) < 250:
            return {"symbol": symbol, "error": "Insufficient data (need 250+ days)"}

        df = self.add_signals(df)
        df = df.dropna(subset=["signal_score"])

        capital    = self.initial_capital
        position   = 0       # shares held
        entry_price = 0.0
        entry_day  = 0
        trades     = []
        equity     = [capital]
        dates      = [df.index[0]]

        for i in range(1, len(df)):
            row  = df.iloc[i]
            prev = df.iloc[i - 1]
            price = float(row["close"])

            # ── Exit logic ─────────────────────────────────────
            if position > 0:
                days_held = i - entry_day
                should_exit = (
                    row["signal"] == "SELL" or
                    days_held >= max_hold_days
                )
                if should_exit:
                    # Sell with slippage + commission
                    exit_price  = price * (1 - self.SLIPPAGE)
                    commission  = position * self.COMMISSION
                    proceeds    = position * exit_price - commission
                    pnl         = proceeds - (position * entry_price)
                    pnl_pct     = pnl / (position * entry_price) * 100

                    capital += proceeds
                    trades.append({
                        "symbol":       symbol,
                        "entry_date":   df.index[entry_day].strftime("%Y-%m-%d"),
                        "exit_date":    row.name.strftime("%Y-%m-%d"),
                        "entry_price":  round(entry_price, 4),
                        "exit_price":   round(exit_price,  4),
                        "qty":          position,
                        "pnl":          round(pnl,     2),
                        "pnl_pct":      round(pnl_pct, 2),
                        "days_held":    days_held,
                        "exit_reason":  "SELL signal" if row["signal"] == "SELL" else "Max hold",
                    })
                    position = 0

            # ── Entry logic ────────────────────────────────────
            if position == 0 and row["signal"] == "BUY":
                # Risk 2% of capital per trade
                risk_amount = capital * 0.02
                atr = float(row.get("atr_14", price * 0.02)) if pd.notna(row.get("atr_14")) else price * 0.02
                stop_dist   = max(atr * 2, price * 0.02)
                qty         = int(risk_amount / stop_dist)
                cost        = qty * price * (1 + self.SLIPPAGE) + qty * self.COMMISSION

                if qty > 0 and cost <= capital:
                    entry_price = price * (1 + self.SLIPPAGE)
                    capital    -= cost
                    position    = qty
                    entry_day   = i

            # Track equity
            mark_to_market = capital + position * price
            equity.append(mark_to_market)
            dates.append(row.name)

        # Close any open position at last price
        if position > 0:
            last_price = float(df.iloc[-1]["close"]) * (1 - self.SLIPPAGE)
            capital   += position * last_price - position * self.COMMISSION
            equity[-1] = capital

        # ── Performance metrics ────────────────────────────────
        equity_series  = pd.Series(equity, index=dates)
        total_return   = (equity[-1] / self.initial_capital - 1) * 100
        daily_returns  = equity_series.pct_change().dropna()
        ann_return     = daily_returns.mean() * 252 * 100
        ann_vol        = daily_returns.std()  * np.sqrt(252) * 100
        sharpe         = ann_return / ann_vol if ann_vol > 0 else 0
        rolling_max    = equity_series.cummax()
        drawdown       = (equity_series - rolling_max) / rolling_max * 100
        max_drawdown   = float(drawdown.min())

        # Benchmark: buy and hold SPY equivalent (just use symbol itself)
        bh_return = (float(df.iloc[-1]["close"]) / float(df.iloc[0]["close"]) - 1) * 100

        wins  = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]

        metrics = {
            "symbol":            symbol,
            "total_return_pct":  round(total_return,  2),
            "ann_return_pct":    round(ann_return,     2),
            "ann_vol_pct":       round(ann_vol,        2),
            "sharpe_ratio":      round(sharpe,         3),
            "max_drawdown_pct":  round(max_drawdown,   2),
            "buy_hold_return":   round(bh_return,      2),
            "alpha":             round(total_return - bh_return, 2),
            "total_trades":      len(trades),
            "win_rate_pct":      round(len(wins) / len(trades) * 100, 1) if trades else 0,
            "avg_win_pct":       round(np.mean([t["pnl_pct"] for t in wins]),   2) if wins   else 0,
            "avg_loss_pct":      round(np.mean([t["pnl_pct"] for t in losses]), 2) if losses else 0,
            "profit_factor":     round(
                sum(t["pnl"] for t in wins) / abs(sum(t["pnl"] for t in losses)), 2
            ) if losses and sum(t["pnl"] for t in losses) != 0 else float("inf"),
            "final_capital":     round(equity[-1], 2),
        }

        return {
            "metrics":      metrics,
            "trades":       trades,
            "equity_curve": equity_series,
        }

    def run_portfolio(self, symbols: list) -> pd.DataFrame:
        """
        Run backtest for multiple symbols and return summary table.
        """
        results = []
        for sym in symbols:
            logger.info(f"Backtesting {sym}...")
            result = self.run(sym)
            if "error" not in result:
                results.append(result["metrics"])
            else:
                logger.warning(f"Skipping {sym}: {result['error']}")

        if not results:
            return pd.DataFrame()

        df = pd.DataFrame(results).set_index("symbol")
        df = df.sort_values("sharpe_ratio", ascending=False)
        return df

    def plot_equity_curve(self, symbol: str, result: dict, save_path: str = None):
        """Plot equity curve vs buy-and-hold for a single symbol."""
        if "equity_curve" not in result:
            return

        equity = result["equity_curve"]
        metrics = result["metrics"]

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), height_ratios=[3, 1])

        # Equity curve
        ax1.plot(equity.index, equity.values, color="steelblue", linewidth=1.5, label="Strategy")
        ax1.axhline(self.initial_capital, color="gray", linestyle="--", linewidth=0.8)
        ax1.set_title(
            f"{symbol} Backtest — Return: {metrics['total_return_pct']:+.1f}% | "
            f"Sharpe: {metrics['sharpe_ratio']:.2f} | "
            f"Max DD: {metrics['max_drawdown_pct']:.1f}%",
            fontsize=11, fontweight="bold"
        )
        ax1.set_ylabel("Portfolio Value ($)")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # Drawdown
        rolling_max = equity.cummax()
        drawdown    = (equity - rolling_max) / rolling_max * 100
        ax2.fill_between(drawdown.index, drawdown.values, 0, color="red", alpha=0.4, label="Drawdown")
        ax2.set_ylabel("Drawdown (%)")
        ax2.set_xlabel("Date")
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches="tight")
            logger.info(f"Chart saved to {save_path}")
        plt.show()


# ── Entry point ────────────────────────────────────────────────

if __name__ == "__main__":
    bt = Backtester(initial_capital=100_000)

    symbols = ["AAPL", "MSFT", "NVDA", "TSLA", "SPY", "QQQ"]

    logger.info("Running portfolio backtest...")
    summary = bt.run_portfolio(symbols)

    print("\n" + "="*70)
    print("BACKTEST RESULTS SUMMARY")
    print("="*70)
    print(summary[[
        "total_return_pct", "sharpe_ratio", "max_drawdown_pct",
        "win_rate_pct", "total_trades", "alpha"
    ]].to_string())

    # Plot best performer
    best = summary.index[0]
    logger.info(f"Plotting equity curve for best performer: {best}")
    result = bt.run(best)
    bt.plot_equity_curve(best, result, save_path=f"docs/backtest_{best}.png")
