"""Common helpers and re-exported symbols shared across mastery views."""

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.contrib import messages
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _
from eve_sde.models import ItemType, TypeDogma
from fittings.models import Doctrine, Fitting

from mastery import app_settings
from mastery.models import DoctrineSkillSetGroupMap, FittingSkillsetMap
from .deps import (
    MASTERY_LEVEL_CHOICES,
    MASTERY_LEVEL_LABELS,
    control_service,
    doctrine_map_service,  # re-exported to fitting.py
    doctrine_skill_service,
    extractor_service,  # re-exported to fitting.py and __init__.py
    fitting_map_service,  # re-exported to fitting.py
    mastery_service,  # re-exported (used by downstream views)
    pilot_access_service,  # re-exported to pilot.py
    pilot_progress_service,  # re-exported to pilot.py
    suggestion_service,  # re-exported (used by downstream views)
)
# Re-exported helpers originally defined in summary_helpers; imported here so
# that existing views can continue to import them from .common.
from .summary_helpers import (  # noqa: E402 – must follow deps import
    _approved_fitting_maps,  # re-exported
    _annotate_member_detail_pilots,  # re-exported
    _is_approved_fitting_map,  # re-exported
    _missing_skillset_error,  # re-exported
    _build_doctrine_summary,  # re-exported
    _build_fitting_kpis,  # re-exported
    _build_fitting_user_rows,  # re-exported
    _build_member_groups_for_summary,  # re-exported
    _get_accessible_fitting_or_404,  # re-exported
    _get_member_characters,  # re-exported
    _get_pilot_detail_characters,  # re-exported
    _get_selected_summary_group,  # re-exported
    _get_summary_group_by_id,  # re-exported
    _parse_activity_days,  # re-exported
    _parse_export_language,  # re-exported
    _parse_export_mode,  # re-exported
    _parse_training_days,  # re-exported
    _prime_summary_character_skills_cache_context,  # re-exported
    _summary_entity_catalog,  # re-exported
)

APPROVAL_STATUS_LABELS = {
    FittingSkillsetMap.ApprovalStatus.IN_PROGRESS: _("In progress"),
    FittingSkillsetMap.ApprovalStatus.NOT_APPROVED: _("Not approved"),
    FittingSkillsetMap.ApprovalStatus.APPROVED: _("Approved"),
}

APPROVAL_STATUS_BADGE_CLASSES = {
    FittingSkillsetMap.ApprovalStatus.IN_PROGRESS: "bg-warning text-dark",
    FittingSkillsetMap.ApprovalStatus.NOT_APPROVED: "bg-secondary",
    FittingSkillsetMap.ApprovalStatus.APPROVED: "bg-success",
}


def _get_mastery_label(level: int) -> str:
    return MASTERY_LEVEL_LABELS.get(level, str(level))


def _get_approval_status_label(status: str | None) -> str:
    return APPROVAL_STATUS_LABELS.get(
        status,
        APPROVAL_STATUS_LABELS[FittingSkillsetMap.ApprovalStatus.NOT_APPROVED],
    )


def _get_approval_status_badge_class(status: str | None) -> str:
    return APPROVAL_STATUS_BADGE_CLASSES.get(
        status,
        APPROVAL_STATUS_BADGE_CLASSES[FittingSkillsetMap.ApprovalStatus.NOT_APPROVED],
    )


def _get_user_display(user) -> Optional[str]:
    if not user:
        return None

    get_full_name = getattr(user, "get_full_name", None)
    if callable(get_full_name):
        full_name = (get_full_name() or "").strip()
        if full_name:
            return full_name

    for attr_name in ("username", "name"):
        value = getattr(user, attr_name, None)
        if value:
            return str(value)

    return str(user)


def _build_actor_display(user) -> Optional[dict]:
    """Return actor display payload with optional main character for avatar rendering."""
    if not user:
        return None

    profile = getattr(user, "profile", None)
    main_character = None if profile is None else getattr(profile, "main_character", None)
    return {
        "user": user,
        "display_name": _get_user_display(user),
        "main_character": main_character,
    }


def _build_recommended_export_text(rows: list[dict]) -> str:
    """Build a full recommended export plan from active rows (no pilot filter)."""
    source_rows = []
    for row in rows:
        required_level, recommended_level = _resolve_row_levels(row)
        target_level = max(required_level, recommended_level)
        skill_type_id = _to_int(row.get("skill_type_id"), default=0)
        if skill_type_id <= 0 or target_level <= 0:
            continue
        source_rows.append(
            {
                "skill_type_id": skill_type_id,
                "target_level": target_level,
                "current_level": 0,
                "current_sp": 0,
            }
        )

    if not source_rows:
        return ""

    export_lines = pilot_progress_service.build_export_lines(
        {
            "missing_required": source_rows,
            "missing_recommended": source_rows,
        },
        mode=pilot_progress_service.EXPORT_MODE_RECOMMENDED,
        character=None,
        language="en",
    )
    return "\n".join(export_lines)


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
            # pylint: disable=protected-access  # intentional: internal SP formula helper
            grouped[group_name]["required_total_sp"] += pilot_progress_service._sp_for_level(rank, required_level)
        if recommended_level > 0:
            # pylint: disable=protected-access
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
    fitting_map = preview.get("fitting_map", fitting_map) if fitting_map is None else fitting_map
    effective_mastery_level = preview["effective_mastery_level"]
    all_rows = list(preview["skills"])
    active_rows = [row for row in all_rows if not row.get("is_blacklisted")]
    recommended_export_text = _build_recommended_export_text(active_rows)
    plan_kpis = _build_plan_kpis(active_rows)
    approval_status = (
                          getattr(fitting_map, "status", None)
                          if fitting_map is not None
                          else FittingSkillsetMap.ApprovalStatus.NOT_APPROVED
                      ) or FittingSkillsetMap.ApprovalStatus.NOT_APPROVED
    last_synced_at = getattr(fitting_map, "last_synced_at", None) if fitting_map else None

    return {
        "fitting": fitting,
        "doctrine_map": doctrine_map,
        "fitting_map": fitting_map,
        "doctrine_priority": int(getattr(doctrine_map, "priority", 0) or 0),
        "fitting_priority": int(getattr(fitting_map, "priority", 0) or 0) if fitting_map else 0,
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
        "last_synced_at": last_synced_at,
        "skillset_id": (
            fitting_map.skillset.pk if fitting_map and fitting_map.skillset else None
        ),
        "approval_status": approval_status,
        "approval_status_label": _get_approval_status_label(approval_status),
        "approval_status_badge_class": _get_approval_status_badge_class(approval_status),
        "approved_by_display": _get_user_display(getattr(fitting_map, "approved_by", None) if fitting_map else None),
        "approved_by_actor": _build_actor_display(getattr(fitting_map, "approved_by", None) if fitting_map else None),
        "approved_at": getattr(fitting_map, "approved_at", None) if fitting_map else None,
        "modified_by_display": _get_user_display(getattr(fitting_map, "modified_by", None) if fitting_map else None),
        "modified_by_actor": _build_actor_display(getattr(fitting_map, "modified_by", None) if fitting_map else None),
        "modified_at": getattr(fitting_map, "modified_at", None) if fitting_map else None,
        "can_approve_plan": bool(fitting_map and last_synced_at and getattr(fitting_map, "skillset", None)),
        "recommended_plan_copy_text": recommended_export_text,
        "recommended_plan_copy_line_count": (
            0 if not recommended_export_text else len(recommended_export_text.splitlines())
        ),
        **plan_kpis,
        "can_make_recommended_plan_alpha_compatible": bool(
            plan_kpis.get("required_plan_alpha_compatible")
            and not plan_kpis.get("recommended_plan_alpha_compatible")
        ),
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
        fitting_map = FittingSkillsetMap.objects.select_related(
            "skillset", "doctrine_map", "approved_by", "modified_by"
        ).filter(
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
    raw_active_group = (request.POST.get("active_group") or "").strip()
    active_group = None
    if raw_active_group:
        normalized_digits = raw_active_group.replace(" ", "").replace(",", "")
        if normalized_digits.isdigit():
            active_group = str(int(normalized_digits))
        else:
            active_group = raw_active_group
    if next_url:
        if active_group:
            parsed_url = urlsplit(next_url)
            query_items = [
                (key, value)
                for key, value in parse_qsl(parsed_url.query, keep_blank_values=True)
                if key != "active_group"
            ]
            query_items.append(("active_group", active_group))
            next_url = urlunsplit(
                (
                    parsed_url.scheme,
                    parsed_url.netloc,
                    parsed_url.path,
                    urlencode(query_items),
                    parsed_url.fragment,
                )
            )
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
    required_alpha_flags = {}
    recommended_alpha_flags = {}

    for row in skill_rows:
        skill_type_id = _to_int(row.get("skill_type_id"), default=0)
        if not skill_type_id:
            continue

        required_level, recommended_level = _resolve_row_levels(row)
        required_requires_omega = bool(row.get("required_requires_omega", False))
        recommended_requires_omega = bool(row.get("recommended_requires_omega", False))

        if required_level > 0:
            required_targets[skill_type_id] = max(required_targets.get(skill_type_id, 0), required_level)
            required_payload = required_alpha_flags.setdefault(
                skill_type_id,
                {"requires_omega": False},
            )
            required_payload["requires_omega"] = required_payload["requires_omega"] or required_requires_omega
        if recommended_level > 0:
            recommended_targets[skill_type_id] = max(recommended_targets.get(skill_type_id, 0), recommended_level)
            recommended_payload = recommended_alpha_flags.setdefault(
                skill_type_id,
                {"requires_omega": False},
            )
            recommended_payload["requires_omega"] = (
                recommended_payload["requires_omega"] or recommended_requires_omega
            )

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
            total += pilot_progress_service._sp_for_level(rank, level)  # pylint: disable=protected-access
        return int(total)

    required_total_sp = _total_sp(required_targets)
    recommended_total_sp = _total_sp(recommended_targets)

    required_seconds = int(
        (required_total_sp / app_settings.MASTERY_PLAN_ESTIMATE_SP_PER_HOUR) * 3600) if required_total_sp else 0
    recommended_seconds = int(
        (recommended_total_sp / app_settings.MASTERY_PLAN_ESTIMATE_SP_PER_HOUR) * 3600) if recommended_total_sp else 0

    required_plan_skill_count = len(required_alpha_flags)
    recommended_plan_skill_count = len(recommended_alpha_flags)
    required_plan_omega_skill_count = sum(1 for payload in required_alpha_flags.values() if payload["requires_omega"])
    recommended_plan_omega_skill_count = sum(
        1 for payload in recommended_alpha_flags.values() if payload["requires_omega"]
    )
    return {
        "required_plan_total_sp": required_total_sp,
        "required_plan_total_time": _format_duration_from_seconds(required_seconds),
        "recommended_plan_total_sp": recommended_total_sp,
        "recommended_plan_total_time": _format_duration_from_seconds(recommended_seconds),
        "required_plan_skill_count": required_plan_skill_count,
        "recommended_plan_skill_count": recommended_plan_skill_count,
        "required_plan_omega_skill_count": required_plan_omega_skill_count,
        "recommended_plan_omega_skill_count": recommended_plan_omega_skill_count,
        "required_plan_alpha_compatible": required_plan_omega_skill_count == 0,
        "recommended_plan_alpha_compatible": recommended_plan_omega_skill_count == 0,
    }


def _apply_preview_suggestions(
        fitting,
        doctrine_map,
        *,
        allowed_skill_ids=None,
        modified_by=None,
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
        doctrine_skill_service.generate_for_fitting(
            doctrine_map,
            fitting,
            modified_by=modified_by,
            status=FittingSkillsetMap.ApprovalStatus.IN_PROGRESS,
        )

    return applied_count


__all__ = [
    "_approved_fitting_maps",
    "_is_approved_fitting_map",
    "_missing_skillset_error",
    "Doctrine",
    "DoctrineSkillSetGroupMap",
    "Fitting",
    "FittingSkillsetMap",
    "ItemType",
    "MASTERY_LEVEL_CHOICES",
    "MASTERY_LEVEL_LABELS",
    "TypeDogma",
    "_annotate_member_detail_pilots",
    "_apply_preview_suggestions",
    "_bad_request_response",
    "_build_doctrine_summary",
    "_build_fitting_kpis",
    "_build_fitting_preview_context",
    "_build_fitting_skills_ajax_response",
    "_build_fitting_user_rows",
    "_build_member_groups_for_summary",
    "_build_plan_kpis",
    "_finalize_fitting_skills_action",
    "_get_approval_status_badge_class",
    "_get_approval_status_label",
    "_get_accessible_fitting_or_404",
    "_get_doctrine_and_map_for_fitting",
    "_get_mastery_label",
    "_get_member_characters",
    "_get_pilot_detail_characters",
    "_get_selected_summary_group",
    "_get_skill_name_options",
    "_get_summary_group_by_id",
    "_get_user_display",
    "_group_preview_skills",
    "_is_ajax_request",
    "_parse_activity_days",
    "_parse_export_language",
    "_parse_export_mode",
    "_parse_mastery_level",
    "_parse_posted_int",
    "_parse_training_days",
    "_prime_summary_character_skills_cache_context",
    "_resolve_row_levels",
    "_summary_entity_catalog",
    "control_service",
    "doctrine_map_service",
    "doctrine_skill_service",
    "extractor_service",
    "fitting_map_service",
    "mastery_service",
    "pilot_access_service",
    "pilot_progress_service",
    "suggestion_service",
]
