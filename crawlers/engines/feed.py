"""
Engine 'feed': RSS / Atom feeds (including WordPress /feed/). Standard library only.

Source options:
  feed_urls: [urls; "{page}" is replaced with 1, 2, ...  (WordPress: https://site/feed/?paged={page})]
  max_pages: 3
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import AsyncIterator

from ..context import CrawlContext
from ..extract import compose_raw_text, strip_html
from ..models import RawCapture


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _child_text(el: ET.Element, *wanted: str) -> str:
    """Text of the first non-empty child, trying the tag names in the order given (priority, not document order)."""
    for name in wanted:
        for child in el:
            if _local(child.tag) == name and (child.text or "").strip():
                return child.text.strip()
    return ""


def _link(el: ET.Element) -> str:
    for child in el:
        if _local(child.tag) == "link":
            if child.get("href") and child.get("rel", "alternate") == "alternate":
                return child.get("href", "").strip()
            if (child.text or "").strip():
                return child.text.strip()
    return ""


def parse_feed(xml: str) -> list[dict]:
    """-> [{id, url, title, published, author, body_html}]; raises ValueError on unsafe/invalid XML."""
    if "<!DOCTYPE" in xml[:2000].upper() and "<!ENTITY" in xml.upper():
        raise ValueError("feed contains XML entity declarations; refusing to parse")
    try:
        root = ET.fromstring(xml.strip().encode("utf-8"))
    except ET.ParseError as exc:
        raise ValueError(f"invalid XML: {exc}")
    items = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        url = _link(el)
        author = _child_text(el, "creator", "author")
        if not author:  # Atom: <author><name>..</name></author>
            for child in el:
                if _local(child.tag) == "author":
                    author = _child_text(child, "name")
        items.append({
            "id": _child_text(el, "guid", "id") or url,
            "url": url,
            "title": _child_text(el, "title"),
            "published": _child_text(el, "pubDate", "published", "updated"),
            "author": author,
            "body_html": _child_text(el, "encoded", "content", "description", "summary"),
        })
    return items


async def run(ctx: CrawlContext) -> AsyncIterator[RawCapture]:
    src = ctx.source
    seen: set[str] = set()
    for template in src.opt("feed_urls") or []:
        paged = "{page}" in template
        for page in range(1, (int(src.opt("max_pages", 3)) if paged else 1) + 1):
            res = await ctx.get(template.replace("{page}", str(page)))
            if not res.ok:
                break
            try:
                items = parse_feed(res.text)
            except ValueError as exc:
                ctx.problem(f"{template}: {exc}")
                break
            fresh = [i for i in items if i["id"] and i["id"] not in seen]
            if not fresh:
                break
            for item in fresh:
                seen.add(item["id"])
                fields = {"title": item["title"], "employer": item["author"], "posted": item["published"],
                          "description": strip_html(item["body_html"])}
                yield RawCapture(
                    source_slug=src.slug,
                    external_id=(item["url"] or item["id"])[:255],
                    raw_text=compose_raw_text(fields),
                    url=item["url"] or None,
                    raw_meta={"title": item["title"], "published": item["published"], "feed_id": item["id"],
                              "extraction": "feed"},
                )
