"""Core normalization pipeline connecting cleaners, extractors, calendars, and risk scoring."""
from __future__ import annotations

import datetime
from typing import Any

from .cleaners import clean_text, detect_language, strip_telegram_footer
from .dates import parse_date
from .extractors import (
    extract_apply_info,
    extract_education_level,
    extract_eligibility,
    extract_employer,
    extract_experience_years,
    extract_job_type,
    extract_location,
    extract_title,
    extract_work_mode,
)
from .models import NormalizedJob
from .scam_detector import evaluate_risk
from .skills import extract_skills


def normalize_raw_capture(
    raw_id: int,
    source_id: int,
    external_id: str,
    url: str | None,
    raw_text: str,
    raw_meta: dict[str, Any] | None = None,
    content_hash: str | None = None,
    fetched_at: datetime.datetime | None = None,
) -> NormalizedJob:
    """Transform a single raw database record into a clean NormalizedJob."""
    meta = raw_meta or {}
    text_clean = clean_text(raw_text)

    # 1. Clean Telegram promo banners if it is from a telegram channel
    if "channel" in meta or "/t.me/" in (url or ""):
        text_clean = strip_telegram_footer(text_clean)

    # 2. Language detection
    lang = detect_language(text_clean)

    # 3. Title & Employer
    title = extract_title(text_clean, meta)
    employer = extract_employer(text_clean, meta)

    # 4. Location & Country
    city, country = extract_location(text_clean, meta)

    # 5. Work mode & Job type
    work_mode = extract_work_mode(text_clean, meta, city)
    job_type = extract_job_type(text_clean, meta)

    # 6. Education & Experience
    edu = extract_education_level(text_clean)
    exp = extract_experience_years(text_clean)

    # 7. Apply & Eligibility
    apply_info = extract_apply_info(text_clean, meta)
    eligibility, elig_note = extract_eligibility(text_clean, meta)

    # 8. Dates: Deadline & Posted
    ref_date = (fetched_at.date() if fetched_at else datetime.date.today())
    raw_deadline = meta.get("deadline") or meta.get("closing_date")
    # If not in meta, scan text for deadline phrases
    if not raw_deadline:
        raw_deadline = text_clean

    deadline = parse_date(raw_deadline, reference_date=ref_date)

    raw_posted = meta.get("posted_at") or meta.get("posted")
    posted_date = parse_date(raw_posted, reference_date=ref_date)
    posted_at = (
        datetime.datetime.combine(posted_date, datetime.time.min, tzinfo=datetime.timezone.utc)
        if posted_date
        else fetched_at
    )

    # 9. Scam / Risk Scoring
    risk_score, risk_flags = evaluate_risk(text_clean, employer=employer, apply_info=apply_info)

    # 10. Canonical Skill Tagging
    combined_content = f"{title}\n{employer or ''}\n{text_clean}"
    skills = extract_skills(combined_content)

    # 11. Status (open vs expired)
    status = "open"
    if deadline and deadline < datetime.date.today():
        status = "expired"

    return NormalizedJob(
        raw_id=raw_id,
        source_id=source_id,
        external_id=external_id,
        url=url,
        title=title,
        employer_name=employer,
        description=text_clean,
        language=lang,  # type: ignore[arg-type]
        location_city=city,
        location_country=country,
        work_mode=work_mode,
        job_type=job_type,
        eligibility=eligibility,
        eligibility_note=elig_note,
        deadline=deadline,
        posted_at=posted_at,
        education_level=edu,
        experience_years_min=exp,
        apply_info=apply_info,
        risk_score=risk_score,
        risk_flags=risk_flags,
        content_hash=content_hash,
        status=status,
        skills=skills,
        meta=meta,
    )
