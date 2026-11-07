"""
Polite HTTP client shared by all engines.

- Honest, identifiable User-Agent.
- Checks robots.txt (cached per site) and honours Crawl-delay.
- Waits `delay` seconds between requests to the same host, across all sources.
- Retries timeouts, network errors and 429/5xx with backoff.
- Caps response size.
"""
from __future__ import annotations

import asyncio
import json as _json
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "SIRALensBot/0.1 (+https://github.com/Lichetsega/Siralens)"
_RETRY_STATUS = (429, 500, 502, 503, 504)


@dataclass
class FetchResult:
    url: str
    status: int | None = None
    text: str = ""
    content_type: str = ""
    error: str | None = None
    blocked: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None and self.status is not None and 200 <= self.status < 300

    def json(self):
        return _json.loads(self.text)


@dataclass
class _Robots:
    parser: RobotFileParser | None = None
    crawl_delay: float | None = None


class Fetcher:
    def __init__(
        self,
        *,
        user_agent: str = USER_AGENT,
        timeout: float = 40.0,
        max_bytes: int = 3_000_000,
        retries: int = 2,
        backoff: float = 2.0,
        default_delay: float = 2.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.retries = retries
        self.backoff = backoff
        self.default_delay = default_delay
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._next_ok: dict[str, float] = {}
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._robots: dict[str, _Robots] = {}
        self._robots_locks: dict[str, asyncio.Lock] = {}

    async def __aenter__(self) -> "Fetcher":
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml,application/json;q=0.9,*/*;q=0.8",
            },
            timeout=httpx.Timeout(self.timeout),
            follow_redirects=True,
            transport=self._transport,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------ public
    async def get(self, url: str, *, respect_robots: bool = True, delay: float | None = None,
                  params: dict | None = None, headers: dict | None = None) -> FetchResult:
        delay = self.default_delay if delay is None else delay
        if respect_robots:
            parts = urlparse(url)
            info = await self._robots_for(f"{parts.scheme}://{parts.netloc}", delay)
            if info.parser is not None and not info.parser.can_fetch(self.user_agent, url):
                return FetchResult(url=url, error="blocked by robots.txt", blocked=True)
            if info.crawl_delay:
                delay = max(delay, min(info.crawl_delay, 30.0))
        return await self._request("GET", url, params=params, payload=None, headers=headers, delay=delay)

    async def post_json(self, url: str, payload: dict, *, delay: float | None = None,
                        params: dict | None = None, headers: dict | None = None) -> FetchResult:
        """POST a JSON body (used for documented APIs, so robots.txt is not consulted)."""
        delay = self.default_delay if delay is None else delay
        return await self._request("POST", url, params=params, payload=payload, headers=headers, delay=delay)

    # ------------------------------------------------------------ internals
    async def _wait_turn(self, host: str, delay: float) -> None:
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            loop = asyncio.get_running_loop()
            wait = self._next_ok.get(host, 0.0) - loop.time()
            if wait > 0:
                await asyncio.sleep(wait)
            self._next_ok[host] = loop.time() + delay

    async def _robots_for(self, origin: str, delay: float) -> _Robots:
        lock = self._robots_locks.setdefault(origin, asyncio.Lock())
        async with lock:
            if origin in self._robots:
                return self._robots[origin]
            res = await self._request("GET", origin + "/robots.txt", params=None, payload=None,
                                      headers=None, delay=delay)
            info = _Robots()
            if res.ok:
                rp = RobotFileParser()
                rp.parse(res.text.splitlines())
                info.parser = rp
                cd = rp.crawl_delay(self.user_agent)
                info.crawl_delay = float(cd) if cd else None
            # 4xx = no restrictions; unreachable = proceed (polite delay still applies)
            self._robots[origin] = info
            return info

    @staticmethod
    def _retry_after(resp: httpx.Response) -> float | None:
        value = resp.headers.get("retry-after", "")
        return float(value) if value.isdigit() else None

    async def _read_limited(self, resp: httpx.Response) -> bytes:
        chunks, size = [], 0
        async for chunk in resp.aiter_bytes():
            chunks.append(chunk)
            size += len(chunk)
            if size > self.max_bytes:
                break
        return b"".join(chunks)[: self.max_bytes]

    async def _request(self, method: str, url: str, *, params, payload, headers, delay: float) -> FetchResult:
        assert self._client is not None, "use 'async with Fetcher()'"
        host = urlparse(url).netloc
        last_error = "request failed"
        for attempt in range(self.retries + 1):
            await self._wait_turn(host, delay)
            try:
                req = self._client.build_request(method, url, params=params, json=payload, headers=headers)
                resp = await self._client.send(req, stream=True)
                try:
                    body = await self._read_limited(resp)
                finally:
                    await resp.aclose()
                result = FetchResult(
                    url=str(resp.url),
                    status=resp.status_code,
                    text=body.decode(resp.encoding or "utf-8", errors="replace"),
                    content_type=resp.headers.get("content-type", ""),
                )
                if resp.status_code in _RETRY_STATUS and attempt < self.retries:
                    last_error = f"HTTP {resp.status_code}"
                    await asyncio.sleep(min(self._retry_after(resp) or self.backoff * (2 ** attempt), 30.0))
                    continue
                if not 200 <= resp.status_code < 300:
                    result.error = f"HTTP {resp.status_code}"
                return result
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.retries:
                    await asyncio.sleep(self.backoff * (2 ** attempt))
        return FetchResult(url=url, error=last_error)
