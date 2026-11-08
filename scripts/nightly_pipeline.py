"""Nightly automated SiraLens pipeline.

Executes:
  1. Crawlers: Discovers and captures new/updated vacancies from all enabled portals and channels.
  2. Normalizer: Cleans, parses dates, tags skills, computes scam risks, deduplicates, and populates `jobs`.
  3. Lifecycle Maintenance: Expires past-deadline jobs.

Can be triggered by:
  - GitHub Actions (cloud cron, runs even when PC is off)
  - Windows Task Scheduler (local daemon)
  - Manual execution: python scripts/nightly_pipeline.py
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import os
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_env() -> None:
    if os.getenv("DATABASE_URL"):
        return
    try:
        from dotenv import load_dotenv

        env_file = PROJECT_ROOT / "backend" / ".env"
        if env_file.exists():
            load_dotenv(env_file)
    except ImportError:
        pass


def run_pipeline() -> None:
    load_env()
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("ERROR: DATABASE_URL is not set.", file=sys.stderr)
        sys.exit(1)

    start_time = time.monotonic()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 65)
    print(f"SIRALENS NIGHTLY PIPELINE START: {now_str}")
    print("=" * 65)

    # 1. Run Crawlers
    print("\n--- STEP 1: CRAWLING ENABLED SOURCES ---")
    try:
        from crawlers.config import load_sources
        from crawlers.runner import run_all

        sources = [s for s in load_sources(PROJECT_ROOT / "crawlers" / "sources.yaml") if s.enabled]
        print(f"Loaded {len(sources)} enabled sources.")
        results = asyncio.run(run_all(sources, dsn=dsn, check=False, concurrency=2, limit=None, timeout=600.0))
        total_fetched = sum(r.fetched for r in results)
        total_new = sum(r.new for r in results)
        print(f"Crawlers completed: {total_fetched} fetched, {total_new} new items captured.")
    except Exception as exc:
        print(f"ERROR in Crawlers Step: {exc}", file=sys.stderr)

    # 2. Run Normalizer
    print("\n--- STEP 2: NORMALIZING & EXPIRING OLD JOBS ---")
    try:
        from normalizer.runner import process_batch

        processed = process_batch(dsn, limit=None, dry_run=False)
        print(f"Normalizer completed: {processed} jobs structured into `jobs` table.")
    except Exception as exc:
        print(f"ERROR in Normalizer Step: {exc}", file=sys.stderr)

    duration = time.monotonic() - start_time
    print("\n" + "=" * 65)
    print(f"SIRALENS NIGHTLY PIPELINE COMPLETED in {duration:.1f}s")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    run_pipeline()
