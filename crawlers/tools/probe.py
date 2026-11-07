"""
SIRALens source probe.

Run this on your own computer. It looks at each job website the way a polite crawler
would and writes a report describing how the site is built (server-rendered or
JavaScript app, sitemap, structured data, robots rules). Nothing here is secret.

    python probe.py                 # probe every site
    python probe.py geezjobs hahu   # probe only some

No packages to install: standard library only.
Output: probe_report.md and probe_report.json in the current folder.
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

USER_AGENT = "SIRALensBot/0.1 (+https://github.com/Lichetsega/Siralens)"
DELAY_SECONDS = 2.0
TIMEOUT = 60
MAX_BYTES = 2_000_000

SITES = {
    "ethiojobs": "https://ethiojobs.net/",
    "hahu": "https://www.hahu.jobs/",
    "ethiopianreporter": "https://www.ethiopianreporterjobs.com/",
    "geezjobs": "https://geezjobs.com/",
    "ethiopiawork": "https://www.ethiopiawork.com/",
    "palmjobs": "https://palmjobs.et/",
    "muyalogy": "https://muyalogy.com/",
    "ethiongojobs": "https://www.ethiongojobs.com/",
    "abayjobs": "https://abayjobs.com/",  # extra: the Telegram channel links here
}

LINK_RE = re.compile(r'<a\s[^>]*?href=["\']([^"\'#][^"\']*)["\']', re.I)
LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S
)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.I | re.S)
JOB_LINK_RE = re.compile(r"/(jobs?|job-detail|vacanc\w*|careers?|positions?|openings?)(/|-|$)", re.I)


# ---------- pure helpers (unit-tested) ----------
def strip_tags(html: str) -> str:
    html = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def find_jobposting(obj):
    """Return the first schema.org JobPosting dict found anywhere in parsed JSON-LD."""
    if isinstance(obj, dict):
        t = obj.get("@type")
        types = t if isinstance(t, list) else [t]
        if "JobPosting" in types:
            return obj
        for v in obj.values():
            found = find_jobposting(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = find_jobposting(v)
            if found:
                return found
    return None


def analyze_html(html: str, base_url: str) -> dict:
    title_m = TITLE_RE.search(html)
    text = strip_tags(html)
    links, seen = [], set()
    for href in LINK_RE.findall(html):
        absolute = urljoin(base_url, href.strip())
        if absolute not in seen:
            seen.add(absolute)
            links.append(absolute)
    job_links = [u for u in links if JOB_LINK_RE.search(urlparse(u).path)]

    jobposting = None
    for block in LD_RE.findall(html):
        try:
            jobposting = find_jobposting(json.loads(block.strip()))
        except (ValueError, TypeError):
            continue
        if jobposting:
            break

    script_count = len(re.findall(r"<script\b", html, flags=re.I))
    return {
        "title": re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else None,
        "html_bytes": len(html),
        "visible_text_chars": len(text),
        "link_count": len(links),
        "job_like_links": job_links[:15],
        "job_like_link_count": len(job_links),
        "has_next_data": "__NEXT_DATA__" in html,
        "has_nuxt": "__NUXT__" in html,
        "has_ld_json": bool(LD_RE.search(html)),
        "has_jobposting": jobposting is not None,
        "jobposting_fields": sorted(jobposting.keys()) if jobposting else [],
        "script_tags": script_count,
        "looks_like_js_app": len(text) < 800 and script_count >= 3,
    }


def parse_robots(text: str) -> dict:
    sitemaps, star_disallow, crawl_delay = [], [], None
    in_star = False
    prev_was_agent = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (p.strip() for p in line.split(":", 1))
        k = key.lower()
        if k == "sitemap":
            sitemaps.append(value)
        elif k == "user-agent":
            in_star = (value == "*") if not prev_was_agent else (in_star or value == "*")
            prev_was_agent = True
            continue
        elif in_star and k == "disallow" and value:
            star_disallow.append(value)
        elif in_star and k == "crawl-delay":
            try:
                crawl_delay = float(value)
            except ValueError:
                pass
        prev_was_agent = False
    return {
        "sitemaps": sitemaps,
        "crawl_delay": crawl_delay,
        "disallow_everything": "/" in star_disallow,
        "disallow_rules": star_disallow[:25],
    }


def parse_sitemap(xml: str) -> dict:
    locs = LOC_RE.findall(xml)
    return {"kind": "index" if "<sitemapindex" in xml.lower() else "urlset", "locs": locs}


# ---------- network ----------
def fetch(url: str) -> dict:
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity", "Accept": "*/*"}
    )
    last_error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = resp.read(MAX_BYTES)
                charset = resp.headers.get_content_charset() or "utf-8"
                return {
                    "ok": True,
                    "status": resp.status,
                    "final_url": resp.geturl(),
                    "content_type": resp.headers.get("Content-Type", ""),
                    "text": body.decode(charset, errors="replace"),
                }
        except urllib.error.HTTPError as e:
            body = e.read(MAX_BYTES) if hasattr(e, "read") else b""
            return {
                "ok": False,
                "status": e.code,
                "final_url": url,
                "content_type": e.headers.get("Content-Type", "") if e.headers else "",
                "text": body.decode("utf-8", errors="replace"),
                "error": f"HTTP {e.code}",
            }
        except Exception as e:  # network errors, timeouts, SSL problems
            last_error = f"{type(e).__name__}: {e}"
            time.sleep(3 * (attempt + 1))
    return {"ok": False, "status": None, "final_url": url, "content_type": "", "text": "", "error": last_error}


def polite_fetch(url: str) -> dict:
    result = fetch(url)
    time.sleep(DELAY_SECONDS)
    return result


# ---------- one site ----------
def probe_site(slug: str, base: str) -> dict:
    report = {"slug": slug, "base_url": base}
    origin = f"{urlparse(base).scheme}://{urlparse(base).netloc}"

    robots_res = polite_fetch(urljoin(origin, "/robots.txt"))
    robots_text = robots_res["text"] if robots_res.get("status") == 200 else ""
    robots = parse_robots(robots_text)
    report["robots"] = {"status": robots_res.get("status"), "error": robots_res.get("error"), **robots}
    rp = RobotFileParser()
    rp.parse(robots_text.splitlines())

    def allowed(url):
        return rp.can_fetch(USER_AGENT, url) if robots_text else True

    # homepage
    if not allowed(base):
        report["homepage"] = {"skipped": "disallowed by robots.txt"}
    else:
        home = polite_fetch(base)
        report["homepage"] = {
            "status": home.get("status"),
            "error": home.get("error"),
            "final_url": home.get("final_url"),
            "content_type": home.get("content_type"),
        }
        if home.get("text"):
            report["homepage"].update(analyze_html(home["text"], home["final_url"] or base))

    # sitemap
    sitemap_url = robots["sitemaps"][0] if robots["sitemaps"] else urljoin(origin, "/sitemap.xml")
    sm = {"url": sitemap_url}
    if allowed(sitemap_url):
        res = polite_fetch(sitemap_url)
        sm["status"] = res.get("status")
        sm["error"] = res.get("error")
        if res.get("status") == 200 and "<loc" in res["text"].lower():
            parsed = parse_sitemap(res["text"])
            sm["kind"] = parsed["kind"]
            sm["url_count"] = len(parsed["locs"])
            sm["sample"] = parsed["locs"][:8]
            if parsed["kind"] == "index" and parsed["locs"]:
                child = next((u for u in parsed["locs"] if "job" in u.lower()), parsed["locs"][0])
                if allowed(child):
                    cres = polite_fetch(child)
                    if cres.get("status") == 200:
                        cp = parse_sitemap(cres["text"])
                        sm["child"] = {
                            "url": child,
                            "url_count": len(cp["locs"]),
                            "sample": cp["locs"][:8],
                        }
    else:
        sm["skipped"] = "disallowed by robots.txt"
    report["sitemap"] = sm

    # one sample job page
    candidates = list(report["homepage"].get("job_like_links", []))
    child_sample = report["sitemap"].get("child", {}).get("sample", [])
    candidates += [u for u in child_sample if JOB_LINK_RE.search(urlparse(u).path)]
    sample_url = next((u for u in candidates if urlparse(u).path.strip("/") and allowed(u)), None)
    if sample_url:
        page = polite_fetch(sample_url)
        report["sample_job_page"] = {"url": sample_url, "status": page.get("status"), "error": page.get("error")}
        if page.get("text"):
            a = analyze_html(page["text"], page["final_url"] or sample_url)
            a.pop("job_like_links", None)
            report["sample_job_page"].update(a)
    return report


def verdict(r: dict) -> str:
    home = r.get("homepage", {})
    if home.get("skipped"):
        return "BLOCKED by robots.txt: do not crawl"
    if home.get("status") != 200:
        return f"homepage not reachable ({home.get('error') or home.get('status')})"
    sample = r.get("sample_job_page", {})
    if sample.get("has_jobposting") or home.get("has_jobposting"):
        return "good: structured JobPosting data"
    if home.get("has_next_data") or home.get("looks_like_js_app"):
        return "JavaScript app: need its data endpoint"
    if home.get("job_like_link_count", 0) > 0:
        return "server-rendered HTML: CSS selectors needed"
    return "unclear: needs manual look"


def to_markdown(reports: list) -> str:
    lines = [
        "# SIRALens probe report",
        f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} | Python {sys.version.split()[0]}",
        "",
        "| site | homepage | robots | sitemap | sample job page | verdict |",
        "|---|---|---|---|---|---|",
    ]
    for r in reports:
        h = r.get("homepage", {})
        s = r.get("sample_job_page", {})
        sm = r.get("sitemap", {})
        lines.append(
            f"| {r['slug']} | {h.get('status') or h.get('skipped') or h.get('error')} "
            f"| {r['robots'].get('status')} | {sm.get('status') or sm.get('skipped') or sm.get('error')} "
            f"| {s.get('status', '-')} | {verdict(r)} |"
        )
    lines += ["", "## Details", "```json", json.dumps(reports, indent=2, ensure_ascii=False), "```"]
    return "\n".join(lines)


def main(argv):
    chosen = argv or list(SITES)
    unknown = [c for c in chosen if c not in SITES]
    if unknown:
        print(f"Unknown site(s): {unknown}. Choose from: {list(SITES)}")
        return 1
    reports = []
    for slug in chosen:
        print(f"Probing {slug} ...", flush=True)
        try:
            reports.append(probe_site(slug, SITES[slug]))
        except Exception as e:  # never let one site stop the rest
            reports.append({"slug": slug, "base_url": SITES[slug], "robots": {}, "error": f"{type(e).__name__}: {e}"})
        print(f"  -> {verdict(reports[-1]) if 'homepage' in reports[-1] else reports[-1].get('error')}", flush=True)
    with open("probe_report.json", "w", encoding="utf-8") as f:
        json.dump(reports, f, indent=2, ensure_ascii=False)
    with open("probe_report.md", "w", encoding="utf-8") as f:
        f.write(to_markdown(reports))
    print("\nDone. Send me probe_report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
