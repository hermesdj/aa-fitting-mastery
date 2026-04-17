"""Settings for Fitting Mastery."""

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
