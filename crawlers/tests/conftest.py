import httpx
import pytest

from crawlers.context import CrawlContext, SourceState
from crawlers.fetcher import Fetcher
from crawlers.models import Source


def make_source(**kw):
    base = dict(slug="t", name="T", kind="portal", engine="html", base_url="https://example.test/",
                wave=1, enabled=True, delay=0.0, respect_robots=True, options={})
    base.update(kw)
    return Source(**base)


def make_fetcher(handler, **kw):
    return Fetcher(transport=httpx.MockTransport(handler), default_delay=0.0, backoff=0.01, **kw)


async def collect(engine, source, handler, state=None):
    """Run an engine against a fake site. Returns (captures, ctx, requested_paths)."""
    requested = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path + (("?" + request.url.query.decode()) if request.url.query else ""))
        return handler(request)

    async with make_fetcher(wrapped) as fetcher:
        ctx = CrawlContext(source, fetcher, state or SourceState())
        out = [c async for c in engine(ctx)]
    return out, ctx, requested
