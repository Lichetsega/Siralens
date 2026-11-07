import asyncio
import json

import httpx
import pytest

from crawlers.context import SourceState
from crawlers.engines import feed, html_portal, json_api, reliefweb, telegram
from crawlers.tests.conftest import collect, make_source

JOBPAGE = """<html><head><script type="application/ld+json">{"@type":"JobPosting","title":"%s",
"hiringOrganization":{"name":"Acme"},"validThrough":"2026-12-01",
"description":"%s"}</script></head><body></body></html>"""
LONG = "Responsibilities include many tasks and duties for this role. " * 4

GENERIC = """<html><body><header><h1>Driver</h1></header><article><p>%s</p></article></body></html>""" % ("Drive safely. " * 30)


def site(pages: dict, robots="User-agent: *\nAllow: /"):
    def handler(req):
        path = req.url.path + (("?" + req.url.query.decode()) if req.url.query else "")
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=robots)
        if path in pages:
            return httpx.Response(200, text=pages[path])
        return httpx.Response(404)
    return handler


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- html
LIST = """<a href="/job-detail/accountant-1">a</a><a href="/job-detail/driver-2">b</a>
<a href="/about">c</a><a href="/login">d</a><a href="/jobs/page/2">e</a><a href="/job-detail/expired-3">f</a>"""
PAGES = {
    "/jobs": LIST,
    "/job-detail/accountant-1": JOBPAGE % ("Accountant", LONG),
    "/job-detail/driver-2": GENERIC,
    "/job-detail/expired-3": "<html><body><h1>Old</h1><p>Sorry, This Job is expired! " + "x " * 80 + "</p></body></html>",
}


def test_html_engine_discovers_fetches_and_extracts():
    src = make_source(options={"discovery": {"list_urls": ["https://example.test/jobs"], "link_pattern": "/job-detail/"}})
    caps, ctx, requested = run(collect(html_portal.run, src, site(PAGES)))
    assert [c.external_id for c in caps] == ["https://example.test/job-detail/accountant-1",
                                              "https://example.test/job-detail/driver-2"]
    assert caps[0].raw_meta["extraction"] == "jsonld" and "Employer: Acme" in caps[0].raw_text
    assert caps[1].raw_meta["extraction"] == "generic" and caps[1].raw_text.startswith("Title: Driver")
    assert "/about" not in requested and "/login" not in requested and "/jobs/page/2" not in requested
    assert any("skipped 1 expired" in n for n in ctx.notes) and not ctx.problems


def test_html_engine_skips_known_urls():
    src = make_source(options={"discovery": {"list_urls": ["https://example.test/jobs"], "link_pattern": "/job-detail/"}})
    state = SourceState(known_ids={"https://example.test/job-detail/accountant-1"})
    caps, ctx, requested = run(collect(html_portal.run, src, site(PAGES), state))
    assert [c.external_id.rsplit("/", 1)[-1] for c in caps] == ["driver-2"]
    assert "/job-detail/accountant-1" not in requested


def test_html_engine_paged_lists_stop_when_nothing_new():
    pages = {"/l?page=1": '<a href="/jobs/a1">x</a>', "/l?page=2": '<a href="/jobs/b2">x</a>',
             "/l?page=3": '<a href="/jobs/a1">x</a>', "/jobs/a1": GENERIC, "/jobs/b2": GENERIC}
    src = make_source(options={"discovery": {"list_urls": ["https://example.test/l?page={page}"], "max_pages": 9}})
    caps, ctx, requested = run(collect(html_portal.run, src, site(pages)))
    assert len(caps) == 2 and "/l?page=4" not in requested


def test_html_engine_sitemap_index_newest_first_and_robots_sitemap():
    index = ('<sitemapindex><sitemap><loc>https://example.test/sm-jobs.xml</loc><lastmod>2026-11-01</lastmod></sitemap>'
             '<sitemap><loc>https://example.test/sm-pages.xml</loc></sitemap></sitemapindex>')
    jobs = ('<urlset><url><loc>https://example.test/jobs/old-one</loc><lastmod>2026-01-01</lastmod></url>'
            '<url><loc>https://example.test/jobs/new-one?a=1&amp;b=2</loc><lastmod>2026-11-05</lastmod></url></urlset>')
    pages = {"/sitemap.xml": index, "/sm-jobs.xml": jobs, "/sm-pages.xml": "<urlset></urlset>",
             "/jobs/old-one": GENERIC, "/jobs/new-one?a=1&b=2": GENERIC}
    src = make_source(options={"max_details": 1})
    handler = site(pages, robots="User-agent: *\nSitemap: https://example.test/sitemap.xml")
    caps, ctx, requested = run(collect(html_portal.run, src, handler))
    assert len(caps) == 1 and "new-one" in caps[0].external_id  # newest first, max_details=1


def test_html_engine_reports_zero_links_as_a_problem():
    caps, ctx, _ = run(collect(html_portal.run, make_source(options={"discovery": {"list_urls": ["https://example.test/"]}}),
                               site({"/": "<html><body>nothing here</body></html>"})))
    assert caps == [] and any("no job links found" in p for p in ctx.problems)


def test_robots_disallow_stops_the_crawl_with_a_clear_problem():
    handler = site(PAGES, robots="User-agent: *\nDisallow: /")
    src = make_source(options={"discovery": {"list_urls": ["https://example.test/jobs"], "robots_sitemaps": False}})
    caps, ctx, requested = run(collect(html_portal.run, src, handler))
    assert caps == [] and any("blocked by robots.txt" in p for p in ctx.problems) and "/jobs" not in requested


# ---------------------------------------------------------------- feed
RSS = """<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"
xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
<item><title>Nurse</title><link>https://example.test/nurse</link><guid>g1</guid><pubDate>Mon, 02 Nov 2026 08:00:00 GMT</pubDate>
<dc:creator>Hospital</dc:creator><description>short</description><content:encoded><![CDATA[<p>Full nurse description</p>]]></content:encoded></item>
<item><title>Cook</title><link>https://example.test/cook</link><guid>g2</guid></item></channel></rss>"""
ATOM = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Pilot</title><id>tag:1</id>
<link rel="alternate" href="https://example.test/pilot"/><updated>2026-11-01T00:00:00Z</updated>
<author><name>Airline</name></author><summary>Fly planes</summary></entry></feed>"""


def test_feed_parses_rss_and_atom():
    items = feed.parse_feed(RSS)
    assert [i["title"] for i in items] == ["Nurse", "Cook"] and items[0]["author"] == "Hospital"
    assert "Full nurse description" in items[0]["body_html"]
    a = feed.parse_feed(ATOM)[0]
    assert (a["url"], a["author"], a["id"]) == ("https://example.test/pilot", "Airline", "tag:1")


def test_feed_rejects_entity_bombs():
    with pytest.raises(ValueError):
        feed.parse_feed('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><rss><channel/></rss>')


def test_feed_engine_pages_and_stops_on_repeat():
    src = make_source(engine="feed", options={"feed_urls": ["https://example.test/feed/?paged={page}"], "max_pages": 5})
    pages = {"/feed/?paged=1": RSS, "/feed/?paged=2": RSS}
    caps, ctx, requested = run(collect(feed.run, src, site(pages)))
    assert [c.url for c in caps] == ["https://example.test/nurse", "https://example.test/cook"]
    assert "Employer: Hospital" in caps[0].raw_text and "Full nurse description" in caps[0].raw_text
    assert "/feed/?paged=3" not in requested


# ---------------------------------------------------------------- telegram
def tg_msg(i, text, reply=None, photo=False):
    reply_html = f'<a class="tgme_widget_message_reply" href="x"><div class="tgme_widget_message_text js-message_reply_text">{reply}</div></a>' if reply else ""
    body = f'<div class="tgme_widget_message_text js-message_text">{text}</div>' if text is not None else ""
    photo_html = '<a class="tgme_widget_message_photo_wrap" href="x"></a>' if photo else ""
    return (f'<div class="tgme_widget_message_wrap"><div class="tgme_widget_message js-widget_message" data-post="chan/{i}">'
            f'{reply_html}{photo_html}{body}<span class="tgme_widget_message_views">1.2K</span>'
            f'<a class="tgme_widget_message_date" href="https://t.me/chan/{i}"><time datetime="2026-11-0{i % 9 + 1}T08:00:00+00:00"></time></a></div></div>')


def tg_page(*msgs):
    return "<html><body>" + "".join(msgs) + "</body></html>"


PAGE_NEW = tg_page(tg_msg(13, "Position 1: <b>Accountant</b><br/>Deadline: <a href='https://x.test/apply'>Oct 10, 2026</a>"),
                   tg_msg(14, "Reply post text", reply="QUOTED TEXT"),
                   tg_msg(15, None, photo=True))
PAGE_OLD = tg_page(tg_msg(11, "Old job eleven"), tg_msg(12, "Old job twelve"))


def tg_handler(req):
    if req.url.path == "/robots.txt":
        return httpx.Response(404)
    return httpx.Response(200, text=PAGE_OLD if req.url.query else PAGE_NEW)


def tg_source(): return make_source(slug="tg_chan", kind="telegram", engine="telegram", options={"channel": "chan", "max_pages": 3})


def test_telegram_parses_text_links_reply_and_images():
    caps, ctx, requested = run(collect(telegram.run, tg_source(), tg_handler))
    by_id = {c.external_id: c for c in caps}
    assert set(by_id) == {"chan/13", "chan/14", "chan/12", "chan/11"}  # image-only post 15 skipped
    assert by_id["chan/13"].raw_text == "Position 1: Accountant\nDeadline: Oct 10, 2026"
    assert by_id["chan/13"].raw_meta["links"] == ["https://x.test/apply"] and by_id["chan/13"].raw_meta["views"] == "1.2K"
    assert by_id["chan/14"].raw_text == "Reply post text"  # not the quoted reply
    assert any("image-only" in n for n in ctx.notes)
    pages = [r for r in requested if r != "/robots.txt"]
    assert pages[0] == "/s/chan" and pages[1] == "/s/chan?before=13"


def test_telegram_incremental_returns_new_posts_only():
    """Regression: the old adapter returned NOTHING when since_message_id was set."""
    caps, ctx, requested = run(collect(telegram.run, tg_source(), tg_handler, SourceState(last_message_id=12)))
    assert {c.external_id for c in caps} == {"chan/13", "chan/14"}
    # page one's oldest post (13) is newer than 12, so one more page is read to confirm the boundary, then it stops
    pages = [r for r in requested if r != "/robots.txt"]
    assert pages == ["/s/chan", "/s/chan?before=13"]


def test_telegram_flags_channel_with_no_preview():
    caps, ctx, _ = run(collect(telegram.run, tg_source(), lambda r: httpx.Response(200, text="<html></html>")))
    assert caps == [] and any("no messages found" in p for p in ctx.problems)


# ---------------------------------------------------------------- json_api
def test_json_api_maps_fields_and_paginates():
    pages = {1: {"data": {"items": [{"id": 7, "title": "Engineer", "company": {"name": "Acme"}, "closing": "2026-12-01",
                                     "desc": "<p>Build things</p>"}]}},
             2: {"data": {"items": []}}}

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, json=pages[int(req.url.params["page"])])

    src = make_source(engine="json_api", options={
        "url": "https://example.test/api/jobs?page={page}", "items_path": "data.items", "id_path": "id",
        "fields": {"title": "title", "employer": "company.name", "deadline": "closing", "description": "desc"},
        "link_template": "https://example.test/jobs/{id}"})
    caps, ctx, _ = run(collect(json_api.run, src, handler))
    assert len(caps) == 1 and caps[0].external_id == "7" and caps[0].url == "https://example.test/jobs/7"
    assert caps[0].raw_text == "Title: Engineer\nEmployer: Acme\nDeadline: 2026-12-01\n\nBuild things"


def test_json_api_wrong_items_path_is_a_problem():
    src = make_source(engine="json_api", options={"url": "https://example.test/api", "items_path": "nope",
                                                   "fields": {"title": "title"}})
    caps, ctx, _ = run(collect(json_api.run, src, lambda r: httpx.Response(404) if "robots" in r.url.path
                               else httpx.Response(200, json={"data": []})))
    assert caps == [] and any("no list found" in p for p in ctx.problems)


# ---------------------------------------------------------------- reliefweb
RW = {"data": [{"id": 1, "fields": {"title": "Programme Officer", "url": "https://reliefweb.int/job/1",
     "source": [{"name": "UNICEF"}], "country": [{"name": "Ethiopia"}], "city": [{"name": "Addis Ababa"}],
     "date": {"created": "2026-11-01", "closing": "2026-12-01"}, "body": "Do things", "how_to_apply": "Apply online",
     "career_categories": [{"name": "Program"}]}}]}


def test_reliefweb_needs_appname(monkeypatch):
    monkeypatch.delenv("RELIEFWEB_APPNAME", raising=False)
    caps, ctx, requested = run(collect(reliefweb.run, make_source(engine="reliefweb"), lambda r: httpx.Response(200, json=RW)))
    assert caps == [] and any("RELIEFWEB_APPNAME" in p for p in ctx.problems) and requested == []


def test_reliefweb_maps_jobs(monkeypatch):
    monkeypatch.setenv("RELIEFWEB_APPNAME", "my-registered-app")
    seen = {}

    def handler(req):
        seen["appname"] = req.url.params.get("appname")
        seen["method"] = req.method
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=RW)

    caps, ctx, _ = run(collect(reliefweb.run, make_source(engine="reliefweb"), handler))
    assert seen["appname"] == "my-registered-app" and seen["method"] == "POST"
    assert seen["body"]["filter"]["conditions"][0] == {"field": "country.iso3", "value": "ETH"}
    c = caps[0]
    assert c.external_id == "1" and c.url == "https://reliefweb.int/job/1"
    assert "Employer: UNICEF" in c.raw_text and "Location: Addis Ababa, Ethiopia" in c.raw_text
    assert "Deadline: 2026-12-01" in c.raw_text and "Apply: Apply online" in c.raw_text


def test_reliefweb_403_message(monkeypatch):
    monkeypatch.setenv("RELIEFWEB_APPNAME", "unapproved")
    caps, ctx, _ = run(collect(reliefweb.run, make_source(engine="reliefweb"), lambda r: httpx.Response(403)))
    assert caps == [] and any("approved name" in p for p in ctx.problems)
