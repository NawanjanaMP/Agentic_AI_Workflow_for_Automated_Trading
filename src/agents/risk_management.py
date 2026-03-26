"""
src/agents/risk_management.py

Risk Management Module — validates agent decisions before execution.
Acts as a hard veto gate: if a decision breaches any risk rule,
it is blocked regardless of what the LLM decided.
"""

import numpy as np
import pandas as pd
from loguru import logger
from dataclasses import dataclass


@dataclass
class RiskConfig:
    """
    Risk parameters — tune these to match your risk tolerance.
    Conservative defaults suit a coursework/demo portfolio.
    """
    max_position_pct:    float = 0.05    # Max 5% of portfolio per position
    max_sector_pct:      float = 0.25    # Max 25% in any single sector
    max_daily_drawdown:  float = 0.05    # Stop trading if portfolio drops 5% in a day
    max_total_drawdown:  float = 0.15    # Stop trading if portfolio drops 15% total
    min_rsi_for_buy:     float = 20.0    # Don't buy if RSI below 20 (extreme crash)
    max_rsi_for_sell:    float = 85.0    # Don't short if RSI above 85 (extreme squeeze)
    max_atr_multiplier:  float = 3.0     # Skip if ATR > 3× its 20-day average (wild volatility)
    var_confidence:      float = 0.99    # VaR confidence level
    var_limit_pct:       float = 0.03    # Max 3% 1-day VaR


class RiskManagementModule:
    """
    Evaluates every agent decision against defined risk rules.

    The module can:
    1. APPROVE  — decision passes all risk checks
    2. MODIFY   — reduce position size to fit within limits
    3. VETO     — block the decision entirely

    Every decision and its risk assessment is logged.
    """

    def __init__(self, config: RiskConfig = None):
        self.config           = config or RiskConfig()
        self.portfolio_value  = 100_000.0    # Starting capital ($100k demo)
        self.positions        = {}           # {symbol: {"qty": N, "avg_price": P}}
        self.daily_pnl        = 0.0
        self.peak_value       = self.portfolio_value
        self.decision_log     = []

    # ── Position sizing ────────────────────────────────────────

    def calculate_position_size(
        self,
        symbol:       str,
        price:        float,
        atr:          float,
        signal_score: int,
    ) -> dict:
        """
        Calculate safe position size using ATR-based risk sizing.

        Kelly-inspired formula:
        - Risk 1% of portfolio per trade
        - Stop loss = 2 × ATR below entry
        - Position size = (portfolio × risk%) / (2 × ATR)

        Args:
            symbol:       Ticker
            price:        Current price
            atr:          Average True Range (volatility measure)
            signal_score: Confidence proxy (-5 to +5)

        Returns:
            Dict with recommended_qty, max_qty, stop_loss, risk_pct
        """
        max_position_value = self.portfolio_value * self.config.max_position_pct
        max_qty_by_capital = int(max_position_value / price) if price > 0 else 0

        # ATR-based sizing: risk 1% of portfolio per trade
        risk_per_trade = self.portfolio_value * 0.01
        stop_distance  = max(atr * 2, price * 0.02)   # at least 2% stop
        qty_by_risk    = int(risk_per_trade / stop_distance) if stop_distance > 0 else 0

        # Scale by signal confidence
        confidence_scale = min(abs(signal_score) / 5.0, 1.0)
        recommended_qty  = int(min(max_qty_by_capital, qty_by_risk) * confidence_scale)
        recommended_qty  = max(recommended_qty, 1)   # minimum 1 share

        return {
            "recommended_qty":   recommended_qty,
            "max_qty":           max_qty_by_capital,
            "stop_loss":         round(price - stop_distance, 4),
            "stop_distance":     round(stop_distance, 4),
            "risk_pct":          round(stop_distance * recommended_qty / self.portfolio_value * 100, 3),
        }

    # ── VaR calculation ────────────────────────────────────────

    def calculate_var(self, returns: list[float], confidence: float = 0.99) -> float:
        """
        Calculate Historical Value at Risk (VaR).
        Returns the maximum expected 1-day loss at the given confidence level.
        """
        if not returns or len(returns) < 20:
            return 0.0
        arr = np.array(returns)
        return float(np.percentile(arr, (1 - confidence) * 100))

    # ── Risk veto gate ─────────────────────────────────────────

    def evaluate(
        self,
        decision:      dict,
        signal_vector: dict,
        recent_returns: list[float] = None,
    ) -> dict:
        """
        Evaluate an agent decision against all risk rules.

        Args:
            decision:       {'action': 'BUY'|'SELL'|'HOLD', 'symbol': str, 'qty': int, ...}
            signal_vector:  Market analysis output for this symbol
            recent_returns: List of recent daily returns for VaR calculation

        Returns:
            Dict with: approved (bool), action, qty, reason, risk_metrics
        """
        symbol  = decision.get("symbol", "")
        action  = decision.get("action", "HOLD")
        qty     = decision.get("qty", 0)
        price   = signal_vector.get("close", 0)
        rsi     = signal_vector.get("rsi_14")
        atr     = signal_vector.get("atr_14", 0) or 0
        vol_reg = signal_vector.get("vol_regime", "MEDIUM")

        veto_reasons   = []
        modify_reasons = []

        # ── Rule 1: Daily drawdown limit ──────────────────────
        daily_drawdown = self.daily_pnl / self.portfolio_value
        if daily_drawdown < -self.config.max_daily_drawdown:
            veto_reasons.append(
                f"Daily drawdown limit breached ({daily_drawdown*100:.1f}% vs -{self.config.max_daily_drawdown*100:.0f}% limit)"
            )

        # ── Rule 2: Total drawdown limit ──────────────────────
        total_drawdown = (self.portfolio_value - self.peak_value) / self.peak_value
        if total_drawdown < -self.config.max_total_drawdown:
            veto_reasons.append(
                f"Total drawdown limit breached ({total_drawdown*100:.1f}% vs -{self.config.max_total_drawdown*100:.0f}% limit)"
            )

        if action == "BUY":
            # ── Rule 3: RSI too extreme for buy ───────────────
            if rsi is not None and rsi < self.config.min_rsi_for_buy:
                veto_reasons.append(
                    f"RSI too low for buy ({rsi:.1f} < {self.config.min_rsi_for_buy} — extreme crash signal)"
                )

            # ── Rule 4: High volatility regime → reduce size ──
            if vol_reg == "HIGH":
                qty = max(int(qty * 0.5), 1)
                modify_reasons.append("Position halved due to HIGH volatility regime")

            # ── Rule 5: VaR limit ──────────────────────────────
            if recent_returns:
                var = self.calculate_var(recent_returns, self.config.var_confidence)
                position_var = abs(var) * qty * price
                portfolio_var_pct = position_var / self.portfolio_value
                if portfolio_var_pct > self.config.var_limit_pct:
                    qty = max(int(qty * (self.config.var_limit_pct / portfolio_var_pct)), 1)
                    modify_reasons.append(
                        f"Position reduced by VaR limit (99% VaR={portfolio_var_pct*100:.2f}%)"
                    )

            # ── Rule 6: Max position size ──────────────────────
            max_value = self.portfolio_value * self.config.max_position_pct
            if qty * price > max_value:
                qty = max(int(max_value / price), 1)
                modify_reasons.append(
                    f"Position capped at {self.config.max_position_pct*100:.0f}% of portfolio"
                )

        # ── Build result ───────────────────────────────────────
        approved = len(veto_reasons) == 0
        final_action = action if approved else "HOLD"
        final_qty    = qty    if approved else 0

        result = {
            "approved":      approved,
            "action":        final_action,
            "symbol":        symbol,
            "qty":           final_qty,
            "price":         price,
            "veto_reasons":  veto_reasons,
            "modify_reasons": modify_reasons,
            "risk_metrics": {
                "daily_drawdown_pct":  round(daily_drawdown * 100, 2),
                "total_drawdown_pct":  round(total_drawdown * 100, 2),
                "position_value":      round(final_qty * price, 2),
                "position_pct":        round(final_qty * price / self.portfolio_value * 100, 2),
                "vol_regime":          vol_reg,
                "atr":                 round(atr, 4),
            },
        }

        # Log the decision
        self.decision_log.append({**decision, **result})

        status = "APPROVED" if approved else "VETOED"
        logger.info(
            f"Risk check: {symbol} {action} {qty} shares → {status} "
            f"{'| ' + '; '.join(veto_reasons) if veto_reasons else ''}"
        )
        return result
