"""
src/models/backtest_orchestrator.py

Phase 5 — Master backtest orchestrator.
Single entry point called by the FastAPI backend.

Workflow per symbol:
    1. Load OHLCV from S3
    2. Load SPY as benchmark
    3. BacktraderEngine  → Signal vs MA-Crossover vs Buy-Hold comparison
    4. WalkForwardValidator → proper OOS metrics (5 folds)
    5. MonteCarloSimulator  → 1000-path bootstrap on signal equity curve
    6. Bundle all results, save to S3 (processed bucket), return dict

S3 caching: results are stored per-symbol per-day.
Repeated API calls within the same day are served from cache (<1 second).
"""

import io
import json
import os
from datetime import datetime, timezone

import boto3
import pandas as pd
from loguru import logger
from dotenv import load_dotenv

from src.models.backtrader_engine  import BacktraderEngine
from src.models.walk_forward       import WalkForwardValidator
from src.models.monte_carlo        import MonteCarloSimulator

load_dotenv()


class BacktestOrchestrator:

    S3_RESULT_PREFIX = "backtests/phase5"
    SPY_PREFIX       = "stocks/daily/SPY/"

    def __init__(self, initial_capital: float = 100_000.0):
        self.initial_capital = initial_capital
        self.bt_engine  = BacktraderEngine(initial_capital)
        self.wf_engine  = WalkForwardValidator(initial_capital, n_splits=5)
        self.mc_engine  = MonteCarloSimulator(n_simulations=1000)
        self.s3 = boto3.client(
            "s3",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        )
        self.raw_bucket       = os.getenv("S3_RAW_BUCKET",       "trading-raw-zone")
        self.processed_bucket = os.getenv("S3_PROCESSED_BUCKET", "trading-processed-zone")

    # ── S3 helpers ────────────────────────────────────────────────

    def _load_symbol(self, symbol: str, asset_type: str = "stocks") -> pd.DataFrame:
        """Load most recent daily OHLCV parquet from S3."""
        prefix = f"{asset_type}/daily/{symbol}/"
        try:
            resp = self.s3.list_objects_v2(Bucket=self.raw_bucket, Prefix=prefix)
            keys = sorted([o["Key"] for o in resp.get("Contents", [])])
            if not keys:
                logger.warning(f"No S3 data found for {symbol} at {prefix}")
                return pd.DataFrame()
            obj = self.s3.get_object(Bucket=self.raw_bucket, Key=keys[-1])
            df  = pd.read_parquet(io.BytesIO(obj["Body"].read()))
            df  = df.sort_index()
            logger.info(f"Loaded {symbol}: {len(df)} rows ({df.index[0].date()} → {df.index[-1].date()})")
            return df
        except Exception as e:
            logger.error(f"Failed to load {symbol}: {e}")
            return pd.DataFrame()

    def _save_to_s3(self, symbol: str, result: dict):
        """Save result JSON to S3 processed bucket."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key   = f"{self.S3_RESULT_PREFIX}/{symbol}/{today}.json"
        try:
            body = json.dumps(result, default=str).encode("utf-8")
            self.s3.put_object(
                Bucket      = self.processed_bucket,
                Key         = key,
                Body        = body,
                ContentType = "application/json",
            )
            logger.info(f"Saved backtest result → s3://{self.processed_bucket}/{key}")
        except Exception as e:
            logger.warning(f"S3 save failed for {symbol}: {e}")

    def _load_cached(self, symbol: str) -> dict | None:
        """Return today's cached result if available, else None."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key   = f"{self.S3_RESULT_PREFIX}/{symbol}/{today}.json"
        try:
            obj  = self.s3.get_object(Bucket=self.processed_bucket, Key=key)
            data = json.loads(obj["Body"].read().decode("utf-8"))
            logger.info(f"Cache hit for {symbol} ({today})")
            return data
        except Exception:
            return None

    # ── Per-symbol orchestration ───────────────────────────────────

    def run_symbol(
        self,
        symbol:          str,
        asset_type:      str  = "stocks",
        run_monte_carlo: bool = True,
        use_cache:       bool = True,
    ) -> dict:
        """
        Full Phase 5 backtest pipeline for one symbol.

        Returns serialisable dict:
        {
          symbol, data_range, ran_at,
          strategies: {signal, ma_crossover, buy_hold},
          walk_forward: {...},
          monte_carlo:  {...},
          error: str | None,
        }
        """
        if use_cache:
            cached = self._load_cached(symbol)
            if cached:
                return cached

        logger.info(f"=== Phase 5 Backtest: {symbol} ===")

        # ── Load data ──────────────────────────────────────────────
        df = self._load_symbol(symbol, asset_type)
        if df.empty or len(df) < 252:
            err = f"Insufficient data for {symbol} (need 252+ days, got {len(df)})"
            logger.warning(err)
            return {"symbol": symbol, "error": err}

        # SPY as benchmark for alpha/beta
        spy_df = self._load_symbol("SPY", "stocks")
        benchmark_df = spy_df if not spy_df.empty else None

        # ── Strategy comparison ────────────────────────────────────
        logger.info(f"Running strategy comparison for {symbol}...")
        strategies_result = self.bt_engine.run(
            symbol       = symbol,
            df           = df,
            strategies   = ["signal", "ma_crossover", "buy_hold"],
            benchmark_df = benchmark_df,
        )

        # ── Walk-forward validation ────────────────────────────────
        logger.info(f"Running walk-forward validation for {symbol}...")
        wf_result = self.wf_engine.run(
            symbol       = symbol,
            df           = df,
            strategy     = "signal",
            benchmark_df = benchmark_df,
        )

        # ── Monte Carlo simulation ─────────────────────────────────
        mc_result = {}
        if run_monte_carlo:
            logger.info(f"Running Monte Carlo simulation for {symbol}...")
            signal_equity = strategies_result.get("signal", {}).get("equity_curve", [])
            if signal_equity:
                # Reconstruct Series from serialised equity curve
                equity_series = pd.Series(
                    [p["value"] for p in signal_equity],
                    index=pd.DatetimeIndex([p["date"] for p in signal_equity]),
                )
                mc_result = self.mc_engine.run(
                    equity_series   = equity_series,
                    initial_capital = self.initial_capital,
                )
            else:
                mc_result = MonteCarloSimulator._empty_result()

        # ── Bundle result ──────────────────────────────────────────
        result = {
            "symbol":       symbol,
            "data_range": {
                "start":  str(df.index[0].date()),
                "end":    str(df.index[-1].date()),
                "n_days": len(df),
            },
            "ran_at":       datetime.now(timezone.utc).isoformat(),
            "initial_capital": self.initial_capital,
            "strategies":   strategies_result,
            "walk_forward": wf_result,
            "monte_carlo":  mc_result,
            "error":        None,
        }

        self._save_to_s3(symbol, result)
        logger.info(f"=== Phase 5 complete: {symbol} ===")
        return result

    # ── Portfolio runner ──────────────────────────────────────────

    def run_portfolio(
        self,
        symbols:         list,
        asset_types:     dict = None,
        run_monte_carlo: bool = True,
        use_cache:       bool = True,
    ) -> dict:
        """
        Run Phase 5 backtest for a list of symbols.

        Args:
            symbols:      list of ticker strings
            asset_types:  dict mapping symbol → "stocks" | "crypto" (defaults to stocks)
            run_monte_carlo: whether to run MC simulation per symbol
            use_cache:    serve today's cached S3 result if available

        Returns:
            {
              count, initial_capital, ran_at,
              summary: [flat metric row per symbol],
              details: {symbol: full_result_dict},
            }
        """
        asset_types = asset_types or {}
        details  = {}
        summary  = []

        for sym in symbols:
            atype = asset_types.get(sym, "stocks")
            try:
                result = self.run_symbol(
                    symbol          = sym,
                    asset_type      = atype,
                    run_monte_carlo = run_monte_carlo,
                    use_cache       = use_cache,
                )
                details[sym] = result

                if result.get("error"):
                    summary.append({"symbol": sym, "error": result["error"]})
                    continue

                # Build flat summary row for the comparison table
                sig = result["strategies"].get("signal",       {}).get("metrics", {})
                mac = result["strategies"].get("ma_crossover", {}).get("metrics", {})
                bnh = result["strategies"].get("buy_hold",     {}).get("metrics", {})
                wf  = result["walk_forward"].get("aggregated_metrics", {})
                mc  = result["monte_carlo"].get("terminal_stats", {})

                summary.append({
                    "symbol":              sym,
                    # Signal strategy metrics
                    "sig_return_pct":      sig.get("total_return_pct",  0),
                    "sig_ann_return_pct":  sig.get("ann_return_pct",    0),
                    "sig_sharpe":          sig.get("sharpe_ratio",      0),
                    "sig_sortino":         sig.get("sortino_ratio",     0),
                    "sig_calmar":          sig.get("calmar_ratio",      0),
                    "sig_max_dd":          sig.get("max_drawdown_pct",  0),
                    "sig_alpha":           sig.get("alpha_pct",         0),
                    "sig_beta":            sig.get("beta",              0),
                    "sig_var_95":          sig.get("var_95_pct",        0),
                    "sig_cvar_95":         sig.get("cvar_95_pct",       0),
                    "sig_win_rate":        sig.get("win_rate_pct",      0),
                    "sig_profit_factor":   sig.get("profit_factor",     0),
                    "sig_trades":          sig.get("total_trades",      0),
                    # MA Crossover metrics
                    "mac_return_pct":      mac.get("total_return_pct",  0),
                    "mac_sharpe":          mac.get("sharpe_ratio",      0),
                    "mac_max_dd":          mac.get("max_drawdown_pct",  0),
                    "mac_win_rate":        mac.get("win_rate_pct",      0),
                    "mac_trades":          mac.get("total_trades",      0),
                    # Buy-and-hold benchmark
                    "bnh_return_pct":      bnh.get("total_return_pct",  0),
                    # Walk-forward OOS
                    "wf_sharpe_mean":      wf.get("sharpe_ratio_mean",  0),
                    "wf_sharpe_std":       wf.get("sharpe_ratio_std",   0),
                    "wf_return_mean":      wf.get("total_return_pct_mean", 0),
                    "wf_n_splits":         result["walk_forward"].get("n_splits", 0),
                    # Monte Carlo
                    "mc_prob_profit":      mc.get("prob_profit",        0),
                    "mc_prob_loss_20":     mc.get("prob_loss_20pct",    0),
                    "mc_p5_final":         mc.get("p5_final_value",     0),
                    "mc_p95_final":        mc.get("p95_final_value",    0),
                    "mc_mean_sharpe":      mc.get("mean_sharpe",        0),
                })

            except Exception as e:
                logger.error(f"Orchestrator failed for {sym}: {e}")
                details[sym] = {"symbol": sym, "error": str(e)}
                summary.append({"symbol": sym, "error": str(e)})

        return {
            "count":           len(summary),
            "initial_capital": self.initial_capital,
            "ran_at":          datetime.now(timezone.utc).isoformat(),
            "summary":         summary,
            "details":         details,
        }


# ── Entry point ────────────────────────────────────────────────────

if __name__ == "__main__":
    orch = BacktestOrchestrator(initial_capital=100_000)
    result = orch.run_portfolio(
        symbols         = ["AAPL", "MSFT", "NVDA", "TSLA", "SPY"],
        run_monte_carlo = True,
        use_cache       = False,
    )

    print("\n" + "=" * 70)
    print("PHASE 5 BACKTEST SUMMARY")
    print("=" * 70)
    for row in result["summary"]:
        if row.get("error"):
            print(f"  {row['symbol']:10s}  ERROR: {row['error']}")
        else:
            print(
                f"  {row['symbol']:10s} | "
                f"Signal: {row['sig_return_pct']:+6.1f}% Sharpe={row['sig_sharpe']:.2f} | "
                f"MA-X: {row['mac_return_pct']:+6.1f}% | "
                f"B&H: {row['bnh_return_pct']:+6.1f}% | "
                f"WF Sharpe={row['wf_sharpe_mean']:.2f}±{row['wf_sharpe_std']:.2f} | "
                f"MC prob={row['mc_prob_profit']:.0%}"
            )
