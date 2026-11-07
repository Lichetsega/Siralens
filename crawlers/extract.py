"""
Turning pages into text and fields. No site-specific code lives here.

Order of preference for a job page:
  1. schema.org JobPosting JSON-LD (structured, most reliable)
  2. generic extraction (title + main text, page chrome removed)
  3. optional per-source CSS overrides from sources.yaml ('css:' block)
"""
from __future__ import annotations

import html as _html
import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

MAX_TEXT = 30_000

# ---------------------------------------------------------------- text helpers
_BLOCK_TAGS = ["p", "div", "li", "ul", "ol", "tr", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6", "table"]
_CELL_TAGS = ["td", "th", "dt", "dd"]


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    out: list[str] = []
    blank = False
    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            out.append(line)
            blank = False
        elif out and not blank:
            out.append("")
            blank = True
    return "\n".join(out).strip()


def node_to_text(node) -> str:
    """Readable text from an element: block tags become line breaks, inline tags stay inline."""
    for br in node.find_all("br"):
        br.replace_with("\n")
    for li in node.find_all("li"):
        li.insert(0, "- ")
    for tag in node.find_all(_CELL_TAGS):
        tag.append(" ")
    for tag in node.find_all(_BLOCK_TAGS):
        tag.append("\n")
    return clean_text(node.get_text(""))


def strip_html(fragment: str) -> str:
    """Plain text from an HTML fragment (or from text that has no tags)."""
    if not fragment:
        return ""
    if "<" not in fragment:
        return clean_text(_html.unescape(fragment))
    return node_to_text(BeautifulSoup(fragment, "html.parser"))


def dotget(obj: Any, path: str | None, default: Any = None) -> Any:
    """dotget({'a': [{'b': 1}]}, 'a.0.b') -> 1"""
    if not path:
        return default
    cur = obj
    for part in str(path).split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.lstrip("-").isdigit():
            i = int(part)
            cur = cur[i] if -len(cur) <= i < len(cur) else None
        else:
            return default
        if cur is None:
            return default
    return cur


def names(value: Any) -> list[str]:
    """Names from a string, {'name': ..}, or a list of those."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        return names(value.get("name"))
    if isinstance(value, list):
        out: list[str] = []
        for v in value:
            out.extend(names(v))
        return out
    return [str(value)]


# ---------------------------------------------------------------- URLs
_TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
             "fbclid", "gclid", "mc_cid", "mc_eid", "sessionid", "jsessionid", "sid", "sess"}

# Whole path segments that mean "not a job page". Matched exactly, never as substrings
# ("accountant" and "developer" must NOT be blocked by "account" or "dev").
BLOCKED_SEGMENTS = frozenset({
    "login", "signin", "sign-in", "logout", "register", "signup", "sign-up", "account", "my-account",
    "profile", "password", "forgot-password", "category", "categories", "tag", "tags", "author", "page",
    "search", "feed", "rss", "wp-admin", "wp-json", "wp-content", "wp-login.php", "cart", "checkout",
    "about", "about-us", "contact", "contact-us", "privacy", "privacy-policy", "terms", "terms-of-service",
    "faq", "advertise", "pricing", "sitemap",
})
BLOCKED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".css", ".js", ".zip", ".rar",
                      ".mp4", ".mp3", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".xml", ".json")

DEFAULT_LINK_PATTERN = r"/(?:jobs?|job-detail|vacanc\w*|careers?|positions?|openings?)/[^/?#]+"


def normalize_url(url: str) -> str:
    """Canonical form for ids and de-duplication: lowercase host, no fragment, no tracking params, no trailing slash."""
    p = urlparse(url.strip())
    path = re.sub(r"/{2,}", "/", p.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query) if k.lower() not in _TRACKING))
    return urlunparse(((p.scheme or "https").lower(), p.netloc.lower(), path, "", query, ""))


def host_key(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def is_candidate(url: str, base_url: str, pattern: re.Pattern, exclude: re.Pattern | None = None) -> bool:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or host_key(url) != host_key(base_url):
        return False
    path = p.path.lower()
    if path.endswith(BLOCKED_EXTENSIONS):
        return False
    if any(seg in BLOCKED_SEGMENTS for seg in (s for s in path.split("/") if s)):
        return False
    if not pattern.search(url):
        return False
    return not (exclude and exclude.search(url))


def extract_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    seen: dict[str, None] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        seen.setdefault(normalize_url(urljoin(base_url, href)), None)
    return list(seen)


# ---------------------------------------------------------------- JSON-LD
def _search_jobposting(data: Any) -> dict | None:
    if isinstance(data, dict):
        t = data.get("@type")
        if "JobPosting" in (t if isinstance(t, list) else [t]):
            return data
        for v in data.values():
            found = _search_jobposting(v)
            if found:
                return found
    elif isinstance(data, list):
        for v in data:
            found = _search_jobposting(v)
            if found:
                return found
    return None


def find_jobposting(soup: BeautifulSoup) -> dict | None:
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text()
        for strict in (True, False):
            try:
                data = json.loads(raw, strict=strict)
                break
            except ValueError:
                data = None
        if data is None:
            continue
        jp = _search_jobposting(data)
        if jp:
            return jp
    return None


def _join(values: list[str]) -> str:
    return ", ".join(v for v in values if v)


def _location(jp: dict) -> str:
    locs = jp.get("jobLocation")
    if isinstance(locs, dict):
        locs = [locs]
    parts: list[str] = []
    for loc in locs or []:
        if not isinstance(loc, dict):
            continue
        addr = loc.get("address")
        if isinstance(addr, str):
            parts.append(addr)
        elif isinstance(addr, dict):
            bits = [_join(names(addr.get(k))) for k in ("addressLocality", "addressRegion", "addressCountry")]
            parts.append(_join(bits))
        elif loc.get("name"):
            parts.append(str(loc["name"]))
    return _join(parts)


def fields_from_jobposting(jp: dict) -> dict:
    emp = jp.get("employmentType")
    return {
        "title": clean_text(str(jp.get("title") or "")),
        "employer": _join(names(jp.get("hiringOrganization"))),
        "location": _location(jp),
        "deadline": str(jp.get("validThrough") or ""),
        "posted": str(jp.get("datePosted") or ""),
        "job_type": _join(names(emp)) if isinstance(emp, (list, dict, str)) else "",
        "remote": str(jp.get("jobLocationType") or "").upper() == "TELECOMMUTE",
        "eligibility_note": _join(names(jp.get("applicantLocationRequirements"))),
        "description": strip_html(str(jp.get("description") or "")),
    }


# ---------------------------------------------------------------- generic pages
_CHROME_TAGS = ["script", "style", "noscript", "iframe", "svg", "nav", "footer", "aside", "form", "button"]
# Note: <header> is NOT removed. On many sites the job title and employer live inside it.
_CHROME_CSS = ['[class*="related"]', '[class*="similar"]', '[id*="related"]', '[class*="cookie"]',
               '[class*="breadcrumb"]', '[class*="sidebar"]', '[class*="newsletter"]', '[class*="share"]',
               '[class*="social"]', '[class*="comment"]', ".widget"]
_BODY_SELECTORS = ["article", "main", '[role="main"]', ".entry-content", ".job-description", ".job-details",
                   ".post-content", "#content", ".content"]


def _safe_decompose(el) -> None:
    try:
        el.decompose()
    except Exception:
        pass


def _meta(soup: BeautifulSoup, prop: str) -> str:
    el = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
    return clean_text(el["content"]) if el and el.get("content") else ""


def _generic_fields(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = (clean_text(h1.get_text(" ")) if h1 else "") or _meta(soup, "og:title") \
        or (clean_text(soup.title.get_text()) if soup.title else "")

    for tag in soup.find_all(_CHROME_TAGS):
        _safe_decompose(tag)
    for sel in _CHROME_CSS:
        for el in soup.select(sel):
            _safe_decompose(el)

    container = None
    for sel in _BODY_SELECTORS:
        el = soup.select_one(sel)
        if el is not None and len(el.get_text(" ", strip=True)) >= 200:
            container = el
            break
    container = container or soup.body or soup
    body = node_to_text(container)

    if len(body) < 100:  # over-cleaned: retry keeping everything except scripts and styles
        raw = BeautifulSoup(html, "html.parser")
        for tag in raw.find_all(["script", "style", "noscript"]):
            _safe_decompose(tag)
        body = node_to_text(raw.body or raw)
    return {"title": title, "description": body}


def _apply_css(html: str, fields: dict, css: dict) -> None:
    if not css:
        return
    soup = BeautifulSoup(html, "html.parser")
    for key in ("title", "employer", "location", "deadline", "job_type"):
        sel = css.get(key)
        el = soup.select_one(sel) if sel else None
        if el is not None:
            fields[key] = clean_text(el.get_text(" "))
    if css.get("apply"):
        el = soup.select_one(css["apply"])
        if el is not None:
            fields["apply"] = clean_text(el.get_text(" "))
    if css.get("body"):
        el = soup.select_one(css["body"])
        if el is not None:
            fields["description"] = node_to_text(el)


def extract_job_page(html: str, url: str, css: dict | None = None) -> dict:
    jp = find_jobposting(BeautifulSoup(html, "html.parser"))
    if jp:
        fields = fields_from_jobposting(jp)
        fields["extraction"] = "jsonld"
        if len(fields.get("description", "")) < 100:  # JSON-LD with a stub description
            fields["description"] = _generic_fields(html)["description"]
    else:
        fields = _generic_fields(html)
        fields["extraction"] = "generic"
    _apply_css(html, fields, css or {})
    fields["url"] = url
    return fields


_EXPIRED = re.compile(r"(job|vacancy|position|posting|advert)\s+(is|has)\s+(been\s+)?(expired|closed|filled)"
                      r"|no longer (available|accepting)|sorry,? this job is expired", re.I)


def looks_expired(fields: dict) -> bool:
    head = f"{fields.get('title', '')}\n{fields.get('description', '')[:600]}"
    return bool(_EXPIRED.search(head))


def compose_raw_text(fields: dict) -> str:
    head = [
        ("Title", fields.get("title")), ("Employer", fields.get("employer")),
        ("Location", fields.get("location")), ("Job type", fields.get("job_type")),
        ("Remote", "yes" if fields.get("remote") else ""), ("Open to", fields.get("eligibility_note")),
        ("Deadline", fields.get("deadline")), ("Posted", fields.get("posted")),
        ("Apply", fields.get("apply")),
    ]
    lines = [f"{k}: {v}" for k, v in head if v]
    text = "\n".join(lines)
    if fields.get("description"):
        text += "\n\n" + fields["description"]
    return clean_text(text)[:MAX_TEXT]


def meta_from_fields(fields: dict) -> dict:
    keep = ("title", "employer", "location", "deadline", "posted", "job_type", "remote", "eligibility_note",
            "extraction", "url")
    return {k: fields[k] for k in keep if fields.get(k) not in (None, "", False)}
