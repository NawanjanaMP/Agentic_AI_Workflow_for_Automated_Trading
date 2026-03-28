"""
src/models/backtrader_engine.py

Phase 5 — Backtrader-based strategy engine.

Strategies:
    SignalStrategy     — mirrors the Phase 4 signal scoring (SMA/RSI/MACD/BB/ATR)
    MACrossoverStrategy — classic SMA-50/200 golden-cross / death-cross
    BuyHoldStrategy    — benchmark: buy on day 1, hold to end

numpy 1.24+ removed np.bool/np.float/np.int — apply compatibility shim before
importing backtrader to avoid AttributeError.
"""

import numpy as np

# ── Backtrader numpy compatibility shim ───────────────────────────
np.bool    = bool
np.float   = float
np.int     = int
np.complex = complex
np.object  = object
np.str     = str
# ─────────────────────────────────────────────────────────────────

import backtrader as bt
import pandas as pd
from datetime import datetime
from loguru import logger

from src.models.metrics_calculator import MetricsCalculator


# ══════════════════════════════════════════════════════════════════
#  Strategy A — Signal-based (Phase 4 logic in Backtrader form)
# ══════════════════════════════════════════════════════════════════

class SignalStrategy(bt.Strategy):
    """
    BUY when signal score >= +2, SELL/EXIT when score <= -2.
    Indicators: SMA20/50/200, RSI14, MACD, Bollinger Bands.
    Position sizing: risk 2% of portfolio per trade via ATR stop.
    """

    params = (
        ("score_buy",     2),
        ("score_sell",   -2),
        ("max_hold_days", 20),
        ("risk_pct",      0.02),
        ("atr_period",    14),
        ("atr_mult",      2.0),
    )

    def __init__(self):
        self.sma20  = bt.indicators.SMA(self.data.close, period=20)
        self.sma50  = bt.indicators.SMA(self.data.close, period=50)
        self.sma200 = bt.indicators.SMA(self.data.close, period=200)
        self.rsi    = bt.indicators.RSI(self.data.close, period=14)
        self.macd   = bt.indicators.MACD(self.data.close)
        self.bb     = bt.indicators.BollingerBands(self.data.close, period=20, devfactor=2)
        self.atr    = bt.indicators.ATR(self.data, period=self.p.atr_period)

        self.trade_log  = []
        self.entry_bar  = 0
        self.order      = None

    def _signal_score(self):
        score = 0
        if self.sma50[0] > self.sma200[0]:  score += 1
        else:                                score -= 1
        if self.data.close[0] > self.sma20[0]: score += 1
        else:                                   score -= 1
        if self.rsi[0] < 30:   score += 1
        elif self.rsi[0] > 70: score -= 1
        if self.macd.macd[0] > self.macd.signal[0]: score += 1
        else:                                         score -= 1
        bb_pct = (self.data.close[0] - self.bb.bot[0]) / (self.bb.top[0] - self.bb.bot[0] + 1e-9)
        if bb_pct < 0.2:   score += 1
        elif bb_pct > 0.8: score -= 1
        return score

    def next(self):
        if self.order:
            return

        score = self._signal_score()

        if not self.position:
            if score >= self.p.score_buy:
                atr       = max(self.atr[0], self.data.close[0] * 0.01)
                stop_dist = atr * self.p.atr_mult
                risk_amt  = self.broker.getvalue() * self.p.risk_pct
                qty       = int(risk_amt / stop_dist)
                if qty > 0:
                    self.order    = self.buy(size=qty)
                    self.entry_bar = len(self)
        else:
            days_held = len(self) - self.entry_bar
            if score <= self.p.score_sell or days_held >= self.p.max_hold_days:
                self.order = self.close()

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin]:
            self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.trade_log.append({
                "entry_date":  bt.num2date(trade.dtopen).strftime("%Y-%m-%d"),
                "exit_date":   bt.num2date(trade.dtclose).strftime("%Y-%m-%d"),
                "entry_price": round(trade.price, 4),
                "exit_price":  round(trade.price + trade.pnl / (trade.size or 1), 4),
                "qty":         int(abs(trade.size)),
                "pnl":         round(trade.pnl, 2),
                "pnl_pct":     round(trade.pnlcomm / max(abs(trade.price * trade.size), 1) * 100, 3),
                "days_held":   (bt.num2date(trade.dtclose) - bt.num2date(trade.dtopen)).days,
            })


# ══════════════════════════════════════════════════════════════════
#  Strategy B — MA Crossover
# ══════════════════════════════════════════════════════════════════

class MACrossoverStrategy(bt.Strategy):
    """
    Golden cross (SMA50 > SMA200) → BUY.
    Death cross (SMA50 < SMA200) → EXIT.
    """

    params = (
        ("fast_period", 50),
        ("slow_period", 200),
        ("risk_pct",    0.02),
        ("atr_period",  14),
        ("atr_mult",    2.0),
    )

    def __init__(self):
        self.fast = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.slow = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.atr  = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.cross = bt.indicators.CrossOver(self.fast, self.slow)

        self.trade_log = []
        self.order     = None

    def next(self):
        if self.order:
            return

        if not self.position:
            if self.cross[0] > 0:   # golden cross
                atr      = max(self.atr[0], self.data.close[0] * 0.01)
                risk_amt = self.broker.getvalue() * self.p.risk_pct
                qty      = int(risk_amt / (atr * self.p.atr_mult))
                if qty > 0:
                    self.order = self.buy(size=qty)
        else:
            if self.cross[0] < 0:   # death cross
                self.order = self.close()

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin]:
            self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.trade_log.append({
                "entry_date":  bt.num2date(trade.dtopen).strftime("%Y-%m-%d"),
                "exit_date":   bt.num2date(trade.dtclose).strftime("%Y-%m-%d"),
                "entry_price": round(trade.price, 4),
                "exit_price":  round(trade.price + trade.pnl / (trade.size or 1), 4),
                "qty":         int(abs(trade.size)),
                "pnl":         round(trade.pnl, 2),
                "pnl_pct":     round(trade.pnlcomm / max(abs(trade.price * trade.size), 1) * 100, 3),
                "days_held":   (bt.num2date(trade.dtclose) - bt.num2date(trade.dtopen)).days,
            })


# ══════════════════════════════════════════════════════════════════
#  Strategy C — Buy & Hold (benchmark)
# ══════════════════════════════════════════════════════════════════

class BuyHoldStrategy(bt.Strategy):
    """Buy all available shares on day 1, hold until the end."""

    def __init__(self):
        self.trade_log = []
        self.bought    = False
        self.order     = None

    def next(self):
        if not self.bought and not self.order:
            size = int(self.broker.getvalue() / self.data.close[0])
            if size > 0:
                self.order  = self.buy(size=size)
                self.bought = True

    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin]:
            self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.trade_log.append({
                "entry_date":  bt.num2date(trade.dtopen).strftime("%Y-%m-%d"),
                "exit_date":   bt.num2date(trade.dtclose).strftime("%Y-%m-%d"),
                "entry_price": round(trade.price, 4),
                "exit_price":  round(trade.price + trade.pnl / (trade.size or 1), 4),
                "qty":         int(abs(trade.size)),
                "pnl":         round(trade.pnl, 2),
                "pnl_pct":     round(trade.pnlcomm / max(abs(trade.price * trade.size), 1) * 100, 3),
                "days_held":   (bt.num2date(trade.dtclose) - bt.num2date(trade.dtopen)).days,
            })


# ══════════════════════════════════════════════════════════════════
#  Backtrader Engine — runs strategies and returns metrics
# ══════════════════════════════════════════════════════════════════

class BacktraderEngine:
    """
    Wraps Backtrader cerebro to run one or more strategies on a symbol
    and return standardised metric + equity-curve dicts.

    Usage:
        engine = BacktraderEngine(initial_capital=100_000)
        results = engine.run(symbol, df, benchmark_df=spy_df)
    """

    SLIPPAGE   = 0.001   # 0.1% per side
    COMMISSION = 0.001   # 0.1% per trade

    STRATEGY_MAP = {
        "signal":      SignalStrategy,
        "ma_crossover": MACrossoverStrategy,
        "buy_hold":    BuyHoldStrategy,
    }

    def __init__(self, initial_capital: float = 100_000.0):
        self.initial_capital = initial_capital

    def _df_to_feed(self, df: pd.DataFrame) -> bt.feeds.PandasData:
        """Convert OHLCV DataFrame to bt PandasData feed."""
        d = df.copy()
        d.index = pd.to_datetime(d.index)
        if d.index.tzinfo is not None:
            d.index = d.index.tz_localize(None)
        d.columns = [c.lower() for c in d.columns]
        # Backtrader requires: open, high, low, close, volume, openinterest
        if "openinterest" not in d.columns:
            d["openinterest"] = 0
        return bt.feeds.PandasData(dataname=d)

    def _run_single(
        self,
        strategy_name: str,
        df: pd.DataFrame,
        benchmark_returns: pd.Series = None,
    ) -> dict:
        """Spin up one cerebro instance, run strategy, extract results."""
        strategy_class = self.STRATEGY_MAP[strategy_name]

        cerebro = bt.Cerebro(stdstats=False)
        cerebro.adddata(self._df_to_feed(df))
        cerebro.addstrategy(strategy_class)
        cerebro.broker.setcash(self.initial_capital)
        cerebro.broker.setcommission(commission=self.COMMISSION)
        cerebro.broker.set_slippage_perc(self.SLIPPAGE)
        cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="time_return")

        try:
            results = cerebro.run()
        except Exception as e:
            logger.error(f"Backtrader run failed [{strategy_name}]: {e}")
            return {"error": str(e)}

        strat       = results[0]
        trade_log   = strat.trade_log
        time_return = strat.analyzers.time_return.get_analysis()

        # Build equity series from TimeReturn analyser
        if time_return:
            dates  = list(time_return.keys())
            ret_series = pd.Series(list(time_return.values()), index=pd.DatetimeIndex(dates))
            equity = (1 + ret_series).cumprod() * self.initial_capital
        else:
            equity = pd.Series([self.initial_capital], index=[df.index[0]])

        metrics = MetricsCalculator.compute_all(
            equity_series     = equity,
            trades            = trade_log,
            benchmark_returns = benchmark_returns,
            initial_capital   = self.initial_capital,
        )

        # Serialisable equity curve: list of [date_str, value]
        equity_curve = [
            {"date": d.strftime("%Y-%m-%d"), "value": round(float(v), 2)}
            for d, v in equity.items()
        ]

        logger.info(
            f"  [{strategy_name}] return={metrics['total_return_pct']:+.1f}% "
            f"sharpe={metrics['sharpe_ratio']:.2f} trades={len(trade_log)}"
        )

        return {
            "metrics":      metrics,
            "trades":       trade_log,
            "equity_curve": equity_curve,
        }

    def run(
        self,
        symbol: str,
        df: pd.DataFrame,
        strategies: list = None,
        benchmark_df: pd.DataFrame = None,
    ) -> dict:
        """
        Run all strategies for one symbol.

        Returns:
            {
              "signal":       {metrics, trades, equity_curve},
              "ma_crossover": {metrics, trades, equity_curve},
              "buy_hold":     {metrics, trades, equity_curve},
            }
        """
        if strategies is None:
            strategies = ["signal", "ma_crossover", "buy_hold"]

        # Compute benchmark daily returns for alpha/beta
        benchmark_returns = None
        if benchmark_df is not None and not benchmark_df.empty:
            benchmark_returns = benchmark_df["close"].pct_change().dropna()

        logger.info(f"BacktraderEngine: running {len(strategies)} strategies for {symbol}")

        output = {}
        for name in strategies:
            if name not in self.STRATEGY_MAP:
                logger.warning(f"Unknown strategy '{name}' — skipping")
                continue
            output[name] = self._run_single(name, df, benchmark_returns)

        return output
