"""Loads and validates sources.yaml (the single list of everything we crawl)."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .models import ENGINE_NAMES, KINDS, Source

DEFAULT_PATH = Path(__file__).with_name("sources.yaml")
_TOP_LEVEL = {"slug", "name", "kind", "engine", "base_url", "wave", "enabled", "delay", "respect_robots"}
_SLUG_RE = re.compile(r"^[a-z0-9_]+$")


class ConfigError(Exception):
    pass


def _check_engine_options(src: Source, problems: list[str]) -> None:
    """Engine-specific required options. Only enforced for enabled sources (disabled ones may be stubs)."""
    if not src.enabled:
        return
    o, tag = src.options, f"[{src.slug}]"
    if src.engine == "telegram" and not o.get("channel"):
        problems.append(f"{tag} engine 'telegram' needs 'channel'")
    elif src.engine == "feed" and not o.get("feed_urls"):
        problems.append(f"{tag} engine 'feed' needs 'feed_urls'")
    elif src.engine == "json_api":
        for key in ("url", "items_path", "fields"):
            if not o.get(key):
                problems.append(f"{tag} engine 'json_api' needs '{key}'")
        if o.get("fields") is not None and not isinstance(o.get("fields"), dict):
            problems.append(f"{tag} 'fields' must be a mapping")
    elif src.engine == "html":
        disc = o.get("discovery") or {}
        if not isinstance(disc, dict):
            problems.append(f"{tag} 'discovery' must be a mapping")


def parse_sources(data: dict) -> list[Source]:
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        raise ConfigError("sources.yaml must contain a top-level 'sources:' list")
    defaults = data.get("defaults") or {}
    problems: list[str] = []
    out: list[Source] = []
    seen: set[str] = set()

    for i, raw in enumerate(data["sources"], start=1):
        if not isinstance(raw, dict):
            problems.append(f"entry #{i}: must be a mapping")
            continue
        merged = {**defaults, **raw}
        slug = str(merged.get("slug", "")).strip()
        tag = f"[{slug or '#' + str(i)}]"
        for req in ("slug", "name", "kind", "engine", "base_url"):
            if not merged.get(req):
                problems.append(f"{tag} missing required field '{req}'")
        if not slug:
            continue
        if not _SLUG_RE.match(slug):
            problems.append(f"{tag} slug must be lowercase letters, digits or underscore")
        if slug in seen:
            problems.append(f"{tag} duplicate slug")
        seen.add(slug)
        if merged.get("kind") not in KINDS:
            problems.append(f"{tag} kind must be one of {KINDS}")
        if merged.get("engine") not in ENGINE_NAMES:
            problems.append(f"{tag} engine must be one of {ENGINE_NAMES}")
        try:
            wave = int(merged.get("wave", 2))
            delay = float(merged.get("delay", 2.0))
            if delay < 0:
                raise ValueError
        except (TypeError, ValueError):
            problems.append(f"{tag} 'wave' must be an integer and 'delay' a non-negative number")
            continue

        src = Source(
            slug=slug,
            name=str(merged.get("name", slug)),
            kind=str(merged.get("kind", "")),
            engine=str(merged.get("engine", "")),
            base_url=str(merged.get("base_url", "")),
            wave=wave,
            enabled=bool(merged.get("enabled", False)),
            delay=delay,
            respect_robots=bool(merged.get("respect_robots", True)),
            options={k: v for k, v in merged.items() if k not in _TOP_LEVEL},
        )
        _check_engine_options(src, problems)
        out.append(src)

    if problems:
        raise ConfigError("sources.yaml has problems:\n  - " + "\n  - ".join(problems))
    return out


def load_sources(path: str | Path | None = None) -> list[Source]:
    p = Path(path) if path else DEFAULT_PATH
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"sources file not found: {p}")
    except yaml.YAMLError as e:
        raise ConfigError(f"{p.name} is not valid YAML: {e}")
    return parse_sources(data)
