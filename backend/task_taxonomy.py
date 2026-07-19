"""Shared task area taxonomy and legacy Category migration helpers."""
from __future__ import annotations

from typing import Final

AREAS: Final[tuple[str, ...]] = ("personal", "group", "university", "work")

AREA_LABELS: Final[dict[str, str]] = {
    "personal": "個人",
    "group": "グループ",
    "university": "大学",
    "work": "仕事",
}

# Existing Notion Category values are preserved for compatibility.  This mapping
# is only a fallback until the dedicated Area property has been populated.
LEGACY_CATEGORY_TO_AREA: Final[dict[str, str]] = {
    "JobHunt": "personal",
    "Sch": "university",
    "Life": "personal",
    "Work": "work",
    "Hobby": "personal",
    "Create": "personal",
    "LiT": "work",
}


def normalize_area(value: str | None) -> str | None:
    """Return one canonical internal area value, or None when unknown."""
    if not value:
        return None
    normalized = str(value).strip().casefold()
    for area in AREAS:
        if normalized == area.casefold() or normalized == AREA_LABELS[area].casefold():
            return area
    return None


def area_from_legacy_category(category: str | None) -> str | None:
    """Derive a conservative area from legacy Category values.

    Multi-select values are cached as a comma-separated string. Event is
    intentionally not mapped because its responsibility source is ambiguous.
    """
    if not category:
        return None
    for item in str(category).split(","):
        value = item.strip()
        if value in LEGACY_CATEGORY_TO_AREA:
            return LEGACY_CATEGORY_TO_AREA[value]
    return None


def resolve_area(area: str | None, category: str | None = None) -> tuple[str | None, str]:
    """Resolve explicit area first, then a legacy Category fallback."""
    explicit = normalize_area(area)
    if explicit:
        return explicit, "explicit"
    migrated = area_from_legacy_category(category)
    if migrated:
        return migrated, "legacy_category"
    return None, "unknown"
