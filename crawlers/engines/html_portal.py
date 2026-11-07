"""
Engine 'html': any job website with detail pages. Fully driven by sources.yaml.

  1. DISCOVER job-page URLs from list pages, sitemaps and/or robots.txt sitemaps
  2. skip URLs we already know
  3. FETCH each new job page and EXTRACT it (JSON-LD first, generic text otherwise)

Source options (all under the source entry in sources.yaml):
  discovery:
    list_urls:    [urls; "{page}" is replaced with 1, 2, 3 ...]
    sitemaps:     [sitemap urls]
    robots_sitemaps: true         # also use Sitemap: lines from robots.txt (default true)
    link_pattern: regex that a job-page URL must match (default: /jobs/<slug>, /job-detail/<slug>, ...)
    exclude_pattern: regex for URLs to skip
    sitemap_child_pattern: only follow child sitemaps whose URL matches this regex
    max_pages: 5, max_urls: 400, max_sitemaps: 6
  css:            optional overrides {title, employer, location, deadline, job_type, apply, body}
  max_details: 60       pages fetched per run (be polite; raise for the first big crawl)
  skip_known: true      do not re-fetch URLs already stored
  skip_expired: true    do not store pages that say the job is closed
"""
from __future__ import annotations

import contextlib
import html as _html
import re
from typing import AsyncIterator

from ..context import CrawlContext
from ..extract import (DEFAULT_LINK_PATTERN, compose_raw_text, extract_job_page, extract_links, is_candidate,
                       looks_expired, meta_from_fields, normalize_url)
from ..models import RawCapture

_SITEMAP_BLOCK = re.compile(r"<(url|sitemap)>(.*?)</\1>", re.S | re.I)
_LOC = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.S | re.I)
_LASTMOD = re.compile(r"<lastmod>\s*(.*?)\s*</lastmod>", re.S | re.I)


def parse_sitemap(xml: str) -> tuple[bool, list[tuple[str, str]]]:
    """-> (is_index, [(url, lastmod), ...])"""
    is_index = "<sitemapindex" in xml.lower()
    entries = []
    for _, block in _SITEMAP_BLOCK.findall(xml):
        loc = _LOC.search(block)
        if loc:
            lm = _LASTMOD.search(block)
            entries.append((_html.unescape(loc.group(1)), lm.group(1) if lm else ""))
    return is_index, entries


async def _robots_sitemaps(ctx: CrawlContext) -> list[str]:
    from urllib.parse import urlparse
    p = urlparse(ctx.source.base_url)
    res = await ctx.get(f"{p.scheme}://{p.netloc}/robots.txt", respect_robots=False)
    if not res.ok:
        return []
    return [line.split(":", 1)[1].strip() for line in res.text.splitlines()
            if line.lower().startswith("sitemap:") and line.split(":", 1)[1].strip()]


async def _from_sitemap(ctx, url, disc, pattern, exclude, add, depth=0) -> None:
    if url.lower().endswith(".gz"):
        ctx.problem(f"{url}: compressed sitemaps (.gz) are not supported")
        return
    res = await ctx.get(url)
    if not res.ok:
        return
    is_index, entries = parse_sitemap(res.text)
    if is_index:
        if depth >= 2:
            return
        child_re = re.compile(disc["sitemap_child_pattern"], re.I) if disc.get("sitemap_child_pattern") else None
        children = [e for e in entries if not child_re or child_re.search(e[0])]
        children.sort(key=lambda e: e[1], reverse=True)
        for child_url, _ in children[: int(disc.get("max_sitemaps", 6))]:
            await _from_sitemap(ctx, child_url, disc, pattern, exclude, add, depth + 1)
        return
    for loc, _ in sorted(entries, key=lambda e: e[1], reverse=True):  # newest first
        if is_candidate(loc, ctx.source.base_url, pattern, exclude):
            add(loc)


async def _from_list(ctx, template, disc, pattern, exclude, add, seen) -> None:
    paged = "{page}" in template
    max_pages = int(disc.get("max_pages", 5)) if paged else 1
    for page in range(1, max_pages + 1):
        url = template.replace("{page}", str(page))
        res = await ctx.get(url)
        if not res.ok:
            return
        fresh = 0
        for link in extract_links(res.text, res.url):
            if link not in seen and is_candidate(link, ctx.source.base_url, pattern, exclude):
                add(link)
                fresh += 1
        if fresh == 0:
            return


async def discover(ctx: CrawlContext) -> list[str]:
    disc = ctx.source.opt("discovery") or {}
    pattern = re.compile(disc.get("link_pattern") or DEFAULT_LINK_PATTERN, re.I)
    exclude = re.compile(disc["exclude_pattern"], re.I) if disc.get("exclude_pattern") else None
    max_urls = int(disc.get("max_urls", 400))
    seen: dict[str, None] = {}

    def add(u: str) -> None:
        if len(seen) < max_urls:
            seen.setdefault(normalize_url(u), None)

    sitemaps = list(disc.get("sitemaps") or [])
    if disc.get("robots_sitemaps", True):
        sitemaps += [s for s in await _robots_sitemaps(ctx) if s not in sitemaps]
    for tpl in disc.get("list_urls") or []:
        await _from_list(ctx, tpl, disc, pattern, exclude, add, seen)
    for sm in sitemaps:
        await _from_sitemap(ctx, sm, disc, pattern, exclude, add)
    return list(seen)


async def run(ctx: CrawlContext) -> AsyncIterator[RawCapture]:
    src = ctx.source
    urls = await discover(ctx)
    if not urls:
        ctx.problem("no job links found: check discovery.list_urls / sitemaps / link_pattern in sources.yaml")
        return
    known = ctx.state.known_ids if src.opt("skip_known", True) else set()
    todo = [u for u in urls if u not in known][: int(src.opt("max_details", 60))]
    ctx.note(f"{len(urls)} job links found, {len(urls) - len([u for u in urls if u not in known])} already known, "
             f"fetching {len(todo)}")

    skipped_expired = skipped_empty = 0
    for u in todo:
        res = await ctx.get(u)
        if not res.ok:
            continue
        fields = extract_job_page(res.text, res.url, src.opt("css"))
        if not fields.get("title") and len(fields.get("description", "")) < 100:
            skipped_empty += 1
            continue
        if src.opt("skip_expired", True) and looks_expired(fields):
            skipped_expired += 1
            continue
        yield RawCapture(source_slug=src.slug, external_id=u[:255], raw_text=compose_raw_text(fields),
                         url=res.url, raw_meta=meta_from_fields(fields))
    if skipped_expired or skipped_empty:
        ctx.note(f"skipped {skipped_expired} expired and {skipped_empty} empty pages")
