"""Scam & fraud detection heuristics for Ethiopian job postings."""
from __future__ import annotations

import re

# Upfront fee patterns (the most common scam in telegram job channels)
_RE_UPFRONT_FEE = re.compile(
    r"(?:registration|service|application|processing)\s+(?:fee|charge|payment)"
    r"|pay\s+(?:before|advance|upfront)"
    r"|መመዝገቢያ|ቅድመ\s*ክፍያ|የአገልግሎት\s*ክፍያ|ክፍያ"
    r"|ብር\s*(?:ይክፈሉ|አስገቡ|አስገብታችሁ|ክፈሉ|ከፍላችሁ|ይላኩ|ላኩ|ልካችሁ)",
    re.IGNORECASE,
)

# Suspicious payment account numbers / personal transfers
_RE_PAYMENT_ACCOUNT = re.compile(
    r"\b1000\d{8,12}\b"  # Standard CBE personal account format
    r"|telebirr\s*(?:account|no|number)?\s*:?\s*09\d{8}"
    r"|ቴሌብር\s*(?:ቁጥር)?\s*:?\s*09\d{8}"
    r"|(?:ደረሰኝ|receipt|slip)\s*(?:ፎቶ|photo|ላኩ|send)",
    re.IGNORECASE,
)

# Unrealistic get-rich-quick claims
_RE_UNREALISTIC_EARNINGS = re.compile(
    r"(?:typing|copy\s*paste|data\s*entry)\s*job\s*.*?(?:daily|በቀን)"
    r"|በቀን\s*(?:እስከ\s*)?[1-9]\d{3,}\s*ብር"
    r"|earn\s+[1-9]\d{3,}\s*(?:birr|etb)?\s*daily"
    r"|ቀላል\s*ስራ\s*በቤትዎ\s*ሆነው",
    re.IGNORECASE,
)

# Anonymous contact only (no email or domain, just personal DM/phone)
_RE_OFFICIAL_CONTACT = re.compile(
    r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+|https?://[^\s/$.?#].[^\s]*",
    re.IGNORECASE,
)
_RE_ANON_DM = re.compile(
    r"(?:inbox|dm|contact)\s*@\w+|በውስጥ\s*መስመር\s*ያናግሩ|በቴሌግራም\s*ያናግሩ",
    re.IGNORECASE,
)


def evaluate_risk(
    text: str | None,
    employer: str | None = None,
    apply_info: str | None = None,
) -> tuple[int, list[str]]:
    """Evaluate job posting risk score (0-100) and identify risk flags.

    Returns:
        (risk_score, risk_flags)
    """
    if not text:
        return 0, []

    content = f"{text} {apply_info or ''}"
    score = 0
    flags: list[str] = []

    # 1. Upfront fee requested (+50)
    if _RE_UPFRONT_FEE.search(content):
        score += 50
        flags.append("upfront_fee")

    # 2. Personal bank account / deposit receipt required (+40)
    if _RE_PAYMENT_ACCOUNT.search(content):
        score += 40
        flags.append("suspicious_payment_account")

    # 3. Unrealistic earnings / copy paste scam (+35)
    if _RE_UNREALISTIC_EARNINGS.search(content):
        score += 35
        flags.append("unrealistic_salary")

    # 4. Anonymous DM only with no employer or official apply portal (+25)
    has_official_contact = bool(_RE_OFFICIAL_CONTACT.search(content))
    has_anon_dm = bool(_RE_ANON_DM.search(content))
    if has_anon_dm and not has_official_contact and not employer:
        score += 25
        flags.append("anonymous_recruiter")

    # 5. Vague description without company or location (+15)
    if len(content.strip()) < 120 and not employer:
        score += 15
        flags.append("vague_description")

    # Normalize score between 0 and 100
    capped_score = min(score, 100)
    return capped_score, flags
