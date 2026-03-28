"""
src/models/monte_carlo.py

Phase 5 — Monte Carlo simulation for strategy robustness testing.

Method: block bootstrap on daily returns from the strategy equity curve.
Block size = 20 days preserves short-term autocorrelation in returns.

Output:
    - 5 percentile equity paths (p5, p25, p50, p75, p95) for fan chart
    - Terminal value statistics (prob of profit, p5/p95 final value)
    - All final values (for histogram rendering in the dashboard)
"""

import numpy as np
import pandas as pd
from loguru import logger

from src.models.metrics_calculator import MetricsCalculator


class MonteCarloSimulator:

    def __init__(
        self,
        n_simulations: int = 1000,
        block_size:    int = 20,
        random_seed:   int = 42,
    ):
        self.n_simulations = n_simulations
        self.block_size    = block_size
        self.rng           = np.random.default_rng(random_seed)

    # ── Core simulation ────────────────────────────────────────────

    def _block_bootstrap(self, returns: np.ndarray, n_days: int) -> np.ndarray:
        """
        Draw n_days of returns by sampling non-overlapping blocks
        with replacement from the empirical return series.
        """
        blocks    = []
        n_blocks  = int(np.ceil(n_days / self.block_size))
        n_blocks_available = max(1, len(returns) - self.block_size + 1)

        starts = self.rng.integers(0, n_blocks_available, size=n_blocks)
        for s in starts:
            blocks.append(returns[s : s + self.block_size])

        sampled = np.concatenate(blocks)[:n_days]
        return sampled

    def _build_equity_path(self, returns: np.ndarray, initial_capital: float) -> np.ndarray:
        """Compound a return series into an equity path."""
        return initial_capital * np.cumprod(1 + returns)

    # ── Main runner ────────────────────────────────────────────────

    def run(
        self,
        equity_series:   pd.Series,
        initial_capital: float = 100_000.0,
        mode:            str   = "bootstrap",
    ) -> dict:
        """
        Run Monte Carlo simulation from a strategy equity curve.

        Args:
            equity_series:   DatetimeIndex → portfolio value (from BacktraderEngine)
            initial_capital: starting portfolio value
            mode:            "bootstrap" (block resample) or "parametric" (normal dist)

        Returns:
            {
              n_simulations, mode,
              dates:       [date_str, ...],
              percentiles: {p5, p25, p50, p75, p95} each a list of floats,
              terminal_stats: {mean/median/p5/p95 final value, prob_profit,
                               prob_loss_20pct, mean_sharpe, std_sharpe},
              all_final_values: [float, ...],   # for histogram
            }
        """
        if equity_series is None or len(equity_series) < 20:
            return self._empty_result()

        daily_returns = equity_series.pct_change().dropna().values
        n_days        = len(daily_returns)
        dates         = [d.strftime("%Y-%m-%d") for d in equity_series.index[1:]]

        logger.info(
            f"Monte Carlo: {self.n_simulations} simulations × {n_days} days "
            f"[mode={mode}]"
        )

        # ── Run simulations ────────────────────────────────────────
        all_paths = np.zeros((self.n_simulations, n_days))

        for i in range(self.n_simulations):
            if mode == "parametric":
                sim_returns = self.rng.normal(
                    loc   = daily_returns.mean(),
                    scale = daily_returns.std(),
                    size  = n_days,
                )
            else:
                sim_returns = self._block_bootstrap(daily_returns, n_days)

            all_paths[i] = self._build_equity_path(sim_returns, initial_capital)

        # ── Percentile paths ───────────────────────────────────────
        pcts = np.percentile(all_paths, [5, 25, 50, 75, 95], axis=0)

        percentiles = {
            "p5":  [round(float(v), 2) for v in pcts[0]],
            "p25": [round(float(v), 2) for v in pcts[1]],
            "p50": [round(float(v), 2) for v in pcts[2]],
            "p75": [round(float(v), 2) for v in pcts[3]],
            "p95": [round(float(v), 2) for v in pcts[4]],
        }

        # ── Terminal statistics ────────────────────────────────────
        final_values = all_paths[:, -1]

        prob_profit     = float(np.mean(final_values > initial_capital))
        prob_loss_20pct = float(np.mean(final_values < initial_capital * 0.80))

        # Sharpe for each simulation path
        sim_sharpes = []
        for i in range(self.n_simulations):
            path_returns = np.diff(all_paths[i]) / all_paths[i][:-1]
            std = path_returns.std()
            if std > 0:
                sim_sharpes.append(float(path_returns.mean() / std * np.sqrt(252)))

        terminal_stats = {
            "mean_final_value":   round(float(np.mean(final_values)),   2),
            "median_final_value": round(float(np.median(final_values)), 2),
            "p5_final_value":     round(float(np.percentile(final_values, 5)),  2),
            "p95_final_value":    round(float(np.percentile(final_values, 95)), 2),
            "prob_profit":        round(prob_profit,     4),
            "prob_loss_20pct":    round(prob_loss_20pct, 4),
            "mean_sharpe":        round(float(np.mean(sim_sharpes)),  3) if sim_sharpes else 0.0,
            "std_sharpe":         round(float(np.std(sim_sharpes)),   3) if sim_sharpes else 0.0,
        }

        logger.info(
            f"Monte Carlo complete: prob_profit={prob_profit:.1%} "
            f"p50_final=${terminal_stats['median_final_value']:,.0f} "
            f"p5_final=${terminal_stats['p5_final_value']:,.0f}"
        )

        return {
            "n_simulations":   self.n_simulations,
            "mode":            mode,
            "dates":           dates,
            "percentiles":     percentiles,
            "terminal_stats":  terminal_stats,
            # Round to 2dp and cap at 1000 values to keep payload manageable
            "all_final_values": [round(float(v), 2) for v in final_values[:1000]],
        }

    @staticmethod
    def _empty_result() -> dict:
        return {
            "n_simulations":   0,
            "mode":            "bootstrap",
            "dates":           [],
            "percentiles":     {"p5": [], "p25": [], "p50": [], "p75": [], "p95": []},
            "terminal_stats":  {
                "mean_final_value": 0, "median_final_value": 0,
                "p5_final_value": 0,  "p95_final_value": 0,
                "prob_profit": 0,     "prob_loss_20pct": 0,
                "mean_sharpe": 0,     "std_sharpe": 0,
            },
            "all_final_values": [],
            "error": "Insufficient equity curve data for simulation",
        }
