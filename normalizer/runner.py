"""Normalization Runner (CLI & Automation).

Fetches unprocessed raw records from `job_raw`, runs the normalization pipeline,
saves structured rows into `jobs` and `job_skills`, and marks raw captures as processed.

Usage:
    python -m normalizer.runner                  # normalize all pending raw captures
    python -m normalizer.runner --limit 50       # normalize first 50 items
    python -m normalizer.runner --dry-run        # inspect extraction without writing to DB
    python -m normalizer.runner --source geezjobs # normalize only a specific source
    python -m normalizer.runner --stats          # show current database counts and stats
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .dedup import find_or_create_dedup_group, make_dedup_key
from .models import NormalizedJob
from .pipeline import normalize_raw_capture


def load_env() -> None:
    """Load backend/.env if DATABASE_URL is not set."""
    if os.getenv("DATABASE_URL"):
        return
    try:
        from dotenv import load_dotenv

        env_path = Path(__file__).resolve().parent.parent / "backend" / ".env"
        if env_path.exists():
            load_dotenv(env_path)
    except ImportError:
        pass


def connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, prepare_threshold=None, row_factory=dict_row)


def print_stats(dsn: str) -> None:
    """Print high-level statistics of job_raw and jobs."""
    with connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("select count(*) as c from job_raw")
        raw_total = cur.fetchone()["c"]
        cur.execute("select count(*) as c from job_raw where processed_at is null")
        raw_unprocessed = cur.fetchone()["c"]
        cur.execute("select count(*) as c from jobs")
        jobs_total = cur.fetchone()["c"]
        cur.execute("select count(*) as c from jobs where status = 'open'")
        jobs_open = cur.fetchone()["c"]
        cur.execute("select count(*) as c from job_skills")
        skills_total = cur.fetchone()["c"]
        cur.execute("select count(*) as c from jobs where risk_score >= 30")
        risky_total = cur.fetchone()["c"]

    print("=" * 60)
    print("SIRALens Database Stats:")
    print(f"  Raw Captures (job_raw):  {raw_total} total ({raw_unprocessed} pending)")
    print(f"  Normalized Jobs (jobs):  {jobs_total} total ({jobs_open} open)")
    print(f"  Tagged Skills:           {skills_total} entries")
    print(f"  Scam/Risk Flagged:       {risky_total} jobs (risk_score >= 30)")
    print("=" * 60)


def expire_past_deadlines(conn: psycopg.Connection) -> int:
    """Mark jobs whose deadline has passed as expired."""
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            """
            update jobs
            set status = 'expired', last_seen_at = now()
            where status = 'open' and deadline is not null and deadline < current_date
            returning id
            """
        )
        expired = cur.fetchall()
        count = len(expired)
    if count > 0:
        print(f"Expired {count} jobs whose deadlines have passed.")
    return count


def load_existing_dedup_groups(conn: psycopg.Connection) -> dict[str, uuid.UUID]:
    """Preload dedup keys from existing jobs."""
    groups: dict[str, uuid.UUID] = {}
    with conn.cursor() as cur:
        cur.execute("select employer_name, title, deadline, dedup_group_id from jobs where dedup_group_id is not null")
        for row in cur.fetchall():
            dl_str = row["deadline"].isoformat() if row["deadline"] else None
            k = make_dedup_key(row["employer_name"], row["title"], dl_str)
            groups[k] = row["dedup_group_id"]
    return groups


def process_batch(
    dsn: str,
    *,
    limit: int | None = None,
    dry_run: bool = False,
    source_slug: str | None = None,
    force: bool = False,
) -> int:
    with connect(dsn) as conn:
        dedup_groups = load_existing_dedup_groups(conn) if not dry_run else {}

        where_clauses: list[str] = []
        params: list[Any] = []
        if not force:
            where_clauses.append("r.processed_at is null")
        if source_slug:
            where_clauses.append("s.slug = %s")
            params.append(source_slug)

        where_sql = f"where {' and '.join(where_clauses)}" if where_clauses else ""
        limit_sql = "limit %s" if limit else ""
        query = f"""
            select r.id, r.source_id, r.external_id, r.url, r.raw_text, r.raw_meta,
                   r.content_hash, r.fetched_at, s.slug as source_slug
            from job_raw r
            join job_sources s on s.id = r.source_id
            {where_sql}
            order by r.fetched_at asc
            {limit_sql}
        """
        if limit:
            params.append(limit)

        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

        if not rows:
            print("No pending raw jobs found to normalize.")
            return 0

        total_rows = len(rows)
        print(f"Normalizing {total_rows} raw job items...\n")
        processed_count = 0
        source_counts: dict[str, int] = {}
        total_skills = 0
        total_risky = 0

        for idx, r in enumerate(rows, start=1):
            source_slug = r["source_slug"]
            job: NormalizedJob = normalize_raw_capture(
                raw_id=r["id"],
                source_id=r["source_id"],
                external_id=r["external_id"],
                url=r["url"],
                raw_text=r["raw_text"],
                raw_meta=r["raw_meta"],
                content_hash=r["content_hash"],
                fetched_at=r["fetched_at"],
            )

            # Deduplication
            dl_str = job.deadline.isoformat() if job.deadline else None
            key = make_dedup_key(job.employer_name, job.title, dl_str)
            group_id, is_canon = find_or_create_dedup_group(key, dedup_groups)
            job.dedup_group_id = group_id
            job.is_canonical = is_canon

            if dry_run:
                print("-" * 50)
                print(f"[{idx}/{total_rows}] [{source_slug}] {job.title}")
                print(f"  Employer:   {job.employer_name or 'N/A'}")
                print(f"  Location:   {job.location_city or 'N/A'}, {job.location_country}")
                print(f"  Work Mode:  {job.work_mode or 'N/A'} | Type: {job.job_type}")
                print(f"  Deadline:   {job.deadline or 'N/A'} | Status: {job.status}")
                print(f"  Education:  {job.education_level or 'N/A'} | Min Exp: {job.experience_years_min} yrs")
                print(f"  Skills:     {', '.join(job.skills) if job.skills else 'None'}")
                print(f"  Risk Score: {job.risk_score} (flags: {job.risk_flags})")
                print(f"  Canonical:  {job.is_canonical} (group: {job.dedup_group_id})")
                processed_count += 1
                source_counts[source_slug] = source_counts.get(source_slug, 0) + 1
                continue

            # Database write
            try:
                with conn.transaction(), conn.cursor() as cur:
                    upsert_job_sql = """
                        insert into jobs (
                            source_id, external_id, url, title, employer_name, description,
                            language, location_city, location_country, work_mode, job_type,
                            eligibility, eligibility_note, deadline, posted_at, education_level,
                            experience_years_min, apply_info, risk_score, risk_flags, content_hash,
                            dedup_group_id, is_canonical, status, first_seen_at, last_seen_at
                        ) values (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now()
                        )
                        on conflict (source_id, external_id) do update set
                            url = excluded.url,
                            title = excluded.title,
                            employer_name = excluded.employer_name,
                            description = excluded.description,
                            language = excluded.language,
                            location_city = excluded.location_city,
                            location_country = excluded.location_country,
                            work_mode = excluded.work_mode,
                            job_type = excluded.job_type,
                            eligibility = excluded.eligibility,
                            eligibility_note = excluded.eligibility_note,
                            deadline = excluded.deadline,
                            posted_at = excluded.posted_at,
                            education_level = excluded.education_level,
                            experience_years_min = excluded.experience_years_min,
                            apply_info = excluded.apply_info,
                            risk_score = excluded.risk_score,
                            risk_flags = excluded.risk_flags,
                            content_hash = excluded.content_hash,
                            status = excluded.status,
                            last_seen_at = now()
                        returning id
                    """
                    cur.execute(
                        upsert_job_sql,
                        (
                            job.source_id,
                            job.external_id,
                            job.url,
                            job.title,
                            job.employer_name,
                            job.description,
                            job.language,
                            job.location_city,
                            job.location_country,
                            job.work_mode,
                            job.job_type,
                            job.eligibility,
                            job.eligibility_note,
                            job.deadline,
                            job.posted_at,
                            job.education_level,
                            job.experience_years_min,
                            job.apply_info,
                            job.risk_score,
                            job.risk_flags,
                            job.content_hash,
                            job.dedup_group_id,
                            job.is_canonical,
                            job.status,
                        ),
                    )
                    job_id = cur.fetchone()["id"]

                    # Skills
                    if job.skills:
                        cur.executemany(
                            """
                            insert into job_skills (job_id, skill)
                            values (%s, %s)
                            on conflict (job_id, skill) do nothing
                            """,
                            [(job_id, skill) for skill in job.skills],
                        )

                    # Mark raw item as processed
                    cur.execute(
                        "update job_raw set processed_at = now() where id = %s",
                        (job.raw_id,),
                    )

                processed_count += 1
                source_counts[source_slug] = source_counts.get(source_slug, 0) + 1
                total_skills += len(job.skills)
                if job.risk_score >= 30:
                    total_risky += 1

                # Live progress line for user feedback
                clean_t = (job.title[:38] + "..") if len(job.title) > 40 else job.title
                risk_tag = f" [RISK {job.risk_score}]" if job.risk_score >= 30 else ""
                print(f"[{idx:4d}/{total_rows}] [{source_slug:<16}] {clean_t:<40} ({len(job.skills)} skills){risk_tag}")

            except Exception as exc:
                print(f"[{idx:4d}/{total_rows}] [{source_slug}] ERROR on item {r['external_id']}: {exc}")

        if not dry_run:
            expire_past_deadlines(conn)

        print("\n" + "=" * 60)
        print("NORMALIZATION SUMMARY:")
        for src, cnt in sorted(source_counts.items()):
            print(f"  {src:<22}: {cnt:4d} jobs")
        print("-" * 60)
        print(f"Total Processed: {processed_count} jobs | Skills Linked: {total_skills} | Flagged: {total_risky}")
        print("=" * 60 + "\n")
        return processed_count


def main() -> None:
    parser = argparse.ArgumentParser(description="SIRALens Normalization Runner")
    parser.add_argument("--limit", type=int, default=None, help="Max jobs to process (default: all pending jobs)")
    parser.add_argument("--dry-run", action="store_true", help="Print extracted data without saving to DB")
    parser.add_argument("--source", type=str, default=None, help="Filter to a specific source slug")
    parser.add_argument("--force", action="store_true", help="Re-process already processed raw jobs")
    parser.add_argument("--stats", action="store_true", help="Show database counts and exit")
    args = parser.parse_args()

    load_env()
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("ERROR: DATABASE_URL is not set. Set it or put it in backend/.env", file=sys.stderr)
        sys.exit(1)

    if args.stats:
        print_stats(dsn)
        return

    process_batch(
        dsn,
        limit=args.limit,
        dry_run=args.dry_run,
        source_slug=args.source,
        force=args.force,
    )


if __name__ == "__main__":
    main()
