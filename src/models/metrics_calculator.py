"""
src/models/metrics_calculator.py

Phase 5 — Comprehensive performance metrics calculator.
Stateless utility class — all methods are static.
Used by BacktraderEngine, WalkForwardValidator, and MonteCarloSimulator.

Metrics computed:
    Sharpe, Sortino, Calmar, Alpha (Jensen's), Beta,
    VaR 95%, CVaR 95%, Max Drawdown, Profit Factor,
    Win Rate, Avg Win/Loss, Total Return, Annualised Return/Vol.
"""

import numpy as np
import pandas as pd
from loguru import logger


class MetricsCalculator:

    TRADING_DAYS = 252

    @staticmethod
    def compute_all(
        equity_series: pd.Series,
        trades: list,
        benchmark_returns: pd.Series = None,
        initial_capital: float = 100_000.0,
        risk_free_rate: float = 0.05,
    ) -> dict:
        """
        Master method — compute every Phase 5 metric in one call.

        Args:
            equity_series:     DatetimeIndex → portfolio value
            trades:            list of trade dicts with 'pnl' and 'pnl_pct' keys
            benchmark_returns: daily returns of benchmark (e.g. SPY). Optional.
            initial_capital:   starting capital
            risk_free_rate:    annual risk-free rate (default 5%)

        Returns:
            dict of all metrics, all floats rounded to 4 dp
        """
        if equity_series is None or len(equity_series) < 2:
            return MetricsCalculator._empty_metrics()

        T   = MetricsCalculator.TRADING_DAYS
        rfr = risk_free_rate / T   # daily risk-free rate

        daily_returns = MetricsCalculator._daily_returns(equity_series)
        if daily_returns.empty:
            return MetricsCalculator._empty_metrics()

        ann_return = float(daily_returns.mean() * T * 100)
        ann_vol    = float(daily_returns.std()  * np.sqrt(T) * 100)
        total_ret  = float((equity_series.iloc[-1] / initial_capital - 1) * 100)

        sharpe  = MetricsCalculator._sharpe(daily_returns,  rfr)
        sortino = MetricsCalculator._sortino(daily_returns, rfr)
        max_dd  = MetricsCalculator._max_drawdown(equity_series)
        calmar  = MetricsCalculator._calmar(ann_return, max_dd)

        # Benchmark-dependent metrics
        beta  = 0.0
        alpha = 0.0
        if benchmark_returns is not None and len(benchmark_returns) > 10:
            bench = benchmark_returns.reindex(daily_returns.index).dropna()
            strat = daily_returns.reindex(bench.index).dropna()
            if len(bench) > 10:
                beta        = MetricsCalculator._beta(strat, bench)
                bench_ann   = float(bench.mean() * T * 100)
                alpha       = MetricsCalculator._alpha(ann_return, beta, bench_ann, risk_free_rate * 100)

        var_95  = MetricsCalculator._var(daily_returns,  0.95)
        cvar_95 = MetricsCalculator._cvar(daily_returns, 0.95)

        # Trade stats
        win_rate      = MetricsCalculator._win_rate(trades)
        profit_factor = MetricsCalculator._profit_factor(trades)
        avg_win, avg_loss = MetricsCalculator._avg_win_loss(trades)

        def r(v, d=4):
            try:
                return round(float(v), d)
            except Exception:
                return 0.0

        return {
            "total_return_pct":  r(total_ret,  2),
            "ann_return_pct":    r(ann_return,  2),
            "ann_vol_pct":       r(ann_vol,     2),
            "sharpe_ratio":      r(sharpe,      3),
            "sortino_ratio":     r(sortino,     3),
            "calmar_ratio":      r(calmar,      3),
            "max_drawdown_pct":  r(max_dd,      2),
            "alpha_pct":         r(alpha,       3),
            "beta":              r(beta,        3),
            "var_95_pct":        r(var_95,      3),
            "cvar_95_pct":       r(cvar_95,     3),
            "win_rate_pct":      r(win_rate,    2),
            "profit_factor":     r(profit_factor, 3),
            "avg_win_pct":       r(avg_win,     3),
            "avg_loss_pct":      r(avg_loss,    3),
            "total_trades":      len(trades),
            "final_capital":     r(equity_series.iloc[-1], 2),
        }

    # ── Private helpers ────────────────────────────────────────────

    @staticmethod
    def _daily_returns(equity: pd.Series) -> pd.Series:
        return equity.pct_change().dropna()

    @staticmethod
    def _sharpe(daily_returns: pd.Series, rfr_daily: float) -> float:
        excess = daily_returns - rfr_daily
        std    = excess.std()
        if std == 0:
            return 0.0
        return float(excess.mean() / std * np.sqrt(MetricsCalculator.TRADING_DAYS))

    @staticmethod
    def _sortino(daily_returns: pd.Series, rfr_daily: float) -> float:
        """Uses only downside deviation in denominator."""
        excess    = daily_returns - rfr_daily
        downside  = excess[excess < 0]
        if len(downside) == 0:
            return float("inf")
        downside_std = downside.std()
        if downside_std == 0:
            return 0.0
        return float(excess.mean() / downside_std * np.sqrt(MetricsCalculator.TRADING_DAYS))

    @staticmethod
    def _calmar(ann_return_pct: float, max_drawdown_pct: float) -> float:
        """Calmar = annualised return / abs(max drawdown)."""
        if max_drawdown_pct == 0:
            return 0.0
        return float(ann_return_pct / abs(max_drawdown_pct))

    @staticmethod
    def _max_drawdown(equity: pd.Series) -> float:
        """Returns max drawdown as a negative percentage."""
        rolling_max = equity.cummax()
        drawdown    = (equity - rolling_max) / rolling_max * 100
        return float(drawdown.min())

    @staticmethod
    def _beta(strategy_returns: pd.Series, benchmark_returns: pd.Series) -> float:
        """Covariance(strategy, benchmark) / Variance(benchmark)."""
        bench_var = benchmark_returns.var()
        if bench_var == 0:
            return 0.0
        cov = np.cov(strategy_returns, benchmark_returns)[0][1]
        return float(cov / bench_var)

    @staticmethod
    def _alpha(
        ann_strategy_pct: float,
        beta: float,
        ann_benchmark_pct: float,
        risk_free_pct: float,
    ) -> float:
        """Jensen's alpha: R_s - [Rf + beta*(R_b - Rf)]."""
        return float(ann_strategy_pct - (risk_free_pct + beta * (ann_benchmark_pct - risk_free_pct)))

    @staticmethod
    def _var(daily_returns: pd.Series, confidence: float = 0.95) -> float:
        """Historical VaR — returned as positive percentage loss."""
        if len(daily_returns) < 20:
            return 0.0
        return float(abs(np.percentile(daily_returns * 100, (1 - confidence) * 100)))

    @staticmethod
    def _cvar(daily_returns: pd.Series, confidence: float = 0.95) -> float:
        """Expected Shortfall — mean of returns below VaR threshold."""
        if len(daily_returns) < 20:
            return 0.0
        threshold = np.percentile(daily_returns, (1 - confidence) * 100)
        tail      = daily_returns[daily_returns <= threshold]
        if tail.empty:
            return 0.0
        return float(abs(tail.mean() * 100))

    @staticmethod
    def _win_rate(trades: list) -> float:
        if not trades:
            return 0.0
        wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
        return float(wins / len(trades) * 100)

    @staticmethod
    def _profit_factor(trades: list) -> float:
        gross_win  = sum(t.get("pnl", 0) for t in trades if t.get("pnl", 0) > 0)
        gross_loss = sum(abs(t.get("pnl", 0)) for t in trades if t.get("pnl", 0) <= 0)
        if gross_loss == 0:
            return float("inf") if gross_win > 0 else 0.0
        return float(gross_win / gross_loss)

    @staticmethod
    def _avg_win_loss(trades: list) -> tuple:
        wins   = [t.get("pnl_pct", 0) for t in trades if t.get("pnl", 0) > 0]
        losses = [t.get("pnl_pct", 0) for t in trades if t.get("pnl", 0) <= 0]
        avg_win  = float(np.mean(wins))   if wins   else 0.0
        avg_loss = float(np.mean(losses)) if losses else 0.0
        return avg_win, avg_loss

    @staticmethod
    def _empty_metrics() -> dict:
        keys = [
            "total_return_pct", "ann_return_pct", "ann_vol_pct",
            "sharpe_ratio", "sortino_ratio", "calmar_ratio",
            "max_drawdown_pct", "alpha_pct", "beta",
            "var_95_pct", "cvar_95_pct",
            "win_rate_pct", "profit_factor", "avg_win_pct", "avg_loss_pct",
            "total_trades", "final_capital",
        ]
        return {k: 0 for k in keys}
