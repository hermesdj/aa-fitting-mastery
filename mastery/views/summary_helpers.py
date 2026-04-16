"""Helpers for pilot and summary views."""

from datetime import datetime, timedelta
from typing import cast

from allianceauth.eveonline.models import EveCharacter
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from fittings.models import Doctrine, Fitting
from memberaudit.models import Character

from mastery.models import FittingSkillsetMap, SummaryAudienceEntity, SummaryAudienceGroup
from mastery.services.pilots.status_buckets import bucket_for_progress

from .deps import pilot_access_service, pilot_progress_service

User = get_user_model()


def _get_member_characters(user):
    return Character.objects.filter(
        eve_character__character_ownership__user=user,
    ).select_related("eve_character").order_by("eve_character__character_name")


def _summary_group_users(summary_group):
    corp_ids = [
        entry.entity_id
        for entry in summary_group.entries.all()
        if entry.entity_type == SummaryAudienceEntity.TYPE_CORPORATION
    ]
    alliance_ids = [
        entry.entity_id
        for entry in summary_group.entries.all()
        if entry.entity_type == SummaryAudienceEntity.TYPE_ALLIANCE
    ]
    if not corp_ids and not alliance_ids:
        return User.objects.none()

    filters = Q()
    if corp_ids:
        filters |= Q(profile__main_character__corporation_id__in=corp_ids)
    if alliance_ids:
        filters |= Q(profile__main_character__alliance_id__in=alliance_ids)

    return User.objects.filter(profile__main_character__isnull=False).filter(filters).distinct()


def _get_summary_group_by_id(group_id_raw: str):
    if not group_id_raw:
        return None
    try:
        group_id = int(group_id_raw)
    except (TypeError, ValueError):
        return None
    return SummaryAudienceGroup.objects.filter(id=group_id).prefetch_related("entries").first()


def _get_pilot_detail_characters(user, summary_group=None):
    # Elevated cross-account access is only allowed within an explicit summary group scope.
    if user.has_perm("mastery.doctrine_summary") and summary_group is not None:
        eligible_users = _summary_group_users(summary_group)
        return Character.objects.filter(
            eve_character__character_ownership__user__in=eligible_users,
        ).select_related("eve_character").order_by("eve_character__character_name")

    return _get_member_characters(user)


def _get_accessible_fitting_or_404(user, fitting_id: int):
    fitting = get_object_or_404(Fitting.objects.select_related("ship_type"), id=fitting_id)
    accessible_fit_ids = pilot_access_service.accessible_fitting_ids(user)
    if fitting.pk not in accessible_fit_ids and not user.has_perm("mastery.manage_fittings"):
        raise Http404("Fitting not accessible")

    fitting_map = FittingSkillsetMap.objects.select_related("skillset", "doctrine_map").filter(
        fitting_id=fitting_id
    ).first()
    doctrine = Doctrine.objects.filter(fittings__id=fitting_id).first()

    return fitting, fitting_map, doctrine


def _parse_export_mode(raw_value: str) -> str:
    valid_modes = {mode for mode, _label in pilot_progress_service.export_mode_choices()}
    if raw_value in valid_modes:
        return raw_value
    return pilot_progress_service.EXPORT_MODE_RECOMMENDED


def _parse_export_language(raw_value: str) -> str:
    return pilot_progress_service.normalize_export_language(raw_value)


def _parse_activity_days(raw_value: str, default: int = 14) -> int:
    try:
        days = int(raw_value) if raw_value is not None else default
    except (TypeError, ValueError):
        return default
    return max(1, min(days, 90))


def _parse_training_days(raw_value: str, default: int = 7) -> int:
    try:
        days = int(raw_value) if raw_value is not None else default
    except (TypeError, ValueError):
        return default
    return max(1, min(days, 90))


def _summary_groups_qs():
    return SummaryAudienceGroup.objects.prefetch_related("entries").order_by("name")


def _get_selected_summary_group(group_id_raw: str):
    groups = list(_summary_groups_qs())
    selected_group = None
    if group_id_raw:
        try:
            group_id = int(group_id_raw)
        except (TypeError, ValueError):
            group_id = None
        if group_id is not None:
            selected_group = next(
                (group for group in groups if getattr(group, "id", None) == group_id),
                None,
            )

    if selected_group is None and groups:
        selected_group = groups[0]

    return groups, selected_group


def _build_member_groups_for_summary(summary_group, activity_days: int, include_inactive: bool):
    if summary_group is None:
        return []

    eligible_users = _summary_group_users(summary_group)
    if not eligible_users.exists():
        return []

    cutoff = timezone.now() - timedelta(days=activity_days)
    groups = {}

    characters = Character.objects.filter(
        eve_character__character_ownership__user__in=eligible_users,
    ).select_related(
        "eve_character__character_ownership__user__profile__main_character",
        "online_status",
    )

    for character in characters:
        ownership = getattr(character.eve_character, "character_ownership", None)
        owner = None if ownership is None else ownership.user
        if owner is None:
            continue

        online_status = getattr(character, "online_status", None)
        last_login = None if online_status is None else online_status.last_login
        last_logout = None if online_status is None else online_status.last_logout
        last_seen: datetime | None = None
        for ts in (last_login, last_logout):
            ts_dt = ts if isinstance(ts, datetime) else None
            if ts_dt is None:
                continue
            if last_seen is None or ts_dt > last_seen:
                last_seen = ts_dt
        is_active = include_inactive or (last_seen is not None and last_seen >= cutoff)

        group = groups.setdefault(
            owner.id,
            {
                "user": owner,
                "main_character": getattr(owner.profile, "main_character", None),
                "characters": [],
                "active_count": 0,
                "total_count": 0,
                "last_seen": None,
            },
        )
        group["total_count"] += 1
        if last_seen and (group["last_seen"] is None or last_seen > group["last_seen"]):
            group["last_seen"] = last_seen

        if is_active:
            group["characters"].append(character)
            group["active_count"] += 1

    results = [obj for obj in groups.values() if obj["characters"]]
    return sorted(
        results,
        key=lambda x: (
            (x["main_character"].character_name if x["main_character"] else x["user"].username) or ""
        ).lower(),
    )


def _summary_entity_catalog() -> tuple[list[dict], list[dict]]:
    corp_map = {}
    alliance_map = {}

    for eve_char in EveCharacter.objects.all():
        corp_id = eve_char.corporation_id
        if corp_id:
            corp_obj = corp_map.setdefault(
                corp_id,
                {
                    "id": corp_id,
                    "name": eve_char.corporation_name or f"Corporation #{corp_id}",
                    "count": 0,
                },
            )
            corp_obj["count"] += 1

        alliance_id = eve_char.alliance_id
        if alliance_id:
            alliance_obj = alliance_map.setdefault(
                alliance_id,
                {
                    "id": alliance_id,
                    "name": eve_char.alliance_name or f"Alliance #{alliance_id}",
                    "count": 0,
                },
            )
            alliance_obj["count"] += 1

    corporations = sorted(corp_map.values(), key=lambda x: (x["name"] or "").lower())
    alliances = sorted(alliance_map.values(), key=lambda x: (x["name"] or "").lower())
    return corporations, alliances


def _progress_for_character(skillset, character, progress_cache: dict, progress_context: dict | None = None):
    cache_key = (skillset.id, character.id)
    if cache_key not in progress_cache:
        progress_cache[cache_key] = pilot_progress_service.build_for_character(
            character=character,
            skillset=skillset,
            include_export_lines=False,
            cache_context=progress_context,
        )
    return progress_cache[cache_key]


def _build_fitting_user_rows(
    fitting_map: FittingSkillsetMap,
    member_groups: list,
    progress_cache: dict,
    progress_context: dict | None = None,
) -> list:
    rows = []
    for group in member_groups:
        progress_rows = []
        for character in group["characters"]:
            progress = _progress_for_character(
                skillset=fitting_map.skillset,
                character=character,
                progress_cache=progress_cache,
                progress_context=progress_context,
            )
            progress_rows.append({"character": character, "progress": progress})

        if not progress_rows:
            continue

        best_row = max(
            progress_rows,
            key=lambda row: (
                row["progress"]["can_fly"],
                row["progress"]["recommended_pct"],
                row["progress"]["required_pct"],
            ),
        )
        flyable_count = sum(1 for row in progress_rows if row["progress"]["can_fly"])
        rows.append(
            {
                "user": group["user"],
                "main_character": group["main_character"],
                "best_character": best_row["character"],
                "best_progress": best_row["progress"],
                "flyable_count": flyable_count,
                "active_count": len(progress_rows),
                "total_count": group["total_count"],
                "last_seen": group["last_seen"],
                "character_rows": progress_rows,
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            row["best_progress"]["can_fly"],
            row["flyable_count"],
            row["best_progress"]["recommended_pct"],
            row["best_progress"]["required_pct"],
        ),
        reverse=True,
    )


_CHAR_STATUS_RANK = {
    "elite": 5,
    "almost_elite": 4,
    "can_fly": 3,
    "almost_fit": 2,
    "needs_training": 1,
}


def _char_status_bucket(progress: dict) -> str:
    """Return the status bucket for a character's progress (mirrors _status_meta logic)."""
    return bucket_for_progress(progress)


def _build_fitting_kpis(user_rows: list) -> dict:
    users_total = len(user_rows)
    flyable_now_users = 0
    recommended_sum = 0.0
    elite_characters = 0
    almost_elite_characters = 0
    can_fly_characters = 0
    almost_fit_characters = 0
    needs_training_characters = 0

    for row in user_rows:
        best_progress = row["best_progress"]
        if bool(best_progress.get("can_fly")):
            flyable_now_users += 1
        recommended_sum += float(best_progress.get("recommended_pct") or 0)

        for pilot in row.get("character_rows", []):
            bucket = _char_status_bucket(pilot["progress"])
            if bucket == "elite":
                elite_characters += 1
            elif bucket == "almost_elite":
                almost_elite_characters += 1
            elif bucket == "can_fly":
                can_fly_characters += 1
            elif bucket == "almost_fit":
                almost_fit_characters += 1
            else:
                needs_training_characters += 1

    recommended_avg = round((recommended_sum / users_total), 1) if users_total else 0.0

    return {
        "users_total": users_total,
        "flyable_now_users": flyable_now_users,
        "elite_characters": elite_characters,
        "almost_elite_characters": almost_elite_characters,
        "can_fly_characters": can_fly_characters,
        "almost_fit_characters": almost_fit_characters,
        "needs_training_characters": needs_training_characters,
        "recommended_avg_pct": recommended_avg,
    }


def _build_doctrine_kpis(fittings: list, users_tracked: int) -> dict:
    """Aggregate doctrine-level KPIs from configured fitting user rows.

    Character counts reflect each character's *best* status bucket across all
    configured fittings in this doctrine, so a character only appears in one bucket.
    """
    per_user_best: dict = {}
    per_char_best: dict = {}  # char_id → {"bucket": str, "rank": int}

    for fit in fittings:
        if not fit.get("configured"):
            continue
        for row in fit.get("user_rows", []):
            user_id = row["user"].id
            progress = row["best_progress"]
            existing = per_user_best.get(user_id)
            if existing is None:
                per_user_best[user_id] = progress
            elif (
                (progress.get("can_fly"), progress.get("recommended_pct", 0), progress.get("required_pct", 0))
                > (existing.get("can_fly"), existing.get("recommended_pct", 0), existing.get("required_pct", 0))
            ):
                per_user_best[user_id] = progress

            for pilot in row.get("character_rows", []):
                char_id = pilot["character"].id
                bucket = _char_status_bucket(pilot["progress"])
                rank = _CHAR_STATUS_RANK[bucket]
                if rank > per_char_best.get(char_id, {}).get("rank", 0):
                    per_char_best[char_id] = {"bucket": bucket, "rank": rank}

    flyable_now_users = sum(1 for p in per_user_best.values() if p.get("can_fly"))
    recommended_sum = sum(float(p.get("recommended_pct") or 0) for p in per_user_best.values())

    bucket_counts: dict[str, int] = {b: 0 for b in _CHAR_STATUS_RANK}
    for char_data in per_char_best.values():
        bucket_counts[char_data["bucket"]] += 1

    users_total = users_tracked
    recommended_avg = round((recommended_sum / users_total), 1) if users_total else 0.0

    return {
        "users_total": users_total,
        "flyable_now_users": flyable_now_users,
        "elite_characters": bucket_counts["elite"],
        "almost_elite_characters": bucket_counts["almost_elite"],
        "can_fly_characters": bucket_counts["can_fly"],
        "almost_fit_characters": bucket_counts["almost_fit"],
        "needs_training_characters": bucket_counts["needs_training"],
        "recommended_avg_pct": recommended_avg,
    }


def _annotate_member_detail_pilots(user_rows: list) -> list:
    annotated_rows = []
    for row in user_rows:
        buckets: dict[str, list] = {k: [] for k in _CHAR_STATUS_RANK}
        for pilot in row.get("character_rows", []):
            progress = pilot["progress"]
            required_stats = (progress.get("mode_stats") or {}).get(
                pilot_progress_service.EXPORT_MODE_REQUIRED, {},
            )
            recommended_stats = (progress.get("mode_stats") or {}).get(
                pilot_progress_service.EXPORT_MODE_RECOMMENDED, {},
            )
            pilot_enriched = {
                **pilot,
                "required_missing_sp": int(required_stats.get("total_missing_sp") or 0),
                "recommended_missing_sp": int(recommended_stats.get("total_missing_sp") or 0),
            }
            buckets[_char_status_bucket(progress)].append(pilot_enriched)

        annotated_rows.append({
            **row,
            "elite_pilots": buckets["elite"],
            "almost_elite_pilots": buckets["almost_elite"],
            "can_fly_pilots": buckets["can_fly"],
            "almost_fit_pilots": buckets["almost_fit"],
            "needs_training_pilots": buckets["needs_training"],
        })

    return annotated_rows


def _build_doctrine_summary(
    doctrine,
    fitting_maps: dict,
    member_groups: list,
    progress_cache: dict,
    progress_context: dict | None = None,
) -> dict:
    fittings = []
    users_with_any_flyable = set()
    unique_fittings = []
    seen_fit_ids = set()
    for fitting in doctrine.fittings.all():
        if fitting.id in seen_fit_ids:
            continue
        seen_fit_ids.add(fitting.id)
        unique_fittings.append(fitting)

    for fitting in unique_fittings:
        fitting_map = fitting_maps.get(fitting.id)
        if not fitting_map or not fitting_map.skillset:
            fittings.append(
                {
                    "fitting": fitting,
                    "configured": False,
                    "users_total": 0,
                    "users_with_flyable": 0,
                    "best_required_pct": 0,
                    "best_recommended_pct": 0,
                    "user_rows": [],
                    "kpis": {
                        "users_total": 0,
                        "flyable_now_users": 0,
                        "elite_characters": 0,
                        "almost_elite_characters": 0,
                        "can_fly_characters": 0,
                        "almost_fit_characters": 0,
                        "needs_training_characters": 0,
                        "recommended_avg_pct": 0.0,
                    },
                }
            )
            continue

        user_rows = _build_fitting_user_rows(
            fitting_map=cast(FittingSkillsetMap, fitting_map),
            member_groups=member_groups,
            progress_cache=progress_cache,
            progress_context=progress_context,
        )
        for row in user_rows:
            if row["flyable_count"] > 0:
                users_with_any_flyable.add(row["user"].id)

        fittings.append(
            {
                "fitting": fitting,
                "fitting_map": fitting_map,
                "configured": True,
                "users_total": len(user_rows),
                "users_with_flyable": sum(1 for row in user_rows if row["flyable_count"] > 0),
                "best_required_pct": max((row["best_progress"]["required_pct"] for row in user_rows), default=0),
                "best_recommended_pct": max((row["best_progress"]["recommended_pct"] for row in user_rows), default=0),
                "user_rows": user_rows,
                "kpis": _build_fitting_kpis(user_rows),
            }
        )

    configured_fittings = [obj for obj in fittings if obj["configured"]]
    return {
        "doctrine": doctrine,
        "fittings": fittings,
        "fittings_total": len(unique_fittings),
        "configured_fittings": len(configured_fittings),
        "users_tracked": len(member_groups),
        "users_with_any_flyable": len(users_with_any_flyable),
        "active_characters_total": sum(group["active_count"] for group in member_groups),
        "kpis": _build_doctrine_kpis(
            fittings=fittings,
            users_tracked=len(member_groups),
        ),
    }
