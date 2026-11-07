import asyncio

import httpx

from crawlers import runner
from crawlers.models import RawCapture
from crawlers.runner import crawl_source, decide_status
from crawlers.tests.conftest import make_fetcher, make_source


def test_decide_status():
    assert decide_status(5, []) == "ok"
    assert decide_status(5, ["x"]) == "partial"
    assert decide_status(0, []) == "empty"
    assert decide_status(0, ["x"]) == "failed"


def test_raw_capture_hash_ignores_whitespace_and_strips_nul():
    a = RawCapture("s", "1", "Hello   world\n\n")
    b = RawCapture("s", "1", "Hello world")
    assert a.content_hash == b.content_hash
    assert "\x00" not in RawCapture("s", "1", "a\x00b").raw_text


def test_one_crashing_engine_does_not_stop_the_run(monkeypatch):
    async def boom(ctx):
        raise RuntimeError("engine exploded")
        yield  # pragma: no cover

    async def fine(ctx):
        yield RawCapture("t", "1", "hello")

    monkeypatch.setitem(runner.ENGINES, "html", boom)
    monkeypatch.setitem(runner.ENGINES, "feed", fine)

    async def go():
        async with make_fetcher(lambda r: httpx.Response(200)) as f:
            return (await crawl_source(make_source(engine="html"), f),
                    await crawl_source(make_source(engine="feed"), f))

    bad, good = asyncio.run(go())
    assert bad.status == "failed" and "engine exploded" in bad.problems[0]
    assert good.status == "ok" and good.fetched == 1


def test_limit_and_empty_captures(monkeypatch):
    async def many(ctx):
        yield RawCapture("t", "0", "   ")  # empty: dropped
        for i in range(1, 10):
            yield RawCapture("t", str(i), f"job {i}")

    monkeypatch.setitem(runner.ENGINES, "html", many)

    async def go():
        async with make_fetcher(lambda r: httpx.Response(200)) as f:
            return await crawl_source(make_source(), f, limit=3)

    assert asyncio.run(go()).fetched == 3


def test_timeout_is_a_failure(monkeypatch):
    async def slow(ctx):
        await asyncio.sleep(5)
        yield RawCapture("t", "1", "x")

    monkeypatch.setitem(runner.ENGINES, "html", slow)

    async def go():
        async with make_fetcher(lambda r: httpx.Response(200)) as f:
            return await crawl_source(make_source(), f, timeout=0.1)

    r = asyncio.run(go())
    assert r.status == "failed" and "timed out" in r.problems[0]


def test_cli_list_and_check_without_database(capsys, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert runner.main(["--list"]) == 0
    assert "geezjobs" in capsys.readouterr().out
    assert runner.main(["--only", "nonexistent"]) == 2
    assert runner.main([]) == 2  # no DATABASE_URL and not --check
    assert "DATABASE_URL is not set" in capsys.readouterr().out
