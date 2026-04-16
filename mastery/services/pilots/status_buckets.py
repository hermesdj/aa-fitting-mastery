"""Shared status-bucket helpers for pilot and summary views."""

from mastery import app_settings

BUCKET_ELITE = "elite"
BUCKET_ALMOST_ELITE = "almost_elite"
BUCKET_CAN_FLY = "can_fly"
BUCKET_ALMOST_FIT = "almost_fit"
BUCKET_NEEDS_TRAINING = "needs_training"


def thresholds() -> dict:
    """Return configured percentage thresholds used by status buckets."""
    return {
        "elite_recommended": float(app_settings.MASTERY_STATUS_ELITE_RECOMMENDED_PCT),
        "almost_elite_recommended": float(app_settings.MASTERY_STATUS_ALMOST_ELITE_RECOMMENDED_PCT),
        "almost_fit_required": float(app_settings.MASTERY_STATUS_ALMOST_FIT_REQUIRED_PCT),
    }


def bucket_for_progress(progress: dict) -> str:
    """Compute status bucket for progress payloads shared across mastery views."""
    can_fly = bool(progress.get("can_fly"))
    required_pct = float(progress.get("required_pct") or 0)
    recommended_pct = float(progress.get("recommended_pct") or 0)

    configured = thresholds()
    elite_threshold = configured["elite_recommended"]
    almost_elite_threshold = configured["almost_elite_recommended"]
    almost_fit_threshold = configured["almost_fit_required"]

    if can_fly and recommended_pct >= elite_threshold:
        return BUCKET_ELITE
    if can_fly and recommended_pct > almost_elite_threshold:
        return BUCKET_ALMOST_ELITE
    if can_fly:
        return BUCKET_CAN_FLY
    if required_pct > almost_fit_threshold:
        return BUCKET_ALMOST_FIT
    return BUCKET_NEEDS_TRAINING

