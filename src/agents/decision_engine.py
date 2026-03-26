"""
src/agents/decision_engine.py

LLM Decision Engine — the brain of the agentic trading system.
Uses LangChain to orchestrate the full agent loop:

1. Gather market analysis signal vector
2. Retrieve relevant news context via RAG
3. Run risk pre-check
4. Prompt the LLM with full structured context
5. Parse JSON decision
6. Run risk post-check (veto gate)
7. Log decision to RDS + S3

Works with OpenAI GPT-4o or Anthropic Claude via LangChain.
"""

import json
import os
from datetime import datetime, timezone

import boto3
from loguru import logger
from dotenv import load_dotenv

from src.agents.market_analysis import MarketAnalysisModule
from src.agents.info_retrieval  import InfoRetrievalModule
from src.agents.risk_management import RiskManagementModule, RiskConfig

load_dotenv()

# ── Company name map for better news search ────────────────────
COMPANY_NAMES = {
    "AAPL": "Apple",    "MSFT": "Microsoft",  "GOOGL": "Google Alphabet",
    "AMZN": "Amazon",   "NVDA": "NVIDIA",      "META": "Meta Facebook",
    "TSLA": "Tesla",    "JPM": "JPMorgan",     "GS": "Goldman Sachs",
    "BAC":  "Bank of America", "SPY": "S&P 500 ETF",
    "QQQ":  "Nasdaq ETF",      "IWM": "Russell 2000 ETF",
    "BTC-USDT": "Bitcoin",     "ETH-USDT": "Ethereum",
    "SOL-USDT": "Solana",      "BNB-USDT": "Binance Coin",
}


DECISION_PROMPT = """You are an expert quantitative trading analyst. Analyse the following data and make a trading decision.

## Symbol: {symbol}

## Market Analysis Signal Vector
{signal_summary}

Technical indicators:
- RSI (14): {rsi}
- MACD histogram: {macd_hist}
- Bollinger %B: {bb_pct}
- ATR (14): {atr}
- 5-day return: {return_5d}%
- Volatility regime: {vol_regime}
- Signal score: {signal_score}/5 ({signal})
- Signal reasons: {signal_reasons}

## Recent News Context
{news_context}

## Risk Parameters
- Portfolio value: ${portfolio_value:,.0f}
- Recommended position size: {recommended_qty} shares
- Stop loss level: ${stop_loss}
- Max risk per trade: {risk_pct}%

## Instructions
Based on ALL of the above, provide your trading decision as a JSON object.
Be specific about your reasoning — reference the actual indicator values and news items.
Only recommend BUY if signal score >= 2 AND news sentiment is not strongly negative.
Only recommend SELL if signal score <= -2 OR strong negative news catalyst exists.
Otherwise recommend HOLD.

Respond with ONLY this JSON — no other text:
{{
  "action": "BUY" | "SELL" | "HOLD",
  "symbol": "{symbol}",
  "qty": <integer — use recommended_qty for BUY/SELL, 0 for HOLD>,
  "confidence": <float 0.0 to 1.0>,
  "rationale": "<2-3 sentences explaining the decision referencing specific indicators and news>",
  "key_risks": "<main risk to this trade>",
  "target_price": <float or null>,
  "stop_loss": <float — use the recommended stop loss>
}}"""


class DecisionEngine:
    """
    Orchestrates the full agentic trading loop.
    Produces a structured trade decision for each symbol.
    """

    def __init__(self):
        self.market_analysis = MarketAnalysisModule()
        self.info_retrieval  = InfoRetrievalModule()
        self.risk_module     = RiskManagementModule(RiskConfig())
        self.s3              = boto3.client(
            "s3",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        )
        self.bucket = os.getenv("S3_RAW_BUCKET", "trading-raw-zone")
        self._llm   = None

    def _get_llm(self):
        """Lazy-load the LLM. Supports OpenAI and Anthropic."""
        if self._llm is not None:
            return self._llm

        openai_key    = os.getenv("OPENAI_API_KEY", "")
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

        placeholders = {"", "your_key_here", "skip"}

        try:
            if openai_key not in placeholders:
                from langchain_openai import ChatOpenAI
                self._llm = ChatOpenAI(
                    model="gpt-4o-mini",     # cost-efficient for coursework
                    temperature=0.1,          # low temp = more deterministic decisions
                    api_key=openai_key,
                )
                logger.info("LLM loaded: OpenAI GPT-4o-mini")

            elif anthropic_key not in placeholders:
                from langchain_anthropic import ChatAnthropic
                self._llm = ChatAnthropic(
                    model="claude-3-haiku-20240307",
                    temperature=0.1,
                    api_key=anthropic_key,
                )
                logger.info("LLM loaded: Anthropic Claude Haiku")

            else:
                logger.warning("No LLM API key found — using rule-based fallback")
                return None

        except Exception as e:
            logger.error(f"LLM load failed: {e}")
            return None

        return self._llm

    def _rule_based_decision(self, signal_vector: dict, sizing: dict) -> dict:
        """
        Fallback decision when no LLM key is available.
        Uses pure signal scoring — same logic as the signal generator.
        """
        signal = signal_vector.get("signal", "HOLD")
        score  = signal_vector.get("signal_score", 0)
        qty    = sizing.get("recommended_qty", 0) if signal != "HOLD" else 0

        return {
            "action":       signal,
            "symbol":       signal_vector["symbol"],
            "qty":          qty,
            "confidence":   min(abs(score) / 5.0, 1.0),
            "rationale":    f"Rule-based decision: signal score {score:+d}. {'; '.join(signal_vector.get('signal_reasons', [])[:2])}",
            "key_risks":    "No LLM context — rule-based only. News sentiment not considered.",
            "target_price": None,
            "stop_loss":    sizing.get("stop_loss"),
            "source":       "rule_based",
        }

    def _call_llm(self, prompt: str) -> dict:
        """Send prompt to LLM and parse JSON response."""
        llm = self._get_llm()
        if llm is None:
            return {}

        try:
            from langchain_core.messages import HumanMessage
            response = llm.invoke([HumanMessage(content=prompt)])
            text     = response.content.strip()

            # Strip markdown code fences if present
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            decision = json.loads(text)
            decision["source"] = "llm"
            return decision

        except json.JSONDecodeError as e:
            logger.error(f"LLM returned invalid JSON: {e}")
            return {}
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return {}

    def _log_to_s3(self, decision: dict):
        """Log final decision to S3 as immutable audit record."""
        try:
            ts  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
            sym = decision.get("symbol", "unknown")
            key = f"decisions/{sym}/{ts}.json"
            self.s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=json.dumps(decision, default=str),
                ContentType="application/json",
            )
            logger.info(f"Decision logged → s3://{self.bucket}/{key}")
        except Exception as e:
            logger.warning(f"S3 audit log failed: {e}")

    # ── Main agent loop ────────────────────────────────────────

    def decide(self, symbol: str, asset_type: str = "stocks") -> dict:
        """
        Run the full agentic loop for one symbol.

        Steps:
        1. Market analysis → signal vector
        2. News retrieval → context
        3. Position sizing
        4. LLM prompt → raw decision
        5. Risk veto gate → final decision
        6. Audit log

        Returns:
            Final approved decision dict
        """
        logger.info(f"=== Agent decision loop: {symbol} ===")

        # ── Step 1: Market Analysis ────────────────────────────
        signal_vector = self.market_analysis.analyse(symbol, asset_type)
        if "error" in signal_vector:
            return {"symbol": symbol, "action": "HOLD", "error": signal_vector["error"]}

        # ── Step 2: News Retrieval ─────────────────────────────
        company = COMPANY_NAMES.get(symbol, symbol)
        articles = self.info_retrieval.get_relevant_news(symbol, company, top_k=5)
        news_context = self.info_retrieval.format_for_prompt(articles)

        # ── Step 3: Position Sizing ────────────────────────────
        sizing = self.risk_module.calculate_position_size(
            symbol       = symbol,
            price        = signal_vector["close"],
            atr          = signal_vector.get("atr_14", 1.0) or 1.0,
            signal_score = signal_vector.get("signal_score", 0),
        )

        # ── Step 4: LLM Decision ───────────────────────────────
        prompt = DECISION_PROMPT.format(
            symbol           = symbol,
            signal_summary   = signal_vector.get("summary", ""),
            rsi              = signal_vector.get("rsi_14", "N/A"),
            macd_hist        = signal_vector.get("macd_hist", "N/A"),
            bb_pct           = signal_vector.get("bb_pct", "N/A"),
            atr              = signal_vector.get("atr_14", "N/A"),
            return_5d        = signal_vector.get("return_5d_pct", "N/A"),
            vol_regime       = signal_vector.get("vol_regime", "N/A"),
            signal_score     = signal_vector.get("signal_score", 0),
            signal           = signal_vector.get("signal", "HOLD"),
            signal_reasons   = "; ".join(signal_vector.get("signal_reasons", [])),
            news_context     = news_context,
            portfolio_value  = self.risk_module.portfolio_value,
            recommended_qty  = sizing["recommended_qty"],
            stop_loss        = sizing["stop_loss"],
            risk_pct         = sizing["risk_pct"],
        )

        raw_decision = self._call_llm(prompt)
        if not raw_decision:
            raw_decision = self._rule_based_decision(signal_vector, sizing)

        # ── Step 5: Risk Veto Gate ─────────────────────────────
        final_decision = self.risk_module.evaluate(
            decision      = raw_decision,
            signal_vector = signal_vector,
        )

        # Merge all context into final record
        output = {
            **raw_decision,
            "action":        final_decision["action"],
            "qty":           final_decision["qty"],
            "approved":      final_decision["approved"],
            "veto_reasons":  final_decision["veto_reasons"],
            "risk_metrics":  final_decision["risk_metrics"],
            "signal_vector": signal_vector,
            "news_count":    len(articles),
            "decided_at":    datetime.now(timezone.utc).isoformat(),
        }

        # ── Step 6: Audit Log ──────────────────────────────────
        self._log_to_s3(output)

        logger.info(
            f"Final decision: {symbol} → {output['action']} "
            f"(approved={output['approved']}, confidence={raw_decision.get('confidence', 0):.2f})"
        )
        return output

    def decide_all(self, symbols: list, asset_type: str = "stocks") -> list[dict]:
        """Run the full agent loop for a list of symbols."""
        # Load articles once for all symbols
        self.info_retrieval.load_articles()

        decisions = []
        for sym in symbols:
            try:
                decision = self.decide(sym, asset_type)
                decisions.append(decision)
            except Exception as e:
                logger.error(f"Agent loop failed for {sym}: {e}")
                decisions.append({"symbol": sym, "action": "HOLD", "error": str(e)})
        return decisions


# ── Entry point ────────────────────────────────────────────────

if __name__ == "__main__":
    engine = DecisionEngine()

    # Run agent for a few symbols
    test_symbols = ["AAPL", "NVDA", "TSLA", "SPY"]
    logger.info(f"Running agent for: {test_symbols}")

    decisions = engine.decide_all(test_symbols)

    print("\n" + "="*60)
    print("AGENT DECISIONS SUMMARY")
    print("="*60)
    for d in decisions:
        print(
            f"{d['symbol']:10s} | {d.get('action','HOLD'):4s} | "
            f"Conf: {d.get('confidence', 0):.0%} | "
            f"Approved: {d.get('approved', False)} | "
            f"{d.get('rationale', 'N/A')[:80]}"
        )
