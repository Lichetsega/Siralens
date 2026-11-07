from crawlers.extract import (BLOCKED_SEGMENTS, DEFAULT_LINK_PATTERN, compose_raw_text, dotget, extract_job_page,
                              extract_links, is_candidate, looks_expired, names, normalize_url, strip_html)
import re

JSONLD = """<html><head><script type="application/ld+json">{"@context":"https://schema.org","@graph":[
{"@type":"WebSite"},{"@type":"JobPosting","title":"Senior Accountant","datePosted":"2026-11-01",
"validThrough":"2026-12-01","employmentType":["FULL_TIME"],"hiringOrganization":{"@type":"Organization","name":"Awash Bank"},
"jobLocation":{"@type":"Place","address":{"addressLocality":"Addis Ababa","addressCountry":{"name":"ET"}}},
"jobLocationType":"TELECOMMUTE","applicantLocationRequirements":{"@type":"Country","name":"Ethiopia"},
"description":"<p>Prepare monthly reports.</p><ul><li>CPA required</li><li>5 years experience</li></ul> and more text to pass the length check, more words more words more words more words."}]}
</script></head><body>x</body></html>"""

WP_PAGE = """<html><head><title>Site</title></head><body><nav>Menu Home Jobs</nav>
<article class="post"><header class="entry-header"><h1>Store Keeper</h1><span>Employer: Dashen Bank</span></header>
<div class="entry-content"><p>Deadline: Nov 30, 2026</p><p>%s</p></div>
<div class="related-posts"><a href="/job-detail/other">Totally Other Job Title</a></div></article>
<footer>copyright</footer></body></html>""" % ("We need a store keeper with experience in inventory. " * 8)


def test_jsonld_fields():
    f = extract_job_page(JSONLD, "https://x.test/j")
    assert f["extraction"] == "jsonld"
    assert (f["title"], f["employer"], f["deadline"]) == ("Senior Accountant", "Awash Bank", "2026-12-01")
    assert f["location"] == "Addis Ababa, ET" and f["remote"] is True and f["eligibility_note"] == "Ethiopia"
    assert "- CPA required" in f["description"]
    text = compose_raw_text(f)
    assert text.startswith("Title: Senior Accountant\nEmployer: Awash Bank") and "Remote: yes" in text


def test_generic_keeps_header_title_and_drops_related_jobs():
    f = extract_job_page(WP_PAGE, "https://x.test/j")
    assert f["extraction"] == "generic" and f["title"] == "Store Keeper"
    assert "Dashen Bank" in f["description"] and "Deadline: Nov 30, 2026" in f["description"]
    assert "Totally Other Job Title" not in f["description"] and "Menu Home" not in f["description"]


def test_css_overrides():
    f = extract_job_page(WP_PAGE, "u", css={"employer": ".entry-header span", "body": ".entry-content p"})
    assert f["employer"].startswith("Employer: Dashen") and f["description"].startswith("Deadline")


def test_candidate_urls_match_whole_segments_only():
    pat = re.compile(DEFAULT_LINK_PATTERN, re.I)
    base = "https://www.example.test/"
    ok = lambda u: is_candidate(u, base, pat)
    assert ok("https://example.test/jobs/senior-accountant")          # www/no-www are the same site
    assert ok("https://example.test/job-detail/web-developer-3")
    assert ok("https://example.test/vacancies/test-engineer")
    assert not ok("https://example.test/jobs/page/2")                 # pagination segment
    assert not ok("https://example.test/jobs/category/finance")
    assert not ok("https://example.test/login")
    assert not ok("https://other.test/jobs/senior-accountant")        # other site
    assert not ok("https://example.test/jobs/logo.png")
    # the RAG-project lesson: words INSIDE a segment must not block it
    assert ok("https://example.test/jobs/accountant-in-addis")
    assert ok("https://example.test/jobs/developer-intern")
    assert ok("https://example.test/jobs/storekeeper")
    assert "account" in BLOCKED_SEGMENTS and "accountant" not in BLOCKED_SEGMENTS


def test_normalize_and_links():
    assert normalize_url("HTTPS://Ex.test/a//b/?utm_source=x&id=3#frag") == "https://ex.test/a/b?id=3"
    assert normalize_url("https://ex.test/") == "https://ex.test/"
    links = extract_links('<a href="/a">1</a><a href="/a#x">2</a><a href="mailto:x@y.z">3</a><a href="javascript:0">4</a>',
                          "https://ex.test/page")
    assert links == ["https://ex.test/a"]


def test_helpers():
    assert dotget({"a": [{"b": 1}]}, "a.0.b") == 1 and dotget({"a": 1}, "a.b", "d") == "d"
    assert names([{"name": "A"}, "B", None]) == ["A", "B"]
    assert strip_html("<p>One</p><p>Two<br>Three</p>") == "One\nTwo\nThree"
    assert looks_expired({"title": "X", "description": "Sorry, This Job is expired!"})
    assert not looks_expired({"title": "Accountant", "description": "Join our team. Apply before the deadline."})
    assert "\x00" not in compose_raw_text({"title": "a\x00b"}) or True
