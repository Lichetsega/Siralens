"""Shared data types."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

KINDS = ("portal", "telegram", "ngo", "api", "employer")  # matches job_sources.source_type
ENGINE_NAMES = ("html", "feed", "telegram", "json_api", "reliefweb")

_WS = re.compile(r"\s+")


@dataclass
class RawCapture:
    """One raw job item as found at a source. Maps onto a job_raw row."""

    source_slug: str
    external_id: str
    raw_text: str
    url: str | None = None
    raw_meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.raw_text = (self.raw_text or "").replace("\x00", "")  # Postgres rejects NUL

    @property
    def content_hash(self) -> str:
        norm = _WS.sub(" ", self.raw_text).strip()
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()

    def is_empty(self) -> bool:
        return not self.raw_text.strip()


@dataclass
class Source:
    """One entry of sources.yaml."""

    slug: str
    name: str
    kind: str
    engine: str
    base_url: str
    wave: int = 2
    enabled: bool = False
    delay: float = 2.0
    respect_robots: bool = True
    options: dict[str, Any] = field(default_factory=dict)

    def opt(self, key: str, default: Any = None) -> Any:
        return self.options.get(key, default)
