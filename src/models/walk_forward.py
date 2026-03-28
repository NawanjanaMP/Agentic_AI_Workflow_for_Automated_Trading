"""
src/models/walk_forward.py

Phase 5 — Walk-forward validation engine.
Splits historical data into in-sample (train) / out-of-sample (test) folds
to measure strategy robustness without look-ahead bias.

Split method: expanding window
    Fold 1: train[0:T1]        | test[T1:T1+W]
    Fold 2: train[0:T2]        | test[T2:T2+W]
    ...
    Fold N: train[0:TN]        | test[TN:TN+W]

Minimum requirements:
    - 252 trading days per train window
    - 63 trading days per test window  (~1 quarter)
    - If data is insufficient for n_splits, automatically reduces to fit
"""

import numpy as np
import pandas as pd
from loguru import logger

from src.models.backtrader_engine  import BacktraderEngine
from src.models.metrics_calculator import MetricsCalculator


class WalkForwardValidator:

    MIN_TRAIN_DAYS = 252   # 1 year minimum train window
    MIN_TEST_DAYS  = 63    # ~1 quarter minimum test window

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        n_splits: int = 5,
        train_pct: float = 0.70,
    ):
        self.initial_capital = initial_capital
        self.n_splits        = n_splits
        self.train_pct       = train_pct
        self.bt_engine       = BacktraderEngine(initial_capital)

    # ── Fold generation ────────────────────────────────────────────

    def _make_folds(self, df: pd.DataFrame) -> list:
        """
        Build (train_df, test_df) expanding-window folds.
        Automatically reduces n_splits if data is insufficient.
        """
        n = len(df)
        min_required = self.MIN_TRAIN_DAYS + self.MIN_TEST_DAYS

        if n < min_required:
            logger.warning(f"Insufficient data ({n} days) for walk-forward — need {min_required}")
            return []

        # How many splits can we actually support?
        max_splits = max(1, (n - self.MIN_TRAIN_DAYS) // self.MIN_TEST_DAYS)
        n_splits   = min(self.n_splits, max_splits)
        if n_splits < self.n_splits:
            logger.warning(f"Reduced walk-forward splits: {self.n_splits} → {n_splits} (data={n} days)")

        # Expanding window: test window slides forward each fold
        test_size  = (n - self.MIN_TRAIN_DAYS) // n_splits
        test_size  = max(test_size, self.MIN_TEST_DAYS)

        folds = []
        for i in range(n_splits):
            train_end = self.MIN_TRAIN_DAYS + i * test_size
            test_end  = min(train_end + test_size, n)

            if test_end <= train_end:
                break

            train_df = df.iloc[:train_end].copy()
            test_df  = df.iloc[train_end:test_end].copy()

            if len(train_df) < self.MIN_TRAIN_DAYS or len(test_df) < self.MIN_TEST_DAYS // 2:
                continue

            folds.append((train_df, test_df))

        logger.info(f"Walk-forward: {len(folds)} folds created from {n} trading days")
        return folds

    # ── Fold metric aggregation ─────────────────────────────────────

    def _aggregate(self, fold_metrics: list) -> dict:
        """Compute mean ± std across folds for every numeric metric."""
        if not fold_metrics:
            return {}

        keys = [k for k in fold_metrics[0] if isinstance(fold_metrics[0][k], (int, float))]
        result = {}
        for k in keys:
            vals = [m[k] for m in fold_metrics if isinstance(m.get(k), (int, float))]
            result[f"{k}_mean"] = round(float(np.mean(vals)), 4) if vals else 0.0
            result[f"{k}_std"]  = round(float(np.std(vals)),  4) if vals else 0.0
        return result

    # ── Main runner ────────────────────────────────────────────────

    def run(
        self,
        symbol: str,
        df: pd.DataFrame,
        strategy: str = "signal",
        benchmark_df: pd.DataFrame = None,
    ) -> dict:
        """
        Run walk-forward validation for one symbol.

        Returns:
            {
              symbol, n_splits, strategy,
              folds: [{fold_id, train_start, train_end, test_start, test_end,
                       oos_metrics, oos_trades, oos_equity}],
              aggregated_metrics: {sharpe_ratio_mean, sharpe_ratio_std, ...},
              combined_equity:    [{date, value}],   # stitched OOS equity
            }
        """
        logger.info(f"Walk-forward [{strategy}] for {symbol}")
        folds = self._make_folds(df)

        if not folds:
            return {
                "symbol":              symbol,
                "strategy":            strategy,
                "n_splits":            0,
                "folds":               [],
                "aggregated_metrics":  {},
                "combined_equity":     [],
                "error":               "Insufficient data for walk-forward validation",
            }

        benchmark_returns = None
        if benchmark_df is not None and not benchmark_df.empty:
            benchmark_returns = benchmark_df["close"].pct_change().dropna()

        fold_results  = []
        fold_metrics  = []
        all_oos_equity = []   # for stitching

        for i, (train_df, test_df) in enumerate(folds):
            logger.info(
                f"  Fold {i+1}/{len(folds)}: "
                f"train={train_df.index[0].date()}→{train_df.index[-1].date()} "
                f"({len(train_df)}d) | "
                f"test={test_df.index[0].date()}→{test_df.index[-1].date()} "
                f"({len(test_df)}d)"
            )

            # Run strategy on out-of-sample window only
            # (In full WF: train window is used to optimise params;
            #  for this coursework we use fixed params from Phase 4)
            try:
                result = self.bt_engine.run(
                    symbol       = symbol,
                    df           = test_df,
                    strategies   = [strategy],
                    benchmark_df = benchmark_df,
                )
                oos = result.get(strategy, {})
            except Exception as e:
                logger.error(f"  Fold {i+1} failed: {e}")
                oos = {"error": str(e)}

            oos_metrics = oos.get("metrics", MetricsCalculator._empty_metrics())
            oos_trades  = oos.get("trades",  [])
            oos_equity  = oos.get("equity_curve", [])

            fold_metrics.append(oos_metrics)
            all_oos_equity.extend(oos_equity)

            fold_results.append({
                "fold_id":    i + 1,
                "train_start": str(train_df.index[0].date()),
                "train_end":   str(train_df.index[-1].date()),
                "test_start":  str(test_df.index[0].date()),
                "test_end":    str(test_df.index[-1].date()),
                "train_days":  len(train_df),
                "test_days":   len(test_df),
                "oos_metrics": oos_metrics,
                "oos_trades":  oos_trades,
                "oos_equity":  oos_equity,
                "error":       oos.get("error"),
            })

        aggregated = self._aggregate(fold_metrics)

        logger.info(
            f"Walk-forward [{strategy}] {symbol} complete: "
            f"Sharpe mean={aggregated.get('sharpe_ratio_mean', 0):.2f} "
            f"± {aggregated.get('sharpe_ratio_std', 0):.2f}"
        )

        return {
            "symbol":             symbol,
            "strategy":           strategy,
            "n_splits":           len(fold_results),
            "folds":              fold_results,
            "aggregated_metrics": aggregated,
            "combined_equity":    all_oos_equity,
        }
