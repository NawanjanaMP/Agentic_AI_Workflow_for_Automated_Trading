"""
cloud/setup_aws.py

One-time AWS resource provisioning script.
Run this ONCE after creating your AWS account to set up:
  - S3 buckets (raw zone + processed zone)
  - RDS PostgreSQL database
  - Required IAM policies (guidance only — do via Console)

Prerequisites:
  1. Create AWS account: https://aws.amazon.com/free
  2. Create IAM user with programmatic access
  3. Attach policies: AmazonS3FullAccess, AmazonRDSFullAccess
  4. Copy Access Key + Secret Key to your .env file
  5. Run: python cloud/setup_aws.py
"""

import boto3
from botocore.exceptions import ClientError
from loguru import logger

from config.settings import settings


# ─────────────────────────────────────────────────
# S3 Setup
# ─────────────────────────────────────────────────

def create_s3_buckets():
    """Create S3 raw and processed zone buckets with proper configuration."""
    s3 = boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_DEFAULT_REGION,
    )

    buckets = [
        {
            "name": settings.S3_RAW_BUCKET,
            "description": "Raw zone — original ingested data",
        },
        {
            "name": settings.S3_PROCESSED_BUCKET,
            "description": "Processed zone — cleaned features",
        },
        {
            "name": f"{settings.S3_RAW_BUCKET}-archive",
            "description": "Archive — historical backups",
        },
    ]

    for bucket_config in buckets:
        bucket_name = bucket_config["name"]
        try:
            if settings.AWS_DEFAULT_REGION == "us-east-1":
                s3.create_bucket(Bucket=bucket_name)
            else:
                s3.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={"LocationConstraint": settings.AWS_DEFAULT_REGION},
                )

            # Enable versioning (allows recovery of overwritten files)
            s3.put_bucket_versioning(
                Bucket=bucket_name,
                VersioningConfiguration={"Status": "Enabled"},
            )

            # Lifecycle rule: move to Glacier after 90 days
            s3.put_bucket_lifecycle_configuration(
                Bucket=bucket_name,
                LifecycleConfiguration={
                    "Rules": [
                        {
                            "ID": "archive-old-data",
                            "Status": "Enabled",
                            "Filter": {"Prefix": ""},
                            "Transitions": [
                                {
                                    "Days": 90,
                                    "StorageClass": "GLACIER",
                                }
                            ],
                        }
                    ]
                },
            )

            # Block all public access (security best practice)
            s3.put_public_access_block(
                Bucket=bucket_name,
                PublicAccessBlockConfiguration={
                    "BlockPublicAcls": True,
                    "IgnorePublicAcls": True,
                    "BlockPublicPolicy": True,
                    "RestrictPublicBuckets": True,
                },
            )

            logger.success(f"Created S3 bucket: {bucket_name} — {bucket_config['description']}")

        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                logger.info(f"Bucket already exists, skipping: {bucket_name}")
            else:
                logger.error(f"Failed to create bucket {bucket_name}: {e}")


# ─────────────────────────────────────────────────
# RDS Setup
# ─────────────────────────────────────────────────

def create_rds_instance():
    """
    Create a PostgreSQL RDS instance (Free Tier eligible: db.t3.micro).

    NOTE: This takes ~5–10 minutes to provision.
    After creation, copy the endpoint URL to your .env as RDS_HOST.

    Free Tier limits: 750 hours/month db.t3.micro, 20GB storage
    """
    rds = boto3.client(
        "rds",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_DEFAULT_REGION,
    )

    try:
        response = rds.create_db_instance(
            DBInstanceIdentifier="trading-db",
            DBInstanceClass="db.t3.micro",          # Free Tier eligible
            Engine="postgres",
            EngineVersion="16.3",
            MasterUsername=settings.RDS_USER,
            MasterUserPassword=settings.RDS_PASSWORD,
            DBName=settings.RDS_DATABASE,
            AllocatedStorage=20,                    # GB — Free Tier max
            StorageType="gp2",
            MultiAZ=False,                          # Single-AZ for dev (saves cost)
            PubliclyAccessible=True,                # Set False in production
            BackupRetentionPeriod=0,                # 0 = disabled (required for free tier)
            Tags=[
                {"Key": "Project", "Value": "agentic-trading"},
                {"Key": "Environment", "Value": settings.ENVIRONMENT},
            ],
        )

        db_id = response["DBInstance"]["DBInstanceIdentifier"]
        logger.success(f"RDS instance creating: {db_id}")
        logger.info("Waiting for RDS to become available (~5-10 minutes)...")

        waiter = rds.get_waiter("db_instance_available")
        waiter.wait(DBInstanceIdentifier=db_id)

        # Get the endpoint after provisioning
        desc = rds.describe_db_instances(DBInstanceIdentifier=db_id)
        endpoint = desc["DBInstances"][0]["Endpoint"]["Address"]
        logger.success(f"RDS ready! Endpoint: {endpoint}")
        logger.info(f"Add to your .env: RDS_HOST={endpoint}")
        return endpoint

    except ClientError as e:
        if "DBInstanceAlreadyExists" in str(e):
            logger.info("RDS instance 'trading-db' already exists.")
        else:
            logger.error(f"RDS creation failed: {e}")
        return None


# ─────────────────────────────────────────────────
# Database Schema Setup
# ─────────────────────────────────────────────────

def create_database_tables():
    """
    Create PostgreSQL tables for structured data storage.
    Run after RDS is ready and RDS_HOST is in your .env.
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(settings.rds_connection_string)

    schema_sql = """
    -- ── Audit log for every agent decision ──────
    CREATE TABLE IF NOT EXISTS trade_decisions (
        id              SERIAL PRIMARY KEY,
        symbol          VARCHAR(20)   NOT NULL,
        action          VARCHAR(10)   NOT NULL,   -- BUY | SELL | HOLD
        quantity        DECIMAL(18,8),
        price_at_signal DECIMAL(18,4),
        confidence      DECIMAL(5,4),
        rationale       TEXT,
        signal_vector   JSONB,                    -- full feature snapshot
        agent_model     VARCHAR(50),
        decided_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
        executed        BOOLEAN       DEFAULT FALSE
    );

    -- ── Company fundamentals (quarterly) ────────
    CREATE TABLE IF NOT EXISTS fundamentals (
        id              SERIAL PRIMARY KEY,
        symbol          VARCHAR(20)   NOT NULL,
        company_name    VARCHAR(200),
        sector          VARCHAR(100),
        industry        VARCHAR(100),
        market_cap      BIGINT,
        pe_ratio        DECIMAL(10,4),
        forward_pe      DECIMAL(10,4),
        eps             DECIMAL(10,4),
        revenue_ttm     BIGINT,
        gross_margin    DECIMAL(8,6),
        debt_to_equity  DECIMAL(10,4),
        beta            DECIMAL(8,4),
        dividend_yield  DECIMAL(8,6),
        week_52_high    DECIMAL(10,4),
        week_52_low     DECIMAL(10,4),
        source          VARCHAR(50),
        ingested_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW()
    );

    -- ── Macro indicators (FRED / manual) ─────────
    CREATE TABLE IF NOT EXISTS macro_indicators (
        id              SERIAL PRIMARY KEY,
        indicator_name  VARCHAR(100)  NOT NULL,   -- 'fed_funds_rate', 'cpi_yoy', etc.
        value           DECIMAL(18,6) NOT NULL,
        period_date     DATE          NOT NULL,
        source          VARCHAR(50),
        ingested_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW()
    );

    -- ── News articles (raw) ──────────────────────
    CREATE TABLE IF NOT EXISTS news_articles (
        id              SERIAL PRIMARY KEY,
        title           TEXT,
        description     TEXT,
        url             TEXT          UNIQUE,
        source_name     VARCHAR(100),
        published_at    TIMESTAMPTZ,
        sentiment_score DECIMAL(6,4),             -- FinBERT score -1 to +1
        sentiment_label VARCHAR(10),              -- positive | negative | neutral
        related_symbols VARCHAR(20)[],            -- array of tickers
        collector       VARCHAR(20),
        ingested_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW()
    );

    -- ── Indices for common query patterns ────────
    CREATE INDEX IF NOT EXISTS idx_trade_decisions_symbol  ON trade_decisions(symbol);
    CREATE INDEX IF NOT EXISTS idx_trade_decisions_decided ON trade_decisions(decided_at DESC);
    CREATE INDEX IF NOT EXISTS idx_fundamentals_symbol     ON fundamentals(symbol);
    CREATE INDEX IF NOT EXISTS idx_news_published          ON news_articles(published_at DESC);
    CREATE INDEX IF NOT EXISTS idx_news_symbols            ON news_articles USING GIN(related_symbols);
    """

    try:
        with engine.connect() as conn:
            conn.execute(text(schema_sql))
            conn.commit()
        logger.success("Database tables created successfully.")
    except Exception as e:
        logger.error(f"Schema creation failed: {e}")


# ─────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("=== AWS Resource Setup ===")
    logger.info("Step 1: Creating S3 buckets...")
    create_s3_buckets()

    logger.info("Step 2: Creating RDS PostgreSQL instance...")
    logger.info("(This takes 5-10 minutes — go make a coffee)")
    endpoint = create_rds_instance()

    if endpoint:
        logger.info("Step 3: Creating database schema...")
        create_database_tables()

    logger.success("AWS setup complete! Check your .env file and update RDS_HOST if needed.")
    logger.info("""
╔══════════════════════════════════════════════╗
║  Next Steps:                                 ║
║  1. Copy RDS endpoint → .env RDS_HOST        ║
║  2. Open RDS Security Group port 5432        ║
║     (AWS Console → RDS → Connectivity)       ║
║  3. Run data collectors:                     ║
║     python data/ingestion/yahoo_collector.py ║
╚══════════════════════════════════════════════╝
    """)