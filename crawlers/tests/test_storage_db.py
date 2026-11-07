"""
Integration tests against a REAL Postgres. Skipped unless TEST_DATABASE_URL is set.
Use a throwaway database that already has job_sources, job_raw and crawl_runs
(db/migrations 0001 and 0002). Never point this at your real Supabase database.
"""
import asyncio
import os

import httpx
import pytest

psycopg = pytest.importorskip("psycopg")
DSN = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="set TEST_DATABASE_URL to a throwaway Postgres to run")

from crawlers import runner, storage  # noqa: E402
from crawlers.models import RawCapture  # noqa: E402
from crawlers.tests.conftest import make_source  # noqa: E402


@pytest.fixture()
def db():
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("truncate crawl_runs, job_raw, job_sources restart identity cascade")
        c.execute("alter table job_raw drop constraint if exists no_bad")
        c.execute("alter table job_raw add constraint no_bad check (external_id <> 'BAD')")
        yield c


def rows(db, sql, *a):
    return db.execute(sql, a).fetchall()


def test_sync_sources_upserts_and_updates_enabled(db):
    s = make_source(slug="geez", name="Geez", enabled=True)
    ids = storage.sync_sources(DSN, [s])
    s.enabled, s.name = False, "Geez 2"
    assert storage.sync_sources(DSN, [s]) == ids  # same id
    assert rows(db, "select name, enabled, source_type from job_sources") == [("Geez 2", False, "portal")]


def test_save_new_unchanged_changed_and_bad_row_isolation(db):
    sid = storage.sync_sources(DSN, [make_source(slug="g")])["g"]
    first = [RawCapture("g", "a", "text a", "https://x/a", {"k": "v"}), RawCapture("g", "BAD", "boom"),
             RawCapture("g", "b", "text b")]
    c1 = storage.save_captures(DSN, sid, first)
    assert (c1["new"], c1["failed"]) == (2, 1) and "BAD" in c1["errors"][0]   # rows after the bad one still saved
    assert sorted(r[0] for r in rows(db, "select external_id from job_raw")) == ["a", "b"]

    c2 = storage.save_captures(DSN, sid, [RawCapture("g", "a", "text a"), RawCapture("g", "b", "text b CHANGED")])
    assert (c2["new"], c2["unchanged"], c2["changed"]) == (0, 1, 1)
    assert rows(db, "select raw_text from job_raw where external_id='b'") == [("text b CHANGED",)]
    assert rows(db, "select raw_meta->>'k' from job_raw where external_id='a'") == [("v",)]


def test_load_state_known_ids_and_telegram_last_id(db):
    sid = storage.sync_sources(DSN, [make_source(slug="t", engine="telegram", kind="telegram")])["t"]
    storage.save_captures(DSN, sid, [RawCapture("t", "chan/101", "x"), RawCapture("t", "chan/99", "y"),
                                     RawCapture("t", "chan/abc", "z")])
    st = storage.load_state(DSN, sid, "telegram")
    assert st.known_ids == {"chan/101", "chan/99", "chan/abc"} and st.last_message_id == 101
    assert storage.load_state(DSN, sid, "html").last_message_id is None


def test_log_run_updates_source_health(db):
    sid = storage.sync_sources(DSN, [make_source(slug="g")])["g"]
    storage.log_run(DSN, sid, "ok", 3, {"new": 2, "changed": 1, "unchanged": 0}, 9, [], 1.5)
    storage.log_run(DSN, sid, "failed", 0, {}, 2, ["blocked by robots.txt"], 0.2)
    assert rows(db, "select last_status, last_success_at is not null from job_sources") == [("failed", True)]
    assert rows(db, "select status, new_count, problems->>0 from crawl_runs order by id") == [
        ("ok", 2, None), ("failed", 0, "blocked by robots.txt")]


def test_end_to_end_run_twice(db, monkeypatch):
    """Full path: sources.yaml-style source -> engine -> database. Second run must fetch nothing new."""
    job = ('<html><head><script type="application/ld+json">{"@type":"JobPosting","title":"%s",'
           '"hiringOrganization":{"name":"Acme"},"description":"' + "Duties and requirements. " * 6 + '"}</script></head></html>')

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path == "/jobs":
            return httpx.Response(200, text='<a href="/job-detail/one">1</a><a href="/job-detail/two">2</a>')
        if req.url.path.startswith("/job-detail/"):
            return httpx.Response(200, text=job % req.url.path.rsplit("/", 1)[-1].title())
        return httpx.Response(404)

    real = runner.Fetcher
    monkeypatch.setattr(runner, "Fetcher", lambda: real(transport=httpx.MockTransport(handler), default_delay=0.0))
    src = make_source(slug="e2e", options={"discovery": {"list_urls": ["https://example.test/jobs"],
                                                         "link_pattern": "/job-detail/", "robots_sitemaps": False}})

    def go():
        return asyncio.run(runner.run_all([src], dsn=DSN, check=False, concurrency=2, limit=None, timeout=30))[0]

    r1 = go()
    assert (r1.status, r1.fetched, r1.new) == ("ok", 2, 2)
    r2 = go()
    assert (r2.status, r2.fetched, r2.requests) == ("empty", 0, 1)  # only the list page was requested
    assert rows(db, "select count(*) from job_raw") == [(2,)]
    assert rows(db, "select status from crawl_runs order by id") == [("ok",), ("empty",)]
    assert rows(db, "select last_status from job_sources where slug='e2e'") == [("empty",)]
