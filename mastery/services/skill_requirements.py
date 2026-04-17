"""Shared helpers for skill requirement extraction and normalization."""

import logging

REQUIRED_SKILL_ATTRIBUTES = [
    (182, 277),
    (183, 278),
    (184, 279),
    (1285, 1286),
    (1289, 1287),
    (1290, 1288),
]

logger = logging.getLogger(__name__)


def normalize_default_skill_map(raw_value) -> dict[int, int]:
    """Return a validated map of globally injected required skills."""
    if not isinstance(raw_value, (list, tuple)):
        logger.warning("Ignoring MASTERY_DEFAULT_SKILLS because it is not a list/tuple")
        return {}

    skill_map: dict[int, int] = {}
    for entry in raw_value:
        if not isinstance(entry, dict):
            logger.warning("Ignoring default skill entry because it is not a dict: %s", entry)
            continue

        try:
            skill_type_id = int(entry.get("type_id"))
            required_level = int(entry.get("required_level"))
        except (TypeError, ValueError):
            logger.warning("Ignoring invalid default skill entry: %s", entry)
            continue

        if skill_type_id <= 0 or not 1 <= required_level <= 5:
            logger.warning("Ignoring out-of-range default skill entry: %s", entry)
            continue

        skill_map[skill_type_id] = max(skill_map.get(skill_type_id, 0), required_level)

    return skill_map


def merge_skill_maps(primary: dict[int, int], secondary: dict[int, int]) -> dict[int, int]:
    """Merge two skill-level maps by keeping the highest level per skill."""
    merged = dict(primary)
    for skill_type_id, level in secondary.items():
        merged[skill_type_id] = max(merged.get(skill_type_id, 0), level)
    return merged
