"""Database side. Every function opens its own short connection, so it is safe to call from threads."""
from __future__ import annotations

import psycopg
from psycopg.types.json import Jsonb

from .context import SourceState
from .models import RawCapture, Source

_SYNC = """
insert into job_sources (slug, name, source_type, base_url, wave, enabled)
values (%s, %s, %s, %s, %s, %s)
on conflict (slug) do update set
  name = excluded.name, source_type = excluded.source_type, base_url = excluded.base_url,
  wave = excluded.wave, enabled = excluded.enabled
returning id
"""

_UPSERT = """
insert into job_raw (source_id, external_id, url, raw_text, raw_meta, content_hash)
values (%s, %s, %s, %s, %s, %s)
on conflict (source_id, external_id) do update set
  url = excluded.url, raw_text = excluded.raw_text, raw_meta = excluded.raw_meta,
  content_hash = excluded.content_hash, fetched_at = now(), processed_at = null
where job_raw.content_hash is distinct from excluded.content_hash
returning (xmax = 0) as inserted
"""


def connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, prepare_threshold=None)  # compatible with Supabase poolers


def sync_sources(dsn: str, sources: list[Source]) -> dict[str, int]:
    """Make the job_sources table mirror sources.yaml. Returns slug -> id."""
    ids: dict[str, int] = {}
    with connect(dsn) as conn, conn.cursor() as cur:
        for s in sources:
            cur.execute(_SYNC, (s.slug, s.name, s.kind, s.base_url, s.wave, s.enabled))
            ids[s.slug] = cur.fetchone()[0]
    return ids


def load_state(dsn: str, source_id: int, engine: str) -> SourceState:
    with connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("select external_id from job_raw where source_id = %s order by fetched_at desc limit 5000",
                    (source_id,))
        state = SourceState(known_ids={r[0] for r in cur.fetchall()})
        if engine == "telegram":
            cur.execute(
                "select max(regexp_replace(external_id, '^.*/', '')::bigint) from job_raw "
                "where source_id = %s and external_id ~ '/[0-9]+$'", (source_id,))
            state.last_message_id = cur.fetchone()[0]
    return state


def save_captures(dsn: str, source_id: int, captures: list[RawCapture]) -> dict:
    """Insert or update each item on its own savepoint, so one bad row never ruins the rest."""
    counts = {"new": 0, "changed": 0, "unchanged": 0, "failed": 0, "errors": []}
    with connect(dsn) as conn, conn.cursor() as cur:
        for c in captures:
            try:
                with conn.transaction():
                    cur.execute(_UPSERT, (source_id, c.external_id[:255], c.url, c.raw_text,
                                          Jsonb(c.raw_meta), c.content_hash))
                    row = cur.fetchone()
                if row is None:
                    counts["unchanged"] += 1
                elif row[0]:
                    counts["new"] += 1
                else:
                    counts["changed"] += 1
            except Exception as exc:  # noqa: BLE001 - report and continue
                counts["failed"] += 1
                if len(counts["errors"]) < 5:
                    counts["errors"].append(f"{c.external_id}: {exc}")
    return counts


def log_run(dsn: str, source_id: int, status: str, fetched: int, counts: dict, requests: int,
            problems: list[str], seconds: float) -> None:
    from psycopg.types.json import Jsonb as J
    with connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "insert into crawl_runs (source_id, finished_at, status, fetched, new_count, changed_count, "
            "unchanged_count, requests, seconds, problems) values (%s, now(), %s, %s, %s, %s, %s, %s, %s, %s)",
            (source_id, status, fetched, counts.get("new", 0), counts.get("changed", 0),
             counts.get("unchanged", 0), requests, round(seconds, 1), J(problems[:20])))
        cur.execute(
            "update job_sources set last_crawled_at = now(), last_status = %s, "
            "last_success_at = case when %s in ('ok', 'partial') then now() else last_success_at end "
            "where id = %s", (status, status, source_id))
