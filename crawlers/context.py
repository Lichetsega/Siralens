"""What an engine receives while crawling one source."""
from __future__ import annotations

from dataclasses import dataclass, field

from .fetcher import Fetcher, FetchResult
from .models import Source


@dataclass
class SourceState:
    """What we already know about a source (loaded from the database)."""

    known_ids: set[str] = field(default_factory=set)
    last_message_id: int | None = None  # Telegram only


class CrawlContext:
    def __init__(self, source: Source, fetcher: Fetcher, state: SourceState | None = None) -> None:
        self.source = source
        self.fetcher = fetcher
        self.state = state or SourceState()
        self.requests = 0
        self.problems: list[str] = []
        self.notes: list[str] = []

    def problem(self, msg: str) -> None:
        if msg not in self.problems and len(self.problems) < 50:
            self.problems.append(msg)

    def note(self, msg: str) -> None:
        self.notes.append(msg)

    async def get(self, url: str, **kw) -> FetchResult:
        kw.setdefault("respect_robots", self.source.respect_robots)
        kw.setdefault("delay", self.source.delay)
        res = await self.fetcher.get(url, **kw)
        self.requests += 1
        if not res.ok:
            self.problem(f"{url}: {res.error}")
        return res

    async def post_json(self, url: str, payload: dict, **kw) -> FetchResult:
        kw.setdefault("delay", self.source.delay)
        res = await self.fetcher.post_json(url, payload, **kw)
        self.requests += 1
        if not res.ok:
            self.problem(f"{url}: {res.error}")
        return res
