"""Field extractors for Ethiopian and international job postings."""
from __future__ import annotations

import re
from typing import Any

from .cleaners import clean_text
from .models import EligibilityType, JobTypeType, WorkModeType

# ---------------------------------------------------------------------------
# City & Country Dictionaries
# ---------------------------------------------------------------------------
ETHIOPIAN_CITIES: dict[str, list[str]] = {
    "Addis Ababa": [
        r"\baddis\s*ababa\b", r"\bfinfinne\b", r"\bአዲስ\s*አበባ\b", r"\bፊንፊኔ\b",
        r"\bsheger\b", r"\bሸገር\b",
    ],
    "Hawassa": [r"\bhawassa\b", r"\bawassa\b", r"\bሀዋሳ\b", r"\bሐዋሳ\b"],
    "Bahir Dar": [r"\bbahir\s*dar\b", r"\bባሕር\s*ዳር\b", r"\bባህር\s*ዳር\b"],
    "Dire Dawa": [r"\bdire\s*dawa\b", r"\bድሬዳዋ\b", r"\bድሬ\s*ዳዋ\b"],
    "Mekelle": [r"\bmekelle\b", r"\bmekele\b", r"\bመቀሌ\b", r"\bመቐለ\b"],
    "Adama": [r"\badama\b", r"\bnazret\b", r"\bnazareth\b", r"\bአዳማ\b", r"\bናዝሬት\b"],
    "Gondar": [r"\bgondar\b", r"\bgonder\b", r"\bጎንደር\b"],
    "Jimma": [r"\bjimma\b", r"\bጅማ\b"],
    "Bishoftu": [r"\bbishoftu\b", r"\bdebre\s*zeit\b", r"\bቢሾፍቱ\b", r"\bደብረዘይት\b"],
    "Dessie": [r"\bdessie\b", r"\bደሴ\b"],
    "Harar": [r"\bharar\b", r"\bሐረር\b", r"\bሀረር\b"],
    "Jigjiga": [r"\bjigjiga\b", r"\bjijiga\b", r"\bጅግጅጋ\b"],
    "Wolaita Sodo": [r"\bwolaita\s*sodo\b", r"\bsodo\b", r"\bሶዶ\b"],
    "Arba Minch": [r"\barba\s*minch\b", r"\bአርባ\s*ምንጭ\b"],
    "Debre Birhan": [r"\bdebre\s*birhan\b", r"\bደብረ\s*ብርሃን\b"],
    "Dilla": [r"\bdilla\b", r"\bዲላ\b"],
    "Asosa": [r"\basosa\b", r"\bassosa\b", r"\bአሶሳ\b"],
    "Gambela": [r"\bgambela\b", r"\bጋምቤላ\b"],
    "Semera": [r"\bsemera\b", r"\bሰመራ\b"],
}

_COMPILED_CITIES = [
    (canonical, [re.compile(p, re.IGNORECASE) for p in patterns])
    for canonical, patterns in ETHIOPIAN_CITIES.items()
]

# ---------------------------------------------------------------------------
# Title & Employer Patterns
# ---------------------------------------------------------------------------
_RE_TITLE_PREFIX = re.compile(
    r"^(?:job\s*title|position|role|vacancy|የስራ\s*መደቡ?|የስራው\s*አይነት)\s*[:፦\-]\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_RE_EMPLOYER_PREFIX = re.compile(
    r"^(?:employer|company|organization|hiring\s*organization|ድርጅት|የመስሪያ\s*ቤቱ\s*ስም)\s*[:፦\-]\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_RE_EMPLOYER_SUFFIXES = re.compile(
    r"\b(?:S\.?C\.?|P\.?L\.?C\.?|አ\.?ማ|ኃ\/የተ\/የግ\/ማ|Bank|ባንክ|Hospital|ሆስፒታል|University|ዩኒቨርሲቲ|NGO)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Job Type & Work Mode
# ---------------------------------------------------------------------------
_WORK_MODE_PATTERNS: list[tuple[WorkModeType, list[re.Pattern]]] = [
    ("remote", [
        re.compile(r"\b(?:remote|work\s*from\s*home|wfh|telecommute|telework)\b", re.IGNORECASE),
        re.compile(r"በ?ርቀት\s*(?:የሚሰራ)?"),
    ]),
    ("hybrid", [
        re.compile(r"\bhybrid\b", re.IGNORECASE),
        re.compile(r"የተደባለቀ"),
    ]),
    ("onsite", [
        re.compile(r"\b(?:on-?site|in-?person|office\s*based)\b", re.IGNORECASE),
        re.compile(r"በቦታው\s*(?:ተገኝቶ)?"),
    ]),
]

_JOB_TYPE_PATTERNS: list[tuple[JobTypeType, list[re.Pattern]]] = [
    ("internship", [
        re.compile(r"\b(?:internship|intern|trainee)\b", re.IGNORECASE),
        re.compile(r"ተለማማጅ|ልምምድ"),
    ]),
    ("volunteer", [
        re.compile(r"\b(?:volunteer|voluntary)\b", re.IGNORECASE),
        re.compile(r"በጎ\s*ፈቃድ"),
    ]),
    ("freelance", [
        re.compile(r"\b(?:freelance|gig)\b", re.IGNORECASE),
        re.compile(r"ጊዚያዊ"),
    ]),
    ("contract", [
        re.compile(r"\b(?:contract|fixed-?term)\b", re.IGNORECASE),
        re.compile(r"ኮንትራት|የኮንትራት"),
    ]),
    ("part_time", [
        re.compile(r"\bpart-?time\b", re.IGNORECASE),
        re.compile(r"የትርፍ\s*ሰዓት|የትርፍ\s*ጊዜ"),
    ]),
    ("full_time", [
        re.compile(r"\bfull-?time|permanent\b", re.IGNORECASE),
        re.compile(r"ቋሚ|የሙሉ\s*ጊዜ"),
    ]),
]

# ---------------------------------------------------------------------------
# Education & Experience
# ---------------------------------------------------------------------------
_EDUCATION_LEVELS: list[tuple[str, list[re.Pattern]]] = [
    ("PhD", [re.compile(r"\b(?:phd|doctorate)\b", re.IGNORECASE), re.compile(r"ዶክተሬት")]),
    ("Master's", [re.compile(r"\b(?:master'?s?|msc|ma|mba)\b", re.IGNORECASE), re.compile(r"ማስተርስ|ሁለተኛ\s*ዲግሪ")]),
    ("Bachelor's", [re.compile(r"\b(?:bachelor'?s?|bsc|ba|degree)\b", re.IGNORECASE), re.compile(r"ዲግሪ|የመጀመሪያ\s*ዲግሪ")]),
    ("Diploma", [re.compile(r"\bdiploma\b", re.IGNORECASE), re.compile(r"ዲፕሎማ")]),
    ("TVET / Level", [re.compile(r"\b(?:tvet|level\s*(?:[1-5]|i{1,3}|iv|v))\b", re.IGNORECASE), re.compile(r"ቴክኒክና\s*ሙያ|ደረጃ\s*[1-5]")]),
    ("High School", [re.compile(r"\b(?:high\s*school|10th|12th)\s*(?:grade|complete)?\b", re.IGNORECASE), re.compile(r"የሁለተኛ\s*ደረጃ|10ኛ|12ኛ")]),
]

_RE_EXP_ZERO = re.compile(
    r"\b(?:0\s*years?|fresh\s*graduate|no\s*experience(?:\s*required)?|entry\s*level)\b"
    r"|ምንም\s*(?:የስራ\s*)?ልምድ\s*(?:የማይጠይቅ)?|0\s*ዓመት",
    re.IGNORECASE,
)
_RE_EXP_YEARS = [
    re.compile(r"(?:min(?:imum)?\s*[:\s]*)?(\d{1,2})\s*(?:to|-)\s*\d{1,2}\s*years?", re.IGNORECASE),
    re.compile(r"(?:min(?:imum)?\s*[:\s]*)?(\d{1,2})\+?\s*years?\s+(?:of\s+)?experience", re.IGNORECASE),
    re.compile(r"(\d{1,2})\s*years?\s+(?:of\s+)?work\s+experience", re.IGNORECASE),
    re.compile(r"(\d{1,2})\s*ዓመት\s*(?:የስራ\s*)?ልምድ", re.IGNORECASE),
    re.compile(r"ከ\s*(\d{1,2})\s*ዓመት\s*በላይ", re.IGNORECASE),
]

_RE_EMAILS = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", re.IGNORECASE)
_RE_URLS = re.compile(r"https?://[^\s/$.?#].[^\s]*", re.IGNORECASE)
_RE_TG_HANDLES = re.compile(r"(?<!\w)@[a-zA-Z0-9_]{4,}", re.IGNORECASE)
_RE_PHONE = re.compile(r"(?:\+2519\d{8}|09\d{8}|\+2517\d{8}|07\d{8})")


# ---------------------------------------------------------------------------
# Extractor Functions
# ---------------------------------------------------------------------------
def extract_title(text: str, meta: dict[str, Any]) -> str:
    """Extract and sanitize job title."""
    candidate = meta.get("title")
    if candidate and len(candidate.strip()) > 2:
        return _clean_title(candidate)

    m = _RE_TITLE_PREFIX.search(text)
    if m:
        return _clean_title(m.group(1))

    # Fallback to the first non-empty line
    for line in text.splitlines():
        line = line.strip()
        if len(line) > 3 and not line.startswith("http") and not line.startswith("@"):
            return _clean_title(line[:120])

    return "Untitled Job"


def _clean_title(t: str) -> str:
    t = re.sub(r"^(?:urgent\s*vacancy|job\s*vacancy|new\s*job|vacancy\s*announcement)\s*[:\-]\s*", "", t, flags=re.I)
    t = re.sub(r"\s+(?:via|on|-|–|\|)\s*(?:GeezJobs|Ethiojobs|HahuJobs|AbayJobs|Muyalogy|EthiopianReporterJobs).*$", "", t, flags=re.I)
    t = re.sub(r"[\*#_\[\]]", "", t)
    return clean_text(t)[:200]


def extract_employer(text: str, meta: dict[str, Any]) -> str | None:
    """Extract employer or organization name."""
    candidate = meta.get("employer")
    if candidate and len(candidate.strip()) > 1:
        return clean_text(candidate)[:200]

    m = _RE_EMPLOYER_PREFIX.search(text)
    if m:
        return clean_text(m.group(1))[:200]

    # Search for lines containing company suffixes
    for line in text.splitlines()[:15]:
        if _RE_EMPLOYER_SUFFIXES.search(line) and len(line.strip()) < 80:
            return clean_text(line)[:200]

    return None


def extract_location(text: str, meta: dict[str, Any]) -> tuple[str | None, str | None]:
    """Extract (location_city, location_country). Default country is 'ET' for Ethiopian sources."""
    meta_loc = meta.get("location")
    search_target = f"{meta_loc or ''}\n{text[:1000]}"

    for city_name, patterns in _COMPILED_CITIES:
        for pat in patterns:
            if pat.search(search_target):
                return city_name, "ET"

    if meta_loc:
        return clean_text(meta_loc)[:100], "ET"

    return None, "ET"


def extract_work_mode(text: str, meta: dict[str, Any], city: str | None = None) -> WorkModeType | None:
    """Determine work mode: onsite, hybrid, or remote."""
    if meta.get("remote") in (True, "yes", "true", "True"):
        return "remote"

    target = f"{meta.get('work_mode', '')} {text[:1000]}"
    for mode, patterns in _WORK_MODE_PATTERNS:
        for pat in patterns:
            if pat.search(target):
                return mode

    # If physical city is identified and no remote keyword found, default to onsite
    if city:
        return "onsite"

    return None


def extract_job_type(text: str, meta: dict[str, Any]) -> JobTypeType | None:
    """Determine job type."""
    meta_type = str(meta.get("job_type", "")).lower()
    target = f"{meta_type} {text[:1000]}"

    for jtype, patterns in _JOB_TYPE_PATTERNS:
        for pat in patterns:
            if pat.search(target):
                return jtype

    return "full_time"  # Most common default for formal vacancies


def extract_education_level(text: str) -> str | None:
    """Identify required education level."""
    for edu_name, patterns in _EDUCATION_LEVELS:
        for pat in patterns:
            if pat.search(text):
                return edu_name
    return None


def extract_experience_years(text: str) -> int | None:
    """Extract minimum years of required work experience."""
    if _RE_EXP_ZERO.search(text):
        return 0

    for pat in _RE_EXP_YEARS:
        m = pat.search(text)
        if m:
            try:
                years = int(m.group(1))
                if 0 <= years <= 30:
                    return years
            except ValueError:
                pass
    return None


def extract_apply_info(text: str, meta: dict[str, Any]) -> str | None:
    """Gather contact, apply link, email, or telegram handle."""
    if meta.get("apply"):
        return clean_text(meta["apply"])[:500]

    emails = _RE_EMAILS.findall(text)
    urls = [u for u in _RE_URLS.findall(text) if "t.me" not in u and not u.endswith((".png", ".jpg", ".jpeg"))]

    # Include hyperlinks extracted from Telegram posts or HTML metadata
    for link in meta.get("links", []):
        if link not in urls and not link.endswith((".png", ".jpg", ".jpeg")) and "t.me/s/" not in link:
            urls.append(link)

    handles = _RE_TG_HANDLES.findall(text)
    phones = _RE_PHONE.findall(text)

    parts: list[str] = []
    if urls:
        parts.append(f"Apply URL: {urls[0]}")
    if emails:
        parts.append(f"Email: {emails[0]}")
    if handles:
        parts.append(f"Telegram: {handles[0]}")
    if phones and not emails and not urls:
        parts.append(f"Phone: {phones[0]}")

    if parts:
        return " | ".join(parts)[:500]

    return None


def extract_eligibility(text: str, meta: dict[str, Any]) -> tuple[EligibilityType, str | None]:
    """Check whether posting is restricted to Ethiopians, worldwide, etc."""
    meta_note = meta.get("eligibility_note")
    search_target = f"{meta_note or ''} {text[:1000]}".lower()

    if "ethiopian nationals only" in search_target or "ethiopian national" in search_target:
        return "ethiopians", "Ethiopian nationals only"
    if "worldwide" in search_target or "all nationalities" in search_target:
        return "worldwide", "Open to all nationalities"
    if meta_note:
        return "restricted", meta_note

    return "unknown", None
