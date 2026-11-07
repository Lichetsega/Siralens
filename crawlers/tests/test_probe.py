import json

from crawlers.tools.probe import analyze_html, find_jobposting, parse_robots, parse_sitemap, strip_tags, verdict

JOB_HTML = """<html><head><title> Senior Accountant | Example </title>
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"WebSite"},
{"@type":"JobPosting","title":"Senior Accountant","validThrough":"2026-12-01","datePosted":"2026-11-01"}]}</script>
</head><body><a href="/job-detail/senior-accountant">x</a><a href="/about">y</a>
<a href="https://other.com/jobs/1">z</a></body></html>"""

SPA_HTML = "<html><head><title>App</title><script src=a></script><script src=b></script><script src=c></script></head><body><div id=root></div></body></html>"


def test_strip_tags_removes_scripts():
    assert strip_tags("<p>Hello <b>you</b></p><script>var a=1;</script>") == "Hello you"


def test_find_jobposting_in_graph():
    data = json.loads('{"@graph":[{"@type":"WebSite"},{"@type":"JobPosting","title":"x"}]}')
    assert find_jobposting(data)["title"] == "x"
    assert find_jobposting({"@type": "Organization"}) is None


def test_analyze_job_page():
    a = analyze_html(JOB_HTML, "https://example.com/")
    assert a["title"] == "Senior Accountant | Example"
    assert a["has_jobposting"] and "validThrough" in a["jobposting_fields"]
    assert "https://example.com/job-detail/senior-accountant" in a["job_like_links"]
    assert not a["looks_like_js_app"] or a["visible_text_chars"] < 800


def test_analyze_spa_detected():
    a = analyze_html(SPA_HTML, "https://example.com/")
    assert a["looks_like_js_app"] and not a["has_jobposting"]


def test_parse_robots():
    txt = """User-agent: Googlebot
Disallow: /private
User-agent: *
Disallow: /admin
Disallow: /search?
Crawl-delay: 5
Sitemap: https://example.com/sitemap.xml
"""
    r = parse_robots(txt)
    assert r["sitemaps"] == ["https://example.com/sitemap.xml"]
    assert r["crawl_delay"] == 5.0
    assert r["disallow_rules"] == ["/admin", "/search?"]
    assert not r["disallow_everything"]
    assert parse_robots("User-agent: *\nDisallow: /")["disallow_everything"]


def test_parse_sitemap():
    idx = "<sitemapindex><sitemap><loc>https://e.com/a.xml</loc></sitemap></sitemapindex>"
    assert parse_sitemap(idx) == {"kind": "index", "locs": ["https://e.com/a.xml"]}
    urls = "<urlset><url><loc> https://e.com/1 </loc></url></urlset>"
    assert parse_sitemap(urls)["locs"] == ["https://e.com/1"]


def test_verdicts():
    assert verdict({"homepage": {"skipped": "x"}}).startswith("BLOCKED")
    assert verdict({"homepage": {"status": 200, "looks_like_js_app": True}}).startswith("JavaScript")
    assert verdict({"homepage": {"status": 200}, "sample_job_page": {"has_jobposting": True}}).startswith("good")
