"""Settings for Fitting Mastery."""

from django.apps import apps

from app_utils.app_settings import clean_setting

MASTERY_PLAN_ESTIMATE_SP_PER_HOUR = clean_setting(
    "MASTERY_PLAN_ESTIMATE_SP_PER_HOUR", 1800, min_value=1
)
"""Training speed used to estimate plan duration in fitting previews."""

MASTERY_STATUS_ELITE_RECOMMENDED_PCT = clean_setting(
    "MASTERY_STATUS_ELITE_RECOMMENDED_PCT", 100, min_value=0, max_value=100
)
"""Recommended coverage threshold (pct) for the Elite bucket."""

MASTERY_STATUS_ALMOST_ELITE_RECOMMENDED_PCT = clean_setting(
    "MASTERY_STATUS_ALMOST_ELITE_RECOMMENDED_PCT", 75, min_value=0, max_value=100
)
"""Recommended coverage threshold (pct) for the Almost elite bucket."""

MASTERY_STATUS_ALMOST_FIT_REQUIRED_PCT = clean_setting(
    "MASTERY_STATUS_ALMOST_FIT_REQUIRED_PCT", 90, min_value=0, max_value=100
)
"""Required coverage threshold (pct) for the Almost fit bucket."""

MASTERY_DEFAULT_SKILLS = clean_setting("MASTERY_DEFAULT_SKILLS", [])
"""Optional list of globally injected default skills for all generated skill plans."""

MASTERY_SUMMARY_PROGRESS_CACHE_TTL = clean_setting(
    "MASTERY_SUMMARY_PROGRESS_CACHE_TTL", 600, min_value=0
)
"""TTL in seconds for the P3 shared progress cache (character × skillset).
Set to 0 to disable inter-request caching entirely (useful for development)."""

def securegroups_installed() -> bool:
    """Return True when allianceauth-secure-groups is installed."""
    return apps.is_installed("securegroups")
