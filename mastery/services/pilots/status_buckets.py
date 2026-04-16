"""Shared status-bucket helpers for pilot and summary views."""

from mastery import app_settings

BUCKET_ELITE = "elite"
BUCKET_ALMOST_ELITE = "almost_elite"
BUCKET_CAN_FLY = "can_fly"
BUCKET_ALMOST_FIT = "almost_fit"
BUCKET_NEEDS_TRAINING = "needs_training"

BUCKET_ORDER = [
    BUCKET_ELITE,
    BUCKET_ALMOST_ELITE,
    BUCKET_CAN_FLY,
    BUCKET_ALMOST_FIT,
    BUCKET_NEEDS_TRAINING,
]

BUCKET_LABELS = {
    BUCKET_ELITE: "Elite",
    BUCKET_ALMOST_ELITE: "Almost elite",
    BUCKET_CAN_FLY: "Can fly",
    BUCKET_ALMOST_FIT: "Almost fit",
    BUCKET_NEEDS_TRAINING: "Needs training",
}

BUCKET_RANK = {
    BUCKET_ELITE: 5,
    BUCKET_ALMOST_ELITE: 4,
    BUCKET_CAN_FLY: 3,
    BUCKET_ALMOST_FIT: 2,
    BUCKET_NEEDS_TRAINING: 1,
}


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


def is_flyable_bucket(bucket: str) -> bool:
    """Return whether a status bucket means the character can fly now."""
    return bucket in {BUCKET_ELITE, BUCKET_ALMOST_ELITE, BUCKET_CAN_FLY}


def matches_bucket_filter(progress: dict, filter_name: str) -> bool:
    """Return whether a progress payload matches a bucket/filter name."""
    if filter_name == "all":
        return True

    bucket = bucket_for_progress(progress)
    if filter_name == "can_fly_now":
        return is_flyable_bucket(bucket)
    if filter_name == "almost_required":
        return bucket == BUCKET_ALMOST_FIT
    return bucket == filter_name


def bucket_choice_list(include_all: bool = False, all_label: str = "All") -> list[tuple[str, str]]:
    """Return ordered UI choices for bucket-based filters."""
    choices = []
    if include_all:
        choices.append(("all", all_label))
    choices.extend((bucket, BUCKET_LABELS[bucket]) for bucket in BUCKET_ORDER)
    return choices
