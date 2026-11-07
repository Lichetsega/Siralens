"""
Engine 'telegram': public channels through the web preview https://t.me/s/<channel>.
One engine serves every channel; each channel is one entry in sources.yaml.

Source options:
  channel:   channel username without @
  max_pages: 3   (about 20 posts per page, newest first; pages go back with ?before=<id>)

Only posts newer than the newest one already stored are returned (incremental).
A bot cannot read channels it does not administer; the web preview needs no account.
"""
from __future__ import annotations

from typing import AsyncIterator

from bs4 import BeautifulSoup

from ..context import CrawlContext
from ..extract import clean_text
from ..models import RawCapture


def _text_div(msg):
    for div in msg.select("div.tgme_widget_message_text"):
        if not div.find_parent(class_="tgme_widget_message_reply"):  # skip the quoted reply preview
            return div
    return None


def parse_messages(html: str, channel: str, slug: str) -> list[tuple[int, RawCapture]]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[int, RawCapture]] = []
    for msg in soup.select("div.tgme_widget_message[data-post]"):
        data_post = msg.get("data-post", "")
        try:
            msg_id = int(data_post.rsplit("/", 1)[-1])
        except ValueError:
            continue
        div = _text_div(msg)
        text, links = "", []
        if div is not None:
            links = [a["href"] for a in div.find_all("a", href=True)][:20]
            for br in div.find_all("br"):
                br.replace_with("\n")
            text = clean_text(div.get_text(""))
        time_el = msg.find("time")
        date_a = msg.select_one("a.tgme_widget_message_date")
        views = msg.select_one(".tgme_widget_message_views")
        fwd = msg.select_one(".tgme_widget_message_forwarded_from_name")
        out.append((msg_id, RawCapture(
            source_slug=slug,
            external_id=data_post,
            raw_text=text,
            url=date_a["href"] if date_a and date_a.get("href") else f"https://t.me/{data_post}",
            raw_meta={
                "channel": channel,
                "message_id": msg_id,
                "posted_at": time_el.get("datetime", "") if time_el else "",
                "views": views.get_text(strip=True) if views else "",
                "links": links,
                "has_photo": msg.select_one(".tgme_widget_message_photo_wrap") is not None,
                "forwarded_from": fwd.get_text(strip=True) if fwd else "",
                "extraction": "telegram",
            },
        )))
    return out


async def run(ctx: CrawlContext) -> AsyncIterator[RawCapture]:
    src = ctx.source
    channel = src.opt("channel")
    base = f"https://t.me/s/{channel}"
    since = ctx.state.last_message_id
    before: int | None = None
    image_only = 0

    for page in range(int(src.opt("max_pages", 3))):
        res = await ctx.get(base if before is None else f"{base}?before={before}")
        if not res.ok:
            break
        messages = parse_messages(res.text, channel, src.slug)
        if not messages:
            if page == 0:
                ctx.problem(f"{base}: no messages found (private channel, or web preview disabled?)")
            break
        for msg_id, capture in messages:
            if since is not None and msg_id <= since:
                continue
            if capture.is_empty():
                image_only += 1
                continue
            yield capture
        oldest = min(i for i, _ in messages)
        if (since is not None and oldest <= since) or oldest <= 1:
            break  # reached what we already have
        before = oldest
    if image_only:
        ctx.note(f"{image_only} image-only posts skipped (need OCR later)")
