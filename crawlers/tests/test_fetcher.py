import asyncio
import time

import httpx

from crawlers.fetcher import Fetcher, USER_AGENT
from crawlers.tests.conftest import make_fetcher


def test_robots_blocking_and_user_agent():
    seen_ua = []

    def handler(req):
        seen_ua.append(req.headers["user-agent"])
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        return httpx.Response(200, text="hi")

    async def go():
        async with make_fetcher(handler) as f:
            return await f.get("https://a.test/private/x"), await f.get("https://a.test/ok"), \
                await f.get("https://a.test/private/x", respect_robots=False)

    blocked, ok, forced = asyncio.run(go())
    assert blocked.blocked and not blocked.ok and blocked.error == "blocked by robots.txt"
    assert ok.ok and forced.ok
    assert set(seen_ua) == {USER_AGENT} and "SIRALensBot" in USER_AGENT


def test_robots_404_means_allowed_and_is_cached():
    calls = []

    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(200, text="x")

    async def go():
        async with make_fetcher(handler) as f:
            return [await f.get(f"https://a.test/p{i}") for i in range(3)]

    assert all(r.ok for r in asyncio.run(go()))
    assert calls.count("/robots.txt") == 1


def test_retries_503_then_succeeds_and_gives_up_on_404():
    state = {"n": 0}

    def handler(req):
        if req.url.path == "/flaky":
            state["n"] += 1
            return httpx.Response(503) if state["n"] < 3 else httpx.Response(200, text="ok")
        return httpx.Response(404)

    async def go():
        async with make_fetcher(handler) as f:
            return await f.get("https://a.test/flaky", respect_robots=False), \
                await f.get("https://a.test/missing", respect_robots=False)

    flaky, missing = asyncio.run(go())
    assert flaky.ok and state["n"] == 3
    assert not missing.ok and missing.status == 404 and missing.error == "HTTP 404"


def test_network_error_is_reported_not_raised():
    def handler(req):
        raise httpx.ConnectError("boom")

    async def go():
        async with make_fetcher(handler) as f:
            return await f.get("https://a.test/x", respect_robots=False)

    res = asyncio.run(go())
    assert not res.ok and "ConnectError" in res.error


def test_same_host_requests_are_spaced():
    def handler(req):
        return httpx.Response(200, text="x")

    async def go():
        f = Fetcher(transport=httpx.MockTransport(handler), default_delay=0.2)
        async with f:
            t0 = time.monotonic()
            await asyncio.gather(*(f.get(f"https://a.test/{i}", respect_robots=False) for i in range(3)))
            return time.monotonic() - t0

    assert asyncio.run(go()) >= 0.38  # three requests, 0.2s apart


def test_response_size_is_capped():
    def handler(req):
        return httpx.Response(200, content=b"x" * 50_000)

    async def go():
        async with make_fetcher(handler, max_bytes=10_000) as f:
            return await f.get("https://a.test/big", respect_robots=False)

    assert len(asyncio.run(go()).text) < 50_000
