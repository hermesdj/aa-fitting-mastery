"""Settings for Fitting Mastery."""

from app_utils.app_settings import clean_setting

MASTERY_PLAN_ESTIMATE_SP_PER_HOUR = clean_setting(
    "MASTERY_PLAN_ESTIMATE_SP_PER_HOUR", 1800, min_value=1
)
"""Training speed used to estimate plan duration in fitting previews."""

