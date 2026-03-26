"""
src/agents/info_retrieval.py

Information Retrieval Module — RAG pipeline over news headlines.
Uses FAISS vector store + sentence embeddings to find relevant news
context for any given stock symbol before passing to the LLM agent.
"""

import io
import json
import os
from datetime import datetime, timezone, timedelta

import boto3
import numpy as np
from loguru import logger
from dotenv import load_dotenv

load_dotenv()


class InfoRetrievalModule:
    """
    Retrieves relevant news context for a symbol using:
    1. Keyword matching — fast, no dependencies
    2. FAISS semantic search — deeper relevance (requires sentence-transformers)

    Falls back gracefully to keyword matching if FAISS is unavailable,
    so the agent always gets some context even without heavy ML dependencies.
    """

    def __init__(self):
        self.s3 = boto3.client(
            "s3",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        )
        self.bucket   = os.getenv("S3_RAW_BUCKET", "trading-raw-zone")
        self._articles = []          # in-memory article cache
        self._embeddings = None      # FAISS index (lazy-loaded)
        self._use_faiss  = False

        # Try to import FAISS + sentence-transformers
        try:
            import faiss
            from sentence_transformers import SentenceTransformer
            self._model   = SentenceTransformer("all-MiniLM-L6-v2")
            self._use_faiss = True
            logger.info("FAISS + SentenceTransformer loaded — semantic search enabled")
        except ImportError:
            logger.info("FAISS not available — using keyword search fallback")

    # ── Article loading ────────────────────────────────────────

    def load_articles(self, days_back: int = 7) -> list[dict]:
        """Load news articles from S3 for the past N days."""
        articles = []
        for i in range(days_back):
            date = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
            key  = f"news/newsapi/{date}.jsonl"
            try:
                obj   = self.s3.get_object(Bucket=self.bucket, Key=key)
                lines = obj["Body"].read().decode("utf-8").strip().split("\n")
                for line in lines:
                    if line.strip():
                        articles.append(json.loads(line))
            except Exception:
                pass   # file may not exist for that date

        self._articles = articles
        logger.info(f"Loaded {len(articles)} articles from S3")
        return articles

    def _build_faiss_index(self):
        """Build FAISS index from loaded articles (called lazily)."""
        if not self._use_faiss or not self._articles:
            return
        try:
            import faiss
            texts = [
                f"{a.get('title', '')} {a.get('description', '')}"
                for a in self._articles
            ]
            embeddings = self._model.encode(texts, show_progress_bar=False)
            embeddings = embeddings.astype("float32")
            dim   = embeddings.shape[1]
            index = faiss.IndexFlatL2(dim)
            index.add(embeddings)
            self._embeddings = (index, embeddings)
            logger.info(f"FAISS index built with {len(texts)} articles")
        except Exception as e:
            logger.warning(f"FAISS index build failed: {e}")
            self._use_faiss = False

    # ── Retrieval ──────────────────────────────────────────────

    def get_relevant_news(self, symbol: str, company_name: str = "", top_k: int = 5) -> list[dict]:
        """
        Retrieve top-k most relevant news articles for a symbol.

        Uses FAISS semantic search if available, otherwise keyword matching.

        Args:
            symbol:       Ticker e.g. 'AAPL'
            company_name: Full name e.g. 'Apple' for better keyword matching
            top_k:        Number of articles to return

        Returns:
            List of article dicts with title, description, source, published_at
        """
        if not self._articles:
            self.load_articles()

        if self._use_faiss:
            return self._faiss_search(symbol, company_name, top_k)
        else:
            return self._keyword_search(symbol, company_name, top_k)

    def _faiss_search(self, symbol: str, company_name: str, top_k: int) -> list[dict]:
        """Semantic search using FAISS."""
        if self._embeddings is None:
            self._build_faiss_index()
        if self._embeddings is None:
            return self._keyword_search(symbol, company_name, top_k)

        query = f"{symbol} {company_name} stock market trading"
        query_vec = self._model.encode([query]).astype("float32")
        index, _  = self._embeddings
        _, indices = index.search(query_vec, top_k * 2)

        results = []
        seen = set()
        for idx in indices[0]:
            if idx < len(self._articles):
                article = self._articles[idx]
                title   = article.get("title", "")
                if title not in seen:
                    seen.add(title)
                    results.append(article)
                if len(results) >= top_k:
                    break
        return results

    def _keyword_search(self, symbol: str, company_name: str, top_k: int) -> list[dict]:
        """Simple keyword search — no ML dependencies."""
        keywords = [
            symbol.lower(),
            company_name.lower(),
            "stock", "market", "earnings", "revenue", "Fed", "interest rate",
        ]
        scored = []
        for article in self._articles:
            text  = f"{article.get('title', '')} {article.get('description', '')}".lower()
            score = sum(1 for kw in keywords if kw and kw in text)
            if score > 0:
                scored.append((score, article))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [a for _, a in scored[:top_k]]

    def format_for_prompt(self, articles: list[dict]) -> str:
        """
        Format retrieved articles into a clean string for the LLM prompt.
        Keeps it concise — the LLM context window is finite.
        """
        if not articles:
            return "No relevant news found for this symbol."

        lines = []
        for i, a in enumerate(articles, 1):
            title   = a.get("title", "No title")[:120]
            source  = a.get("source_name", "Unknown")
            pub     = a.get("published_at", "")[:10]
            desc    = a.get("description", "")[:150] if a.get("description") else ""
            lines.append(f"{i}. [{source} | {pub}] {title}")
            if desc:
                lines.append(f"   {desc}")
        return "\n".join(lines)
