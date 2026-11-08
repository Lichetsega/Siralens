"""SIRALens Normalization Pipeline (Phase 2).

Consumes raw captures from `job_raw`, cleans text, parses Ethiopian & Gregorian
dates, extracts structured fields (title, employer, location, work mode, education,
experience, apply info), attaches canonical skills, flags scam/risk indicators,
deduplicates cross-source listings, and populates `jobs` and `job_skills`.
"""
from __future__ import annotations

from .models import NormalizedJob
from .pipeline import normalize_raw_capture

__all__ = ["NormalizedJob", "normalize_raw_capture"]
