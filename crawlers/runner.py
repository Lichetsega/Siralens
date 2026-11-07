"""
Crawl runner. Reads sources.yaml and loops over every enabled source.

    python -m crawlers.runner --list                    show all sources
    python -m crawlers.runner --check geezjobs          dry run: no database, prints what it found
    python -m crawlers.runner                           crawl every enabled source, save to the database
    python -m crawlers.runner --only geezjobs hahu      crawl only these
    python -m crawlers.runner --sync                    just copy sources.yaml into the job_sources table

Run it from the project root (the folder that contains backend/ and crawlers/).
Needs DATABASE_URL (from backend/.env or the environment) unless you use --list or --check.
This is a one-shot command: schedule it with cron / Task Scheduler / a CI schedule. There is no sleeping loop.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import ConfigError, load_sources
from .context import CrawlContext, SourceState
from .engines import ENGINES
from .fetcher import Fetcher
from .models import RawCapture, Source


@dataclass
class SourceResult:
    slug: str
    status: str  # ok | empty | partial | failed
    fetched: int = 0
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    save_failed: int = 0
    requests: int = 0
    seconds: float = 0.0
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    captures: list[RawCapture] = field(default_factory=list)


def decide_status(n_captures: int, problems: list[str]) -> str:
    """ok = got items; partial = got items but had problems; empty = nothing new, no problems;
    failed = nothing and problems."""
    if n_captures == 0:
        return "failed" if problems else "empty"
    return "partial" if problems else "ok"


async def crawl_source(source: Source, fetcher: Fetcher, state: SourceState | None = None, *,
                       limit: int | None = None, timeout: float = 900.0) -> SourceResult:
    ctx = CrawlContext(source, fetcher, state)
    captures: list[RawCapture] = []
    started = time.monotonic()

    async def collect() -> None:
        async with contextlib.aclosing(ENGINES[source.engine](ctx)) as gen:
            async for cap in gen:
                if cap.is_empty():
                    continue
                captures.append(cap)
                if limit and len(captures) >= limit:
                    break

    try:
        await asyncio.wait_for(collect(), timeout=timeout)
    except asyncio.TimeoutError:
        ctx.problem(f"timed out after {int(timeout)}s")
    except Exception as exc:  # noqa: BLE001 - one source must never stop the others
        ctx.problem(f"{type(exc).__name__}: {exc}")

    return SourceResult(
        slug=source.slug, status=decide_status(len(captures), ctx.problems), fetched=len(captures),
        requests=ctx.requests, seconds=time.monotonic() - started, problems=ctx.problems,
        notes=ctx.notes, captures=captures,
    )


def _persist(dsn: str, source_id: int, result: SourceResult) -> None:
    from . import storage
    counts = storage.save_captures(dsn, source_id, result.captures) if result.captures else {}
    result.new = counts.get("new", 0)
    result.changed = counts.get("changed", 0)
    result.unchanged = counts.get("unchanged", 0)
    result.save_failed = counts.get("failed", 0)
    result.problems.extend(f"save: {e}" for e in counts.get("errors", []))
    try:
        storage.log_run(dsn, source_id, result.status, result.fetched, counts, result.requests,
                        result.problems, result.seconds)
    except Exception as exc:  # noqa: BLE001
        result.problems.append(f"could not log run (did you run db/migrations/0002_crawl_runs.sql?): {exc}")


async def run_all(sources: list[Source], *, dsn: str | None, check: bool, concurrency: int, limit: int | None,
                  timeout: float) -> list[SourceResult]:
    from . import storage
    ids: dict[str, int] = {}
    if dsn and not check:
        ids = await asyncio.to_thread(storage.sync_sources, dsn, sources)
    sem = asyncio.Semaphore(concurrency)

    async with Fetcher() as fetcher:
        async def one(src: Source) -> SourceResult:
            async with sem:
                state = SourceState()
                if dsn and not check:
                    state = await asyncio.to_thread(storage.load_state, dsn, ids[src.slug], src.engine)
                print(f"-> {src.slug}", flush=True)
                result = await crawl_source(src, fetcher, state, limit=limit, timeout=timeout)
                if dsn and not check:
                    await asyncio.to_thread(_persist, dsn, ids[src.slug], result)
                print(f"   {src.slug}: {result.status} ({result.fetched} fetched)", flush=True)
                return result

        return list(await asyncio.gather(*(one(s) for s in sources)))


# ------------------------------------------------------------------ output
def print_sources(sources: list[Source]) -> None:
    print(f"{'slug':<20}{'engine':<11}{'kind':<10}{'wave':<5}{'enabled':<8}name")
    for s in sources:
        print(f"{s.slug:<20}{s.engine:<11}{s.kind:<10}{s.wave:<5}{'yes' if s.enabled else 'no':<8}{s.name}")


def print_summary(results: list[SourceResult], check: bool) -> None:
    print("\n" + "=" * 78)
    print(f"{'source':<20}{'status':<9}{'fetched':>8}{'new':>6}{'chg':>5}{'same':>6}{'reqs':>6}{'sec':>7}")
    for r in results:
        print(f"{r.slug:<20}{r.status:<9}{r.fetched:>8}{r.new:>6}{r.changed:>5}{r.unchanged:>6}"
              f"{r.requests:>6}{r.seconds:>7.1f}")
    for r in results:
        if r.notes or r.problems:
            print(f"\n[{r.slug}]")
            for n in r.notes:
                print(f"  note:    {n}")
            for p in r.problems[:10]:
                print(f"  PROBLEM: {p}")
            if len(r.problems) > 10:
                print(f"  ... and {len(r.problems) - 10} more problems")
        if check:
            for c in r.captures[:2]:
                print(f"  sample:  {c.url or c.external_id}  [{c.raw_meta.get('extraction', '?')}]")
                print("           " + c.raw_text[:300].replace("\n", "\n           "))
    print("\nstatus: ok = items found | partial = items found with problems | "
          "empty = nothing new | failed = nothing and problems")


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = Path(__file__).resolve().parents[1]
    for p in (root / ".env", root / "backend" / ".env", Path(__file__).parent / ".env"):
        if p.exists():
            load_dotenv(p, override=False)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Amharic text must not crash a Windows console
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    _load_env()

    ap = argparse.ArgumentParser(description="SIRALens crawl runner")
    ap.add_argument("--only", nargs="+", metavar="SLUG", help="crawl only these sources")
    ap.add_argument("--check", nargs="*", metavar="SLUG", help="dry run (no database); optionally name sources, even disabled ones")
    ap.add_argument("--list", action="store_true", help="list sources and exit")
    ap.add_argument("--sync", action="store_true", help="copy sources.yaml into the database and exit")
    ap.add_argument("--limit", type=int, default=None, help="stop each source after N items (default 5 with --check)")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=900.0, help="seconds allowed per source")
    ap.add_argument("--sources", default=None, help="path to a different sources.yaml")
    args = ap.parse_args(argv)

    try:
        sources = load_sources(args.sources)
    except ConfigError as exc:
        print(exc)
        return 2

    if args.list:
        print_sources(sources)
        return 0

    check = args.check is not None
    names = args.check if check and args.check else args.only
    if names:
        unknown = [n for n in names if n not in {s.slug for s in sources}]
        if unknown:
            print(f"Unknown source(s): {unknown}. Use --list to see them.")
            return 2
        selected = [s for s in sources if s.slug in names and (check or s.enabled)]
        skipped = [s.slug for s in sources if s.slug in names and not s.enabled and not check]
        if skipped:
            print(f"Skipping disabled source(s): {skipped} (set enabled: true in sources.yaml)")
    else:
        selected = [s for s in sources if s.enabled]

    dsn = os.getenv("DATABASE_URL", "").strip() or None
    if args.sync:
        if not dsn:
            print("DATABASE_URL is not set.")
            return 2
        from . import storage
        ids = storage.sync_sources(dsn, sources)
        print(f"Synced {len(ids)} sources to the database.")
        return 0
    if not check and not dsn:
        print("DATABASE_URL is not set (put it in backend/.env). Use --check for a dry run without a database.")
        return 2
    if not selected:
        print("Nothing to crawl. Enable sources in sources.yaml or name them with --only.")
        return 0

    limit = args.limit if args.limit is not None else (5 if check else None)
    results = asyncio.run(run_all(selected, dsn=dsn, check=check, concurrency=args.concurrency,
                                  limit=limit, timeout=args.timeout))
    print_summary(results, check)
    return 1 if all(r.status == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
