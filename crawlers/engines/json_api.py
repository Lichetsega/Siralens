"""
Engine 'json_api': any site whose listings come from a JSON endpoint you can see in the browser's
Network tab (F12 -> Network -> Fetch/XHR). Configure it; no code needed.

Source options:
  url:         endpoint; "{page}" is replaced with the page number
  method:      GET (default)
  items_path:  where the list of jobs is, e.g. "data.items"  (dot path; use "" if the response IS the list)
  id_path:     the job's id inside one item, e.g. "id"
  fields:      mapping of our names -> paths inside one item. Names: title, employer, location, deadline,
               posted, job_type, description (HTML is fine), apply
  link_template: e.g. "https://site.com/jobs/{id}"  (or url_path: path to a link inside the item)
  page_start: 1,  max_pages: 5,  headers: {optional extra headers, never secrets}
"""
from __future__ import annotations

from typing import AsyncIterator

from ..context import CrawlContext
from ..extract import compose_raw_text, dotget, names, strip_html
from ..models import RawCapture


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return ", ".join(names(value))
    return str(value)


async def run(ctx: CrawlContext) -> AsyncIterator[RawCapture]:
    src = ctx.source
    template = src.opt("url")
    mapping: dict = src.opt("fields") or {}
    start = int(src.opt("page_start", 1))
    seen: set[str] = set()

    for page in range(start, start + int(src.opt("max_pages", 5))):
        res = await ctx.get(template.replace("{page}", str(page)), headers=src.opt("headers"))
        if not res.ok:
            break
        try:
            data = res.json()
        except ValueError:
            ctx.problem(f"{template}: response is not JSON")
            break
        items = dotget(data, src.opt("items_path")) if src.opt("items_path") else data
        if not isinstance(items, list) or not items:
            if page == start:
                ctx.problem(f"{template}: no list found at items_path '{src.opt('items_path')}'")
            break
        fresh = 0
        for item in items:
            ident = _as_text(dotget(item, src.opt("id_path", "id")))
            if not ident or ident in seen:
                continue
            seen.add(ident)
            fresh += 1
            fields = {k: _as_text(dotget(item, path)) for k, path in mapping.items()}
            fields["description"] = strip_html(fields.get("description", ""))
            link = _as_text(dotget(item, src.opt("url_path"))) if src.opt("url_path") else ""
            if not link and src.opt("link_template"):
                link = str(src.opt("link_template")).replace("{id}", ident)
            if link:
                fields.setdefault("apply", "")
            yield RawCapture(
                source_slug=src.slug,
                external_id=ident[:255],
                raw_text=compose_raw_text(fields),
                url=link or None,
                raw_meta={**{k: v for k, v in fields.items() if k != "description" and v}, "extraction": "json_api"},
            )
        if fresh == 0:
            break
