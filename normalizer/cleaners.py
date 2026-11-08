"""Text cleaning and language detection."""
from __future__ import annotations

import html as _html
import re

_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_MULTIPLE_SPACES = re.compile(r"[ \t]+")
_MULTIPLE_NEWLINES = re.compile(r"\n{3,}")

# Telegram promotional footer patterns
_TG_PROMO_PATTERNS = [
    re.compile(r"(?:join|subscribe|follow)\s+(?:our\s+)?(?:telegram\s+)?channel\s*:?[\s\S]*$", re.IGNORECASE),
    re.compile(r"(?:ለተጨማሪ\s+ስራዎች|ይቀላቀሉ|ሼር\s+ያድርጉ)[\s\S]*$", re.IGNORECASE),
    re.compile(r"https?://t\.me/[a-zA-Z0-9_+/]+(?:\s+join)?", re.IGNORECASE),
]


def clean_text(text: str | None) -> str:
    """Normalize raw text: unescape HTML, clean whitespace, and strip common promotional clutter."""
    if not text:
        return ""

    s = _html.unescape(text)
    s = _ZERO_WIDTH.sub("", s)
    s = s.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")

    # Clean multiple spaces per line
    lines = []
    for line in s.splitlines():
        cleaned = _MULTIPLE_SPACES.sub(" ", line).strip()
        lines.append(cleaned)

    result = "\n".join(lines).strip()
    result = _MULTIPLE_NEWLINES.sub("\n\n", result)
    return result


def strip_telegram_footer(text: str) -> str:
    """Remove channel subscribe links and promotional boilerplate at the end of Telegram posts."""
    cleaned = text
    for pattern in _TG_PROMO_PATTERNS:
        cleaned = pattern.sub("", cleaned).strip()
    return cleaned


def detect_language(text: str | None) -> str:
    """Classify text language as 'am' (Amharic), 'en' (English), or 'mixed'.

    Uses Ethiopic script range (U+1200 - U+137F) vs Latin characters.
    """
    if not text:
        return "en"

    ethiopic_chars = 0
    latin_chars = 0

    for ch in text:
        code = ord(ch)
        if 0x1200 <= code <= 0x137F:
            ethiopic_chars += 1
        elif (0x0041 <= code <= 0x005A) or (0x0061 <= code <= 0x007A):
            latin_chars += 1

    total = ethiopic_chars + latin_chars
    if total < 10:
        return "en"

    eth_ratio = ethiopic_chars / total
    latin_ratio = latin_chars / total

    # If both have significant presence (> 20%), consider it mixed
    if eth_ratio >= 0.20 and latin_ratio >= 0.20:
        return "mixed"
    if eth_ratio > 0.50:
        return "am"
    return "en"
