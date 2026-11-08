"""Deduplication and canonical job grouping."""
from __future__ import annotations

import hashlib
import re
import uuid

_NORM_CHARS = re.compile(r"[^a-zA-Z0-9\u1200-\u137F]+")


def make_dedup_key(employer: str | None, title: str, deadline_str: str | None = None) -> str:
    """Generate a stable deduplication hash from normalized employer, title, and deadline."""
    norm_employer = _NORM_CHARS.sub("", (employer or "unknown").lower())
    norm_title = _NORM_CHARS.sub("", title.lower())
    norm_dl = deadline_str or "nodate"

    raw_key = f"{norm_employer}:{norm_title}:{norm_dl}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def find_or_create_dedup_group(
    dedup_key: str,
    existing_groups: dict[str, uuid.UUID],
) -> tuple[uuid.UUID, bool]:
    """Look up an existing group ID for the key, or create a new one.

    Returns:
        (dedup_group_id, is_canonical)
    """
    if dedup_key in existing_groups:
        return existing_groups[dedup_key], False

    new_id = uuid.uuid4()
    existing_groups[dedup_key] = new_id
    return new_id, True
