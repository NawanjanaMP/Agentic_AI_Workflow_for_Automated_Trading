"""
data/ingestion/news_collector.py

Collects financial news headlines from NewsAPI and RSS feeds.
Stores raw headlines to S3 for later FinBERT sentiment scoring.

Free NewsAPI tier: 100 requests/day, 1-month history.
Sign up: https://newsapi.org/register
"""

import feedparser
import json
from datetime import datetime, timezone, timedelta

import requests
from loguru import logger

from config.settings import settings
from data.ingestion.yahoo_collector import S3Uploader


# Financial RSS feeds (no API key needed)
RSS_FEEDS = {
    "reuters_business":    "https://feeds.reuters.com/reuters/businessNews",
    "yahoo_finance_news":  "https://finance.yahoo.com/news/rssindex",
    "seeking_alpha":       "https://seekingalpha.com/feed.xml",
    "marketwatch":         "https://feeds.marketwatch.com/marketwatch/topstories/",
    "cnbc_finance":        "https://www.cnbc.com/id/10001147/device/rss/rss.html",
    "bloomberg":           "https://feeds.bloomberg.com/markets/news.rss",
    "ft_markets":          "https://www.ft.com/markets?format=rss",
}


class NewsCollector:
    """
    Aggregates financial news from:
    1. NewsAPI — keyword-based search per ticker
    2. RSS feeds — top financial news sources

    Output: JSONL files stored in S3 under:
        news/newsapi/YYYY-MM-DD.jsonl
        news/rss/SOURCE/YYYY-MM-DD.jsonl
    """

    def __init__(self):
        self.api_key = settings.NEWS_API_KEY
        self.uploader = S3Uploader()
        self.base_url = "https://newsapi.org/v2/everything"

    # ── NewsAPI ───────────────────────────────────

    def fetch_newsapi(self, query: str, days_back: int = 7, page_size: int = 100) -> list[dict]:
        """
        Search NewsAPI for articles matching a query.

        Args:
            query:     Search query e.g. 'Apple stock AAPL earnings'
            days_back: How many days of articles to retrieve
            page_size: Articles per request (max 100 on free tier)

        Returns:
            List of article dicts with title, description, url, publishedAt, source
        """
        from_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")

        params = {
            "q": query,
            "from": from_date,
            "sortBy": "relevancy",
            "language": "en",
            "pageSize": page_size,
            "apiKey": self.api_key,
        }

        try:
            resp = requests.get(self.base_url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "ok":
                logger.warning(f"NewsAPI error: {data.get('message', 'Unknown error')}")
                return []

            articles = data.get("articles", [])
            logger.info(f"NewsAPI: {len(articles)} articles for query='{query}'")

            # Flatten and tag
            cleaned = []
            for a in articles:
                cleaned.append({
                    "title": a.get("title", ""),
                    "description": a.get("description", ""),
                    "url": a.get("url", ""),
                    "source_name": a.get("source", {}).get("name", ""),
                    "published_at": a.get("publishedAt", ""),
                    "query": query,
                    "collector": "newsapi",
                    "ingested_at": datetime.now(timezone.utc).isoformat(),
                })
            return cleaned

        except requests.RequestException as e:
            logger.error(f"NewsAPI request failed: {e}")
            return []

    def fetch_all_ticker_news(self, symbols: list = None) -> list[dict]:
        """Fetch news for all tracked stock symbols."""
        symbols = symbols or settings.STOCK_SYMBOLS[:10]  # Free tier: be conservative
        all_articles = []

        # Build company-name queries for better results
        ticker_queries = {
            "AAPL": "Apple stock AAPL",
            "MSFT": "Microsoft stock MSFT",
            "GOOGL": "Google Alphabet GOOGL",
            "AMZN": "Amazon stock AMZN",
            "NVDA": "NVIDIA stock NVDA",
            "META": "Meta Facebook stock META",
            "TSLA": "Tesla stock TSLA",
            "JPM": "JPMorgan Chase stock JPM",
            "GS": "Goldman Sachs stock GS",
            "BAC": "Bank of America stock BAC",
        }

        for symbol in symbols:
            query = ticker_queries.get(symbol, f"{symbol} stock")
            articles = self.fetch_newsapi(query=query, days_back=7)
            all_articles.extend(articles)

        # Also fetch general market news
        market_queries = [
            "stock market today",
            "Federal Reserve interest rates",
            "earnings report Wall Street",
            "cryptocurrency bitcoin market",
        ]
        for q in market_queries:
            all_articles.extend(self.fetch_newsapi(query=q, days_back=3))

        return all_articles

    # ── RSS Feeds ─────────────────────────────────

    def fetch_rss(self, feed_name: str, feed_url: str) -> list[dict]:
        """
        Parse a single RSS feed and return articles as dicts.
        Uses feedparser — no API key needed.
        """
        logger.info(f"Parsing RSS feed: {feed_name}")
        try:
            feed = feedparser.parse(feed_url)
            articles = []

            for entry in feed.entries[:50]:  # cap at 50 per feed
                articles.append({
                    "title": getattr(entry, "title", ""),
                    "description": getattr(entry, "summary", ""),
                    "url": getattr(entry, "link", ""),
                    "source_name": feed_name,
                    "published_at": getattr(entry, "published", ""),
                    "collector": "rss",
                    "ingested_at": datetime.now(timezone.utc).isoformat(),
                })

            logger.info(f"RSS {feed_name}: {len(articles)} articles")
            return articles

        except Exception as e:
            logger.error(f"RSS parse failed for {feed_name}: {e}")
            return []

    def fetch_all_rss(self) -> dict[str, list[dict]]:
        """Fetch all configured RSS feeds. Returns dict keyed by feed name."""
        results = {}
        for name, url in RSS_FEEDS.items():
            results[name] = self.fetch_rss(name, url)
        return results

    # ── Storage ───────────────────────────────────

    def _articles_to_jsonl(self, articles: list[dict]) -> str:
        """Convert list of article dicts to JSONL format (one JSON per line)."""
        return "\n".join(json.dumps(a, ensure_ascii=False) for a in articles)

    def _upload_articles(self, articles: list[dict], s3_key: str):
        """Upload articles as JSONL to S3."""
        if not articles:
            logger.warning(f"No articles to upload for key: {s3_key}")
            return
        jsonl = self._articles_to_jsonl(articles)
        try:
            import boto3
            client = boto3.client(
                "s3",
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_DEFAULT_REGION,
            )
            client.put_object(
                Bucket=settings.S3_RAW_BUCKET,
                Key=s3_key,
                Body=jsonl.encode("utf-8"),
                ContentType="application/x-ndjson",
            )
            logger.info(f"Uploaded {len(articles)} articles → s3://{settings.S3_RAW_BUCKET}/{s3_key}")
        except Exception as e:
            logger.error(f"Upload failed for {s3_key}: {e}")

    # ── Main Run ──────────────────────────────────

    def run(self):
        """Full collection run — NewsAPI + all RSS feeds."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # NewsAPI articles
        logger.info("=== Collecting NewsAPI articles ===")
        newsapi_articles = self.fetch_all_ticker_news()
        self._upload_articles(newsapi_articles, f"news/newsapi/{today}.jsonl")

        # RSS feeds
        logger.info("=== Collecting RSS feeds ===")
        rss_results = self.fetch_all_rss()
        for feed_name, articles in rss_results.items():
            self._upload_articles(articles, f"news/rss/{feed_name}/{today}.jsonl")

        total = len(newsapi_articles) + sum(len(v) for v in rss_results.values())
        logger.success(f"News collection complete. Total articles: {total}")


if __name__ == "__main__":
    collector = NewsCollector()
    collector.run()
