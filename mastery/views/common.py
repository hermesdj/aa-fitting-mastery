from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from django.contrib import messages
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from eve_sde.models import ItemType, TypeDogma
from fittings.models import Doctrine, Fitting

from mastery import app_settings
from mastery.models import DoctrineSkillSetGroupMap, FittingSkillsetMap
from .deps import (
    MASTERY_LEVEL_CHOICES,
    MASTERY_LEVEL_LABELS,
    control_service,
    doctrine_map_service,
    doctrine_skill_service,
    extractor_service,
    fitting_map_service,
    mastery_service,
    pilot_access_service,
    pilot_progress_service,
    suggestion_service,
)


def _get_mastery_label(level: int) -> str:
    return MASTERY_LEVEL_LABELS.get(level, str(level))


def _parse_mastery_level(raw_value: str):
    if raw_value in (None, ""):
        return None

    level = int(raw_value)

    if level not in MASTERY_LEVEL_LABELS:
        raise ValueError(f"Invalid mastery level: {level}")

    return level


def _parse_posted_int(raw_value: str, field_name: str) -> int:
    if raw_value in (None, ""):
        raise ValueError(f"{field_name} is required")

    normalized = str(raw_value).strip()
    normalized = normalized.replace("\u202f", "").replace("\xa0", "").replace(" ", "")

    if "," in normalized and "." in normalized:
        normalized = normalized.replace(",", "")
    elif "," in normalized:
        normalized = normalized.replace(",", ".")

    try:
        number = Decimal(normalized)
    except InvalidOperation as ex:
        raise ValueError(f"Invalid integer for {field_name}: {raw_value}") from ex

    if number != number.to_integral_value():
        raise ValueError(f"{field_name} must be an integer: {raw_value}")

    return int(number)


def _to_int(value, default: int = 0) -> int:
    """Best-effort int parser for mixed payloads coming from preview/services."""
    if value in (None, ""):
        return default

    if isinstance(value, bool):
        return int(value)

    if isinstance(value, int):
        return value

    if isinstance(value, Decimal):
        return int(value)

    normalized = str(value).strip()
    if not normalized:
        return default

    normalized = normalized.replace("\u202f", "").replace("\xa0", "").replace(" ", "")
    if "," in normalized and "." in normalized:
        normalized = normalized.replace(",", "")
    elif "," in normalized:
        normalized = normalized.replace(",", ".")

    try:
        return int(Decimal(normalized))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _resolve_row_levels(row: dict) -> tuple[int, int]:
    """Resolve required/recommended levels from preview rows with backward-compatible key fallbacks."""
    required_level = _to_int(
        row.get("required_level", row.get("required", row.get("required_target_level"))),
        default=0,
    )

    recommended_value = row.get("recommended_level")
    if recommended_value in (None, ""):
        recommended_value = row.get("recommended")
    if recommended_value in (None, ""):
        recommended_value = row.get("recommended_level_override")
    if recommended_value in (None, ""):
        recommended_value = row.get("target_level")

    recommended_level = _to_int(recommended_value, default=0)
    recommended_level = max(recommended_level, required_level)

    return required_level, recommended_level


def _get_doctrine_and_map_for_fitting(fitting_id: int):
    fitting = get_object_or_404(Fitting.objects.select_related("ship_type"), id=fitting_id)
    fitting_map = FittingSkillsetMap.objects.select_related("doctrine_map").filter(fitting_id=fitting_id).first()

    doctrine = None
    doctrine_map = None

    if fitting_map:
        doctrine_map = fitting_map.doctrine_map
        doctrine = doctrine_map.doctrine
    else:
        doctrine = Doctrine.objects.filter(fittings__id=fitting_id).first()

    return fitting, doctrine, doctrine_map, fitting_map


def _group_preview_skills(skill_rows: List[dict]) -> dict:
    normalized_skill_ids = [
        _to_int(row.get("skill_type_id"), default=0)
        for row in skill_rows
    ]
    skill_type_ids = [skill_type_id for skill_type_id in normalized_skill_ids if skill_type_id > 0]
    item_types = {
        item_type.id: item_type
        for item_type in ItemType.objects.select_related("group").filter(
            id__in=skill_type_ids
        )
    }

    rank_by_skill = {skill_id: 1 for skill_id in skill_type_ids}
    if skill_type_ids:
        for row in TypeDogma.objects.filter(
                item_type_id__in=skill_type_ids,
                dogma_attribute_id=pilot_progress_service.DOGMA_SKILL_TIME_CONSTANT,
        ).values("item_type_id", "value"):
            rank_by_skill[int(row["item_type_id"])] = max(1, int(row["value"]))

    grouped = defaultdict(
        lambda: {
            "skills": [],
            "suggestion_count": 0,
            "blacklisted_count": 0,
            "active_skill_count": 0,
            "required_total_sp": 0,
            "recommended_total_sp": 0,
        }
    )

    for row in sorted(skill_rows, key=lambda x: (x.get("group_name", "Other"), x.get("skill_name", ""))):
        skill_type_id = _to_int(row.get("skill_type_id"), default=0)
        if skill_type_id <= 0:
            continue

        item_type = item_types.get(skill_type_id)
        skill_name = item_type.name if item_type else f"Skill {skill_type_id}"
        skill_description = "" if not item_type else (getattr(item_type, "description", "") or "")
        group_name = item_type.group.name if item_type and item_type.group else "Other"
        group_id = item_type.group.id if item_type and item_type.group else None

        row_payload = {
            **row,
            "skill_type_id": skill_type_id,
            "skill_name": skill_name,
            "skill_description": skill_description,
            "group_name": group_name,
            "group_id": group_id,
        }
        grouped[group_name]["skills"].append(row_payload)
        if row_payload.get("is_suggested"):
            grouped[group_name]["suggestion_count"] += 1
        if row_payload.get("is_blacklisted"):
            grouped[group_name]["blacklisted_count"] += 1

        if row_payload.get("is_blacklisted"):
            continue

        grouped[group_name]["active_skill_count"] += 1

        rank = rank_by_skill.get(skill_type_id, 1)
        required_level, recommended_level = _resolve_row_levels(row_payload)

        if required_level > 0:
            grouped[group_name]["required_total_sp"] += pilot_progress_service._sp_for_level(rank, required_level)
        if recommended_level > 0:
            grouped[group_name]["recommended_total_sp"] += pilot_progress_service._sp_for_level(rank, recommended_level)

    normalized_groups = {}
    for group_name, payload in grouped.items():
        total_skill_count = len(payload["skills"])
        blacklisted_count = payload["blacklisted_count"]
        active_skill_count = payload["active_skill_count"]
        first_skill = payload["skills"][0] if payload["skills"] else {}
        normalized_groups[group_name] = {
            **payload,
            "group_id": first_skill.get("group_id"),
            "total_skill_count": total_skill_count,
            "has_blacklisted_skills": blacklisted_count > 0,
            "has_active_skills": active_skill_count > 0,
            "all_blacklisted": total_skill_count > 0 and blacklisted_count == total_skill_count,
        }

    return dict(sorted(normalized_groups.items(), key=lambda x: (x[0] or "").lower()))


def _get_skill_name_options() -> List[str]:
    return list(
        ItemType.objects.filter(group__category__name__iexact="Skill")
        .order_by("name")
        .values_list("name", flat=True)
    )


def _build_fitting_preview_context(
        fitting: Fitting,
        doctrine_map: DoctrineSkillSetGroupMap,
        fitting_map: FittingSkillsetMap = None,
        mastery_level: int = None,
) -> dict:
    preview = doctrine_skill_service.preview_fitting(
        doctrine_map=doctrine_map,
        fitting=fitting,
        mastery_level=mastery_level,
    )
    effective_mastery_level = preview["effective_mastery_level"]
    all_rows = list(preview["skills"])
    active_rows = [row for row in all_rows if not row.get("is_blacklisted")]

    return {
        "fitting": fitting,
        "doctrine_map": doctrine_map,
        "fitting_map": fitting_map,
        "grouped_skills": _group_preview_skills(all_rows),
        "effective_mastery_level": effective_mastery_level,
        "effective_mastery_label": _get_mastery_label(effective_mastery_level),
        "doctrine_default_mastery_level": doctrine_map.default_mastery_level,
        "doctrine_default_mastery_label": _get_mastery_label(doctrine_map.default_mastery_level),
        "fitting_mastery_override": None if not fitting_map else fitting_map.mastery_level,
        "mastery_choices": MASTERY_LEVEL_CHOICES,
        "recommended_choices": list(range(6)),
        "suggestion_count": sum(1 for row in all_rows if row.get("is_suggested")),
        "skill_name_options": _get_skill_name_options(),
        "skillset_skill_count": (
            fitting_map.skillset.skills.count() if fitting_map and fitting_map.skillset else None
        ),
        "last_synced_at": (
            fitting_map.last_synced_at if fitting_map else None
        ),
        "skillset_id": (
            fitting_map.skillset.pk if fitting_map and fitting_map.skillset else None
        ),
        **_build_plan_kpis(active_rows),
        "plan_estimate_sp_per_hour": app_settings.MASTERY_PLAN_ESTIMATE_SP_PER_HOUR,
    }


def _is_ajax_request(request) -> bool:
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _bad_request_response(request, message: str):
    if _is_ajax_request(request):
        return JsonResponse({"status": "error", "message": message}, status=400)
    return HttpResponseBadRequest(message)


def _add_feedback_message(request, message: Optional[str], level: str = "success"):
    if not message:
        return

    if level == "info":
        messages.info(request, message)
    elif level == "warning":
        messages.warning(request, message)
    elif level == "error":
        messages.error(request, message)
    else:
        messages.success(request, message)


def _render_ajax_messages_html(request, message: Optional[str] = None, level: str = "success") -> str:
    if not message:
        return ""

    bootstrap_level = "danger" if level == "error" else level
    return render_to_string(
        "mastery/partials/ajax_messages.html",
        {
            "messages": [
                {
                    "level": bootstrap_level,
                    "text": message,
                }
            ]
        },
        request=request,
    )


def _render_fitting_skills_editor_html(
        request,
        *,
        fitting: Fitting,
        doctrine,
        doctrine_map: DoctrineSkillSetGroupMap,
        fitting_map: FittingSkillsetMap = None,
) -> str:
    if fitting_map is None:
        fitting_map = FittingSkillsetMap.objects.select_related("skillset", "doctrine_map").filter(
            fitting_id=fitting.id
        ).first()

    context = _build_fitting_preview_context(
        fitting=fitting,
        doctrine_map=doctrine_map,
        fitting_map=fitting_map,
    )
    context["doctrine"] = doctrine

    return render_to_string(
        "mastery/partials/fitting_skills_editor.html",
        context,
        request=request,
    )


def _build_fitting_skills_ajax_response(
        request,
        *,
        fitting: Fitting,
        doctrine,
        doctrine_map: DoctrineSkillSetGroupMap,
        fitting_map: FittingSkillsetMap = None,
        message: Optional[str] = None,
        message_level: str = "success",
):
    return JsonResponse(
        {
            "status": "ok",
            "html": _render_fitting_skills_editor_html(
                request,
                fitting=fitting,
                doctrine=doctrine,
                doctrine_map=doctrine_map,
                fitting_map=fitting_map,
            ),
            "messages_html": _render_ajax_messages_html(
                request,
                message=message,
                level=message_level,
            ),
            "message": message,
            "message_level": message_level,
        }
    )


def _finalize_fitting_skills_action(
        request,
        *,
        fitting: Fitting,
        doctrine,
        doctrine_map: DoctrineSkillSetGroupMap,
        message: Optional[str] = None,
        message_level: str = "success",
):
    if _is_ajax_request(request):
        return _build_fitting_skills_ajax_response(
            request,
            fitting=fitting,
            doctrine=doctrine,
            doctrine_map=doctrine_map,
            message=message,
            message_level=message_level,
        )

    _add_feedback_message(request, message=message, level=message_level)

    next_url = request.POST.get("next")
    if next_url:
        return redirect(next_url)

    return redirect("mastery:fitting_skills", fitting_id=fitting.id)


def _format_duration_from_seconds(total_seconds: int) -> str:
    total_seconds = max(0, int(total_seconds))
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _seconds = divmod(rem, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)


def _build_plan_kpis(skill_rows: list[dict]) -> dict:
    required_targets = {}
    recommended_targets = {}

    for row in skill_rows:
        skill_type_id = _to_int(row.get("skill_type_id"), default=0)
        if not skill_type_id:
            continue

        required_level, recommended_level = _resolve_row_levels(row)

        if required_level > 0:
            required_targets[skill_type_id] = max(required_targets.get(skill_type_id, 0), required_level)
        if recommended_level > 0:
            recommended_targets[skill_type_id] = max(recommended_targets.get(skill_type_id, 0), recommended_level)

    all_skill_ids = set(required_targets.keys()) | set(recommended_targets.keys())
    rank_by_skill = {skill_id: 1 for skill_id in all_skill_ids}
    if all_skill_ids:
        for row in TypeDogma.objects.filter(
                item_type_id__in=list(all_skill_ids),
                dogma_attribute_id=pilot_progress_service.DOGMA_SKILL_TIME_CONSTANT,
        ).values("item_type_id", "value"):
            rank_by_skill[int(row["item_type_id"])] = max(1, int(row["value"]))

    def _total_sp(targets: dict[int, int]) -> int:
        total = 0
        for skill_type_id, level in targets.items():
            rank = rank_by_skill.get(skill_type_id, 1)
            total += pilot_progress_service._sp_for_level(rank, level)
        return int(total)

    required_total_sp = _total_sp(required_targets)
    recommended_total_sp = _total_sp(recommended_targets)

    required_seconds = int(
        (required_total_sp / app_settings.MASTERY_PLAN_ESTIMATE_SP_PER_HOUR) * 3600) if required_total_sp else 0
    recommended_seconds = int(
        (recommended_total_sp / app_settings.MASTERY_PLAN_ESTIMATE_SP_PER_HOUR) * 3600) if recommended_total_sp else 0

    return {
        "required_plan_total_sp": required_total_sp,
        "required_plan_total_time": _format_duration_from_seconds(required_seconds),
        "recommended_plan_total_sp": recommended_total_sp,
        "recommended_plan_total_time": _format_duration_from_seconds(recommended_seconds),
    }


def _apply_preview_suggestions(
        fitting,
        doctrine_map,
        *,
        allowed_skill_ids=None,
) -> int:
    """Apply pending suggestion actions and return how many were applied."""
    preview = doctrine_skill_service.preview_fitting(doctrine_map=doctrine_map, fitting=fitting)
    applied_count = 0

    for row in preview["skill_rows"]:
        if not row.get("is_suggested"):
            continue

        skill_type_id = int(row["skill_type_id"])
        if allowed_skill_ids is not None and skill_type_id not in allowed_skill_ids:
            continue

        action = row.get("suggestion_action")
        if action == "remove":
            control_service.set_blacklist(fitting_id=fitting.id, skill_type_id=skill_type_id, value=True)
            applied_count += 1
        elif action == "add":
            control_service.set_blacklist(fitting_id=fitting.id, skill_type_id=skill_type_id, value=False)
            applied_count += 1

    if applied_count:
        doctrine_skill_service.generate_for_fitting(doctrine_map, fitting)

    return applied_count


from .summary_helpers import (
    _annotate_member_detail_pilots,
    _build_doctrine_summary,
    _build_fitting_kpis,
    _build_fitting_user_rows,
    _build_member_groups_for_summary,
    _get_accessible_fitting_or_404,
    _get_member_characters,
    _get_pilot_detail_characters,
    _get_selected_summary_group,
    _get_summary_group_by_id,
    _parse_activity_days,
    _parse_export_language,
    _parse_export_mode,
    _parse_training_days,
    _summary_entity_catalog,
)

