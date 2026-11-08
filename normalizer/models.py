"""Data models for the normalization pipeline."""
from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

LanguageType = Literal["en", "am", "mixed"]
WorkModeType = Literal["onsite", "hybrid", "remote"]
JobTypeType = Literal[
    "full_time",
    "part_time",
    "contract",
    "freelance",
    "internship",
    "volunteer",
]
EligibilityType = Literal["ethiopians", "worldwide", "restricted", "unknown"]
JobStatusType = Literal["open", "expired", "hidden"]


@dataclass
class NormalizedJob:
    """A fully extracted and normalized job item matching the `jobs` schema."""

    raw_id: int
    source_id: int
    external_id: str
    url: str | None
    title: str
    employer_name: str | None = None
    employer_id: uuid.UUID | None = None
    description: str | None = None
    language: LanguageType | None = None
    location_city: str | None = None
    location_country: str | None = "ET"
    work_mode: WorkModeType | None = None
    job_type: JobTypeType | None = None
    eligibility: EligibilityType = "unknown"
    eligibility_note: str | None = None
    deadline: datetime.date | None = None
    posted_at: datetime.datetime | None = None
    education_level: str | None = None
    experience_years_min: int | None = None
    apply_info: str | None = None
    risk_score: int = 0
    risk_flags: list[str] = field(default_factory=list)
    content_hash: str | None = None
    dedup_group_id: uuid.UUID | None = None
    is_canonical: bool = True
    status: JobStatusType = "open"
    skills: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def is_expired(self, today: datetime.date | None = None) -> bool:
        if not self.deadline:
            return False
        ref = today or datetime.date.today()
        return self.deadline < ref
