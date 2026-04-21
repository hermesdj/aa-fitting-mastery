"""Helpers for pilot and summary views."""

from datetime import datetime, timedelta
from typing import cast

from allianceauth.eveonline.models import EveCharacter
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from fittings.models import Doctrine, Fitting
from memberaudit.models import Character

from mastery.models import DoctrineSkillSetGroupMap, FittingSkillsetMap, SummaryAudienceEntity, SummaryAudienceGroup
from mastery.services.pilots.status_buckets import (
    BUCKET_ALMOST_ELITE,
    BUCKET_ALMOST_FIT,
    BUCKET_CAN_FLY,
    BUCKET_ELITE,
    BUCKET_NEEDS_TRAINING,
    BUCKET_RANK,
    bucket_for_progress,
)

from .deps import pilot_access_service, pilot_progress_service

User = get_user_model()


def _is_approved_fitting_map(fitting_map) -> bool:
    """Return True when a fitting map exists and is approved."""
    return bool(
        fitting_map
        and getattr(
            fitting_map,
            "status",
            FittingSkillsetMap.ApprovalStatus.APPROVED,
        )
        == FittingSkillsetMap.ApprovalStatus.APPROVED
    )


def _approved_fitting_maps() -> dict:
    """Return fitting-id keyed maps restricted to approved skill plans."""
    return {
        obj.fitting_id: obj
        for obj in FittingSkillsetMap.objects.select_related("skillset", "doctrine_map").all()
        if _is_approved_fitting_map(obj)
    }


def _missing_skillset_error(fitting_map) -> str | None:
    """Return a user-facing error when fitting map/skillset is missing or not approved."""
    if not fitting_map or not getattr(fitting_map, "skillset", None):
        return str(_("No skillset configured for this fitting yet"))
    if not _is_approved_fitting_map(fitting_map):
        return str(_("No approved skillset configured for this fitting yet"))
    return None


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


def _character_last_seen(character) -> datetime | None:
    """Return the latest known activity timestamp for a character."""
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
    return last_seen


def _is_character_active(character, cutoff: datetime | None, include_inactive: bool) -> bool:
    """Return whether a character is in scope for the requested activity window."""
    if include_inactive or cutoff is None:
        return True
    last_seen = _character_last_seen(character)
    return last_seen is not None and last_seen >= cutoff


def _get_pilot_detail_characters(
    user,
    summary_group=None,
    activity_days: int | None = None,
    include_inactive: bool = False,
):
    # Elevated cross-account access is only allowed within an explicit summary group scope.
    if user.has_perm("mastery.doctrine_summary") and summary_group is not None:
        eligible_users = _summary_group_users(summary_group)
        characters = Character.objects.filter(
            eve_character__character_ownership__user__in=eligible_users,
        ).select_related("eve_character", "online_status").order_by("eve_character__character_name")
        cutoff = None if activity_days is None else timezone.now() - timedelta(days=activity_days)
        return [
            character
            for character in characters
            if _is_character_active(character, cutoff=cutoff, include_inactive=include_inactive)
        ]

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

        last_seen = _character_last_seen(character)
        is_active = _is_character_active(character, cutoff=cutoff, include_inactive=include_inactive)

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


def _char_status_bucket(progress: dict) -> str:
    """Return the status bucket for a character's progress (mirrors _status_meta logic)."""
    return bucket_for_progress(progress)


def _build_fitting_kpis(user_rows: list) -> dict:
    users_total = len(user_rows)
    flyable_now_users = 0
    flyable_now_characters = 0
    recommended_ready = 0
    recommended_sum = 0.0
    elite_characters = 0
    almost_elite_characters = 0
    can_fly_characters = 0
    almost_fit_characters = 0
    needs_training_characters = 0

    for row in user_rows:
        best_progress = row["best_progress"]
        can_fly = bool(best_progress.get("can_fly"))

        flyable_now_characters += sum(
            1 for pilot in row.get("character_rows", []) if pilot["progress"].get("can_fly")
        )

        if can_fly:
            flyable_now_users += 1
        # Keep reading required stats for other KPI compatibility.

        recommended_pct = float(best_progress.get("recommended_pct") or 0)
        if recommended_pct >= 100:
            recommended_ready += 1
        recommended_sum += float(best_progress.get("recommended_pct") or 0)

        for pilot in row.get("character_rows", []):
            bucket = _char_status_bucket(pilot["progress"])
            if bucket == BUCKET_ELITE:
                elite_characters += 1
            elif bucket == BUCKET_ALMOST_ELITE:
                almost_elite_characters += 1
            elif bucket == BUCKET_CAN_FLY:
                can_fly_characters += 1
            elif bucket == BUCKET_ALMOST_FIT:
                almost_fit_characters += 1
            else:
                needs_training_characters += 1

    recommended_avg = round((recommended_sum / users_total), 1) if users_total else 0.0

    return {
        "users_total": users_total,
        "flyable_now_users": flyable_now_users,
        "flyable_now_characters": flyable_now_characters,
        "recommended_ready": recommended_ready,
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
                rank = BUCKET_RANK[bucket]
                if rank > per_char_best.get(char_id, {}).get("rank", 0):
                    per_char_best[char_id] = {"bucket": bucket, "rank": rank}

    flyable_now_users = 0
    recommended_ready = 0
    recommended_sum = 0.0

    bucket_counts: dict[str, int] = {b: 0 for b in BUCKET_RANK}
    for char_data in per_char_best.values():
        bucket_counts[char_data["bucket"]] += 1

    for progress in per_user_best.values():
        can_fly = bool(progress.get("can_fly"))
        recommended_pct = float(progress.get("recommended_pct") or 0)

        if can_fly:
            flyable_now_users += 1
        # Required-time data is intentionally not exposed as KPI anymore.

        if recommended_pct >= 100:
            recommended_ready += 1
        recommended_sum += recommended_pct

    users_total = users_tracked
    recommended_avg = round((recommended_sum / users_total), 1) if users_total else 0.0

    return {
        "users_total": users_total,
        "flyable_now_users": flyable_now_users,
        "flyable_now_characters": sum(bucket_counts.values()),
        "recommended_ready": recommended_ready,
        "elite_characters": bucket_counts[BUCKET_ELITE],
        "almost_elite_characters": bucket_counts[BUCKET_ALMOST_ELITE],
        "can_fly_characters": bucket_counts[BUCKET_CAN_FLY],
        "almost_fit_characters": bucket_counts[BUCKET_ALMOST_FIT],
        "needs_training_characters": bucket_counts[BUCKET_NEEDS_TRAINING],
        "recommended_avg_pct": recommended_avg,
    }


def _annotate_member_detail_pilots(user_rows: list, training_days: int = 7) -> list:
    threshold = timedelta(days=training_days)
    annotated_rows = []
    for row in user_rows:
        req_ready_not_recommended = []
        near_required = []
        buckets: dict[str, list] = {k: [] for k in BUCKET_RANK}
        for pilot in row.get("character_rows", []):
            progress = pilot["progress"]
            required_stats = (progress.get("mode_stats") or {}).get(
                pilot_progress_service.EXPORT_MODE_REQUIRED, {},
            )
            recommended_stats = (progress.get("mode_stats") or {}).get(
                pilot_progress_service.EXPORT_MODE_RECOMMENDED, {},
            )
            required_time = required_stats.get("total_missing_time")
            required_time_td = required_time if isinstance(required_time, timedelta) else None
            is_trainable_soon = bool(
                (not progress.get("can_fly"))
                and required_time_td is not None
                and required_time_td <= threshold
            )
            pilot_enriched = {
                **pilot,
                "required_missing_sp": int(required_stats.get("total_missing_sp") or 0),
                "recommended_missing_sp": int(recommended_stats.get("total_missing_sp") or 0),
                "is_trainable_soon": is_trainable_soon,
            }

            if progress.get("can_fly") and float(progress.get("recommended_pct") or 0) < 100:
                req_ready_not_recommended.append(pilot_enriched)
            elif ((not progress.get("can_fly")) and float(progress.get("required_pct") or 0) > 90) or is_trainable_soon:
                near_required.append(pilot_enriched)

            buckets[_char_status_bucket(progress)].append(pilot_enriched)

        should_keep_row = bool(row.get("flyable_count")) or bool(req_ready_not_recommended) or bool(near_required)
        if not should_keep_row:
            continue

        annotated_rows.append(
            {
                **row,
                "elite_pilots": buckets[BUCKET_ELITE],
                "almost_elite_pilots": buckets[BUCKET_ALMOST_ELITE],
                "can_fly_pilots": buckets[BUCKET_CAN_FLY],
                "almost_fit_pilots": buckets[BUCKET_ALMOST_FIT],
                "needs_training_pilots": buckets[BUCKET_NEEDS_TRAINING],
                "req_ready_not_recommended": req_ready_not_recommended,
                "near_required": near_required,
            }
        )

    return annotated_rows


def _build_doctrine_summary(
    doctrine,
    fitting_maps: dict,
    member_groups: list,
    progress_cache: dict,
    progress_context: dict | None = None,
    doctrine_priority: int | None = None,
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

    if doctrine_priority is None:
        doctrine_priority = int(
            DoctrineSkillSetGroupMap.objects.filter(doctrine=doctrine)
            .values_list("priority", flat=True)
            .first()
            or 0
        )

    for fitting in unique_fittings:
        fitting_map = fitting_maps.get(fitting.id)
        if (
            not fitting_map
            or not fitting_map.skillset
            or getattr(fitting_map, "status", None) != FittingSkillsetMap.ApprovalStatus.APPROVED
        ):
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
                "priority": int(getattr(fitting_map, "priority", 0) or 0),
                "configured": True,
                "users_total": len(user_rows),
                "users_with_flyable": sum(1 for row in user_rows if row["flyable_count"] > 0),
                "best_required_pct": max((row["best_progress"]["required_pct"] for row in user_rows), default=0),
                "best_recommended_pct": max((row["best_progress"]["recommended_pct"] for row in user_rows), default=0),
                "user_rows": user_rows,
                "kpis": _build_fitting_kpis(user_rows),
            }
        )

    fittings.sort(
        key=lambda item: (
            -int(item.get("priority", 0) or 0),
            (getattr(item["fitting"], "name", None) or "").lower(),
        )
    )
    configured_fittings = [obj for obj in fittings if obj["configured"]]
    return {
        "doctrine": doctrine,
        "priority": doctrine_priority,
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
