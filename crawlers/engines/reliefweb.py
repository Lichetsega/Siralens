"""
Engine 'reliefweb': the official ReliefWeb jobs API (https://apidoc.reliefweb.int).

ReliefWeb asks every client to use a registered application name. Register one, then set
RELIEFWEB_APPNAME in your .env. Without it this source reports a clear problem and does nothing.

Source options:
  queries: list of {name, field, value}, e.g. {name: Ethiopia, field: country.iso3, value: ETH}
  max_pages: 5   (100 jobs per page)
"""
from __future__ import annotations

import os
from typing import AsyncIterator

from ..context import CrawlContext
from ..extract import compose_raw_text, names, strip_html
from ..models import RawCapture

API_URL = "https://api.reliefweb.int/v2/jobs"
FIELDS = ["title", "body", "url", "date.created", "date.closing", "source", "country", "city",
          "career_categories", "type", "experience", "how_to_apply"]
DEFAULT_QUERIES = [
    {"name": "Ethiopia", "field": "country.iso3", "value": "ETH"},
]


def to_capture(item: dict, slug: str) -> RawCapture | None:
    f = item.get("fields") or {}
    job_id = str(item.get("id") or "")
    if not job_id:
        return None
    how = f.get("how_to_apply")
    how_text = strip_html(how.get("instruction", "") if isinstance(how, dict) else str(how or ""))
    date = f.get("date") or {}
    fields = {
        "title": f.get("title") or "",
        "employer": ", ".join(names(f.get("source"))),
        "location": ", ".join(names(f.get("city")) + names(f.get("country"))),
        "job_type": ", ".join(names(f.get("type"))),
        "deadline": date.get("closing") or "",
        "posted": date.get("created") or "",
        "apply": how_text,
        "description": strip_html(f.get("body") or ""),
    }
    return RawCapture(
        source_slug=slug,
        external_id=job_id,
        raw_text=compose_raw_text(fields),
        url=f.get("url") or f"https://reliefweb.int/job/{job_id}",
        raw_meta={"countries": names(f.get("country")), "categories": names(f.get("career_categories")),
                  "experience": names(f.get("experience")), "extraction": "reliefweb",
                  **{k: v for k, v in fields.items() if k in ("title", "employer", "location", "deadline", "posted") and v}},
    )


async def run(ctx: CrawlContext) -> AsyncIterator[RawCapture]:
    src = ctx.source
    appname = os.getenv("RELIEFWEB_APPNAME", "").strip()
    if not appname:
        ctx.problem("RELIEFWEB_APPNAME is not set (register an application name with ReliefWeb, then put it in .env)")
        return
    seen: set[str] = set()
    for q in src.opt("queries") or DEFAULT_QUERIES:
        for page in range(int(src.opt("max_pages", 5))):
            body = {
                "limit": 100,
                "offset": page * 100,
                "sort": ["date.created:desc"],
                "fields": {"include": FIELDS},
                "filter": {"operator": "AND", "conditions": [{"field": q["field"], "value": q["value"]}]},
            }
            res = await ctx.post_json(API_URL, body, params={"appname": appname})
            if not res.ok:
                if res.status == 403:
                    ctx.problem("ReliefWeb refused the request (403): is RELIEFWEB_APPNAME an approved name?")
                break
            try:
                items = res.json().get("data", [])
            except ValueError:
                ctx.problem("ReliefWeb returned something that is not JSON")
                break
            if not items:
                break
            for item in items:
                cap = to_capture(item, src.slug)
                if cap and cap.external_id not in seen:
                    seen.add(cap.external_id)
                    yield cap
            if len(items) < 100:
                break
