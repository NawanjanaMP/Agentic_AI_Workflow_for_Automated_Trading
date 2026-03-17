"""
src/pipelines/data_collection_dag.py

Apache Airflow DAG — orchestrates all data collectors on schedule.

Schedule:
  - Daily OHLCV + Fundamentals: runs at 6:00 AM UTC (after US market close)
  - News collection: runs every 2 hours
  - Alpha Vantage indicators: runs at 6:30 AM UTC (after OHLCV)
  - Crypto data: runs every hour

To use without Airflow (for testing), each task can be called directly.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from loguru import logger

# ── Default DAG settings ──────────────────────────
DEFAULT_ARGS = {
    "owner": "trading-team",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,          # Set to True + add email in .env for alerts
}


# ─────────────────────────────────────────────────
# Task Functions (called by Airflow operators)
# ─────────────────────────────────────────────────

def task_collect_yahoo(**kwargs):
    """Daily stock OHLCV + fundamentals via Yahoo Finance."""
    from data.ingestion.yahoo_collector import YahooCollector
    collector = YahooCollector()
    results = collector.run(period="5d", interval="1d")   # last 5 days (delta update)
    logger.info(f"Yahoo collection results: {results}")
    return results


def task_collect_yahoo_intraday(**kwargs):
    """Hourly intraday bars (1h interval, last 60 days)."""
    from data.ingestion.yahoo_collector import YahooCollector
    from config.settings import settings
    collector = YahooCollector()
    # Only high-priority symbols for intraday to save API calls
    priority_symbols = ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"]
    results = collector.run(symbols=priority_symbols, period="60d", interval="1h")
    return results


def task_collect_alpha_vantage(**kwargs):
    """Technical indicators from Alpha Vantage."""
    from data.ingestion.alpha_vantage_collector import AlphaVantageCollector
    from config.settings import settings
    collector = AlphaVantageCollector()
    # Free tier: only 5 symbols per day
    collector.run(symbols=settings.STOCK_SYMBOLS[:5])


def task_collect_crypto(**kwargs):
    """Binance crypto OHLCV."""
    from data.ingestion.binance_collector import BinanceCollector
    collector = BinanceCollector()
    collector.run_historical(timeframe="1h")


def task_collect_news(**kwargs):
    """NewsAPI + RSS financial news."""
    from data.ingestion.news_collector import NewsCollector
    collector = NewsCollector()
    collector.run()


def task_validate_data(**kwargs):
    """
    Basic data quality checks after collection.
    Fails the DAG if critical data is missing.
    """
    import boto3
    from config.settings import settings
    from datetime import timezone

    s3 = boto3.client("s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_DEFAULT_REGION,
    )

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    required_files = [
        f"stocks/daily/AAPL/{today}.parquet",
        f"stocks/daily/SPY/{today}.parquet",
        f"news/newsapi/{today}.jsonl",
    ]

    missing = []
    for key in required_files:
        try:
            s3.head_object(Bucket=settings.S3_RAW_BUCKET, Key=key)
            logger.info(f"Validated: {key}")
        except Exception:
            missing.append(key)
            logger.error(f"Missing expected file: {key}")

    if missing:
        raise ValueError(f"Data validation failed. Missing files: {missing}")

    logger.success("All critical data files validated.")


# ─────────────────────────────────────────────────
# DAG 1: Daily Stock Data (6:00 AM UTC)
# ─────────────────────────────────────────────────

with DAG(
    dag_id="daily_stock_collection",
    default_args=DEFAULT_ARGS,
    description="Collect daily stock OHLCV, fundamentals, and indicators",
    schedule_interval="0 6 * * 1-5",       # Weekdays at 6 AM UTC
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["data-collection", "stocks"],
) as dag_stocks:

    collect_yahoo = PythonOperator(
        task_id="collect_yahoo_ohlcv",
        python_callable=task_collect_yahoo,
    )

    collect_av = PythonOperator(
        task_id="collect_alpha_vantage_indicators",
        python_callable=task_collect_alpha_vantage,
    )

    validate = PythonOperator(
        task_id="validate_data_quality",
        python_callable=task_validate_data,
    )

    # Dependency: Yahoo first, then AV indicators, then validate
    collect_yahoo >> collect_av >> validate


# ─────────────────────────────────────────────────
# DAG 2: News Collection (every 2 hours)
# ─────────────────────────────────────────────────

with DAG(
    dag_id="news_collection",
    default_args=DEFAULT_ARGS,
    description="Collect financial news from NewsAPI and RSS feeds",
    schedule_interval="0 */2 * * *",        # Every 2 hours
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["data-collection", "news"],
) as dag_news:

    collect_news = PythonOperator(
        task_id="collect_financial_news",
        python_callable=task_collect_news,
    )


# ─────────────────────────────────────────────────
# DAG 3: Crypto Data (every hour)
# ─────────────────────────────────────────────────

with DAG(
    dag_id="crypto_collection",
    default_args=DEFAULT_ARGS,
    description="Collect crypto OHLCV from Binance",
    schedule_interval="0 * * * *",          # Every hour
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["data-collection", "crypto"],
) as dag_crypto:

    collect_crypto = PythonOperator(
        task_id="collect_binance_ohlcv",
        python_callable=task_collect_crypto,
    )


# ─────────────────────────────────────────────────
# Standalone runner (no Airflow needed for testing)
# ─────────────────────────────────────────────────

if __name__ == "__main__":
    """
    Run all collection tasks sequentially without Airflow.
    Good for testing the full pipeline locally.

    Usage: python src/pipelines/data_collection_dag.py
    """
    logger.info("=== Running full data collection (no Airflow) ===")

    logger.info("1/4 Yahoo Finance...")
    task_collect_yahoo()

    logger.info("2/4 Binance Crypto...")
    task_collect_crypto()

    logger.info("3/4 News...")
    task_collect_news()

    logger.info("4/4 Alpha Vantage (limited)...")
    task_collect_alpha_vantage()

    logger.success("All collection tasks complete!")
