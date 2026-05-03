"""Pilot-facing views: doctrine/fitting progress for individual users."""

from urllib.parse import urlencode

from allianceauth.authentication.decorators import permissions_required
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _, gettext_lazy

from mastery.services.pilots.status_buckets import (
    BUCKET_ALMOST_ELITE,
    BUCKET_ALMOST_FIT,
    BUCKET_CAN_FLY,
    BUCKET_ELITE,
    BUCKET_NEEDS_TRAINING,
    bucket_choice_list,
    bucket_for_progress,
    matches_bucket_filter,
    thresholds,
)

from .common import (
    _approved_fitting_maps,
    _get_accessible_fitting_or_404,
    _get_member_characters,
    _get_pilot_detail_characters,
    _get_summary_group_by_id,
    _missing_skillset_error,
    _parse_activity_days,
    _parse_export_language,
    _parse_export_mode,
    pilot_access_service,
    pilot_progress_service,
)


CHARACTER_FILTER_ALL = "all"
CHARACTER_FILTER_CAN_FLY = "can_fly_now"
CHARACTER_FILTER_ELITE = "elite"
CHARACTER_FILTER_ALMOST_REQUIRED = "almost_required"
CHARACTER_FILTER_ALMOST_ELITE = "almost_elite"
CHARACTER_FILTER_NEEDS_TRAINING = "needs_training"
CHARACTER_FILTER_CHOICES = [
    (CHARACTER_FILTER_ALL, gettext_lazy("All characters")),
    (CHARACTER_FILTER_CAN_FLY, gettext_lazy("Can fly now")),
    (CHARACTER_FILTER_ELITE, gettext_lazy("Elite (recommended 100%)")),
    (CHARACTER_FILTER_ALMOST_REQUIRED, gettext_lazy("Almost fit")),
    (CHARACTER_FILTER_ALMOST_ELITE, gettext_lazy("Almost elite")),
    (CHARACTER_FILTER_NEEDS_TRAINING, gettext_lazy("Needs training")),
]

INDEX_STATUS_FILTER_CHOICES = bucket_choice_list(include_all=True, all_label="All")


def _parse_index_status_filter(raw_value: str) -> str:
    alias_map = {
        "flyable": "can_fly",
        "training": "needs_training",
    }
    normalized = alias_map.get(raw_value, raw_value)
    valid_values = {value for value, _label in INDEX_STATUS_FILTER_CHOICES}
    if normalized in valid_values:
        return normalized
    return "all"


def _parse_character_filter(raw_value: str) -> str:
    valid = {value for value, _label in CHARACTER_FILTER_CHOICES}
    if raw_value in valid:
        return raw_value
    return CHARACTER_FILTER_CAN_FLY


def _matches_character_filter(progress: dict, character_filter: str) -> bool:
    return matches_bucket_filter(progress, character_filter)


def _build_character_filter_choices_with_counts(character_rows):
    """Build non-empty character filter choices with matching counts in labels."""
    filter_counts = {
        value: sum(1 for row in character_rows if _matches_character_filter(row["progress"], value))
        for value, _label in CHARACTER_FILTER_CHOICES
    }
    return [
        (value, f"{label} ({filter_counts[value]})")
        for value, label in CHARACTER_FILTER_CHOICES
        if filter_counts[value] > 0
    ]


def _progress_missing_sp_payload(progress: dict) -> dict[str, int]:
    """Return required/recommended missing SP summary extracted from a progress payload."""
    mode_stats = progress.get("mode_stats") or {}
    return {
        "required_missing_sp": int(
            (mode_stats.get(pilot_progress_service.EXPORT_MODE_REQUIRED) or {}).get("total_missing_sp") or 0
        ),
        "recommended_missing_sp": int(
            (mode_stats.get(pilot_progress_service.EXPORT_MODE_RECOMMENDED) or {}).get("total_missing_sp") or 0
        ),
    }


def _pilot_detail_action_params(
    character_id: int,
    character_filter: str,
    export_mode: str,
    export_language: str,
    summary_group=None,
    activity_days: int | None = None,
    include_inactive: bool = False,
) -> dict:
    params = {
        "character_id": character_id,
        "character_filter": character_filter,
        "export_mode": export_mode,
        "export_language": export_language,
    }
    if summary_group is not None:
        params["group_id"] = summary_group.id
        params["activity_days"] = activity_days
        if include_inactive:
            params["include_inactive"] = 1
    return params


def _build_pilot_detail_character_rows(
    fitting_id: int,
    skillset,
    member_characters,
    export_mode: str,
    export_language: str,
    selected_character_filter: str,
    summary_group=None,
    activity_days: int | None = None,
    include_inactive: bool = False,
):
    character_rows = []
    progress_context = {}
    for character in member_characters:
        progress = pilot_progress_service.build_for_character(
            character=character,
            skillset=skillset,
            include_export_lines=False,
            cache_context=progress_context,
        )
        action_params = _pilot_detail_action_params(
            character.id,
            selected_character_filter,
            export_mode,
            export_language,
            summary_group=summary_group,
            activity_days=activity_days,
            include_inactive=include_inactive,
        )
        action_url = (
            f"{reverse('mastery:pilot_fitting_detail', args=[fitting_id])}?"
            f"{urlencode(action_params)}"
        )
        character_rows.append(
            {
                "character": character,
                "progress": progress,
                "status_bucket": bucket_for_progress(progress),
                "action_url": action_url,
                "popover_id": f"pilotdetail-popover-{character.id}",
            }
        )
    return character_rows


def _get_doctrine_priority_map(priority_map: dict[int, int] | None = None) -> dict[int, int]:
    """Build a doctrine-id -> priority lookup for pilot overview pages."""
    if priority_map is not None:
        return priority_map

    from mastery.models import DoctrineSkillSetGroupMap

    return {
        row["doctrine_id"]: row["priority"]
        for row in DoctrineSkillSetGroupMap.objects.values("doctrine_id", "priority")
    }


@login_required
@permissions_required('mastery.basic_access')
def index(request):
    """Render pilot overview cards across accessible doctrines and fittings."""
    doctrines = pilot_access_service.accessible_doctrines(request.user)
    member_characters = list(_get_member_characters(request.user))
    doctrine_priority_map = None
    selected_character_id = request.GET.get("character_id")
    selected_status = _parse_index_status_filter((request.GET.get("status") or "all").strip().lower())
    search_query = (request.GET.get("q") or "").strip().lower()

    try:
        selected_character_id = int(selected_character_id) if selected_character_id else None
    except (TypeError, ValueError):
        selected_character_id = None

    selected_character = None
    if selected_character_id:
        for character in member_characters:
            if character.id == selected_character_id:
                selected_character = character
                break

    fitting_maps = _approved_fitting_maps()
    progress_context = {}

    doctrine_cards = []
    configured_fittings_count = 0
    flyable_fittings_count = 0
    for doctrine in doctrines:
        fitting_cards = []
        seen_fitting_ids = set()
        for fitting in doctrine.fittings.all():
            if fitting.id in seen_fitting_ids:
                continue
            seen_fitting_ids.add(fitting.id)

            fitting_map = fitting_maps.get(fitting.id)
            if not fitting_map:
                continue

            recommended_plan_clone_profile = pilot_progress_service.summarize_plan_clone_requirements(
                fitting_map.skillset,
                cache_context=progress_context,
            )
            if not isinstance(recommended_plan_clone_profile, dict):
                recommended_plan_clone_profile = {}

            character_rows = []
            for character in member_characters:
                progress = pilot_progress_service.build_for_character(
                    character=character,
                    skillset=fitting_map.skillset,
                    include_export_lines=False,
                    cache_context=progress_context,
                )
                action_params = {
                    "character_id": character.id,
                    "character_filter": CHARACTER_FILTER_ALL,
                }
                character_rows.append(
                    {
                        "character": character,
                        "progress": progress,
                        "status_bucket": bucket_for_progress(progress),
                        **_progress_missing_sp_payload(progress),
                        "action_url": (
                            f"{reverse('mastery:pilot_fitting_detail', args=[fitting.id])}?"
                            f"{urlencode(action_params)}"
                        ),
                        "popover_id": f"pilotindex-popover-{fitting.id}-{character.id}",
                        "is_selected": bool(selected_character_id and character.id == selected_character_id),
                    }
                )

            selected_progress = None
            if selected_character_id:
                for row in character_rows:
                    if row["character"].id == selected_character_id:
                        selected_progress = row["progress"]
                        break

            progress_for_filter = selected_progress
            if progress_for_filter is None and character_rows:
                progress_for_filter = max(
                    character_rows,
                    key=lambda row: (
                        row["progress"]["can_fly"],
                        row["progress"]["required_pct"],
                        row["progress"]["recommended_pct"],
                    ),
                )["progress"]

            if search_query and (
                search_query not in doctrine.name.lower()
                and search_query not in fitting.name.lower()
                and search_query not in fitting.ship_type.name.lower()
            ):
                continue

            if selected_status != "all":
                if not progress_for_filter:
                    continue
                if bucket_for_progress(progress_for_filter) != selected_status:
                    continue

            configured_fittings_count += 1
            if progress_for_filter and progress_for_filter["can_fly"]:
                flyable_fittings_count += 1

            bucket_map = {
                BUCKET_ELITE: [],
                BUCKET_ALMOST_ELITE: [],
                BUCKET_CAN_FLY: [],
                BUCKET_ALMOST_FIT: [],
                BUCKET_NEEDS_TRAINING: [],
            }
            for row in character_rows:
                bucket_map[row["status_bucket"]].append(row)

            fitting_cards.append(
                {
                    "fitting": fitting,
                    "is_configured": True,
                    "skillset": fitting_map.skillset,
                    "priority": fitting_map.priority,
                    "characters": character_rows,
                    "best_required_pct": max(
                        (row["progress"]["required_pct"] for row in character_rows), default=0
                    ),
                    "best_recommended_pct": max(
                        (row["progress"]["recommended_pct"] for row in character_rows), default=0
                    ),
                    "can_any_fly": any(row["progress"]["can_fly"] for row in character_rows),
                    "recommended_plan_skill_count": int(
                        recommended_plan_clone_profile.get("recommended_plan_skill_count", 0) or 0
                    ),
                    "recommended_plan_omega_skill_count": int(
                        recommended_plan_clone_profile.get("recommended_plan_omega_skill_count", 0) or 0
                    ),
                    "recommended_plan_alpha_compatible": bool(
                        recommended_plan_clone_profile.get("recommended_plan_alpha_compatible", True)
                    ),
                    "selected_progress": selected_progress,
                    "elite_rows": bucket_map[BUCKET_ELITE],
                    "almost_elite_rows": bucket_map[BUCKET_ALMOST_ELITE],
                    "can_fly_rows": bucket_map[BUCKET_CAN_FLY],
                    "almost_fit_rows": bucket_map[BUCKET_ALMOST_FIT],
                    "needs_training_rows": bucket_map[BUCKET_NEEDS_TRAINING],
                }
            )

        if fitting_cards:
            doctrine_priority_map = _get_doctrine_priority_map(doctrine_priority_map)
            doctrine_priority = doctrine_priority_map.get(doctrine.id, 0)
            doctrine_cards.append(
                {
                    "doctrine": doctrine,
                    "priority": doctrine_priority,
                    "fittings": sorted(fitting_cards, key=lambda x: (-x["priority"], x["fitting"].name.lower())),
                }
            )

    doctrine_cards.sort(key=lambda x: (-x["priority"], x["doctrine"].name.lower()))

    context = {
        "doctrine_cards": doctrine_cards,
        "character_count": len(member_characters),
        "member_characters": member_characters,
        "selected_character": selected_character,
        "selected_character_id": selected_character_id,
        "selected_status": selected_status,
        "index_status_filter_choices": INDEX_STATUS_FILTER_CHOICES,
        "status_thresholds": thresholds(),
        "search_query": request.GET.get("q", ""),
        "configured_fittings_count": configured_fittings_count,
        "flyable_fittings_count": flyable_fittings_count,
    }
    return render(request, "mastery/index.html", context)


@login_required
@permissions_required('mastery.basic_access')
def pilot_fitting_detail_view(request, fitting_id):
    """Pilot fitting detail view."""
    fitting, fitting_map, doctrine = _get_accessible_fitting_or_404(request.user, fitting_id)
    missing_error = _missing_skillset_error(fitting_map)
    if missing_error:
        return HttpResponseBadRequest(missing_error)

    export_mode = _parse_export_mode(request.GET.get("export_mode"))
    export_language = _parse_export_language(request.GET.get("export_language"))
    selected_character_filter = _parse_character_filter(request.GET.get("character_filter"))
    activity_days = _parse_activity_days(request.GET.get("activity_days"), default=14)
    include_inactive = request.GET.get("include_inactive") == "1"
    raw_group_id = request.GET.get("group_id")
    summary_group = _get_summary_group_by_id(raw_group_id)
    if request.user.has_perm("mastery.doctrine_summary") and raw_group_id and summary_group is None:
        return HttpResponseBadRequest(_("Invalid summary group"))
    member_characters = list(
        _get_pilot_detail_characters(
            request.user,
            summary_group=summary_group,
            activity_days=activity_days,
            include_inactive=include_inactive,
        )
    )
    character_rows = _build_pilot_detail_character_rows(
        fitting_id=fitting.id,
        skillset=fitting_map.skillset,
        member_characters=member_characters,
        export_mode=export_mode,
        export_language=export_language,
        selected_character_filter=selected_character_filter,
        summary_group=summary_group,
        activity_days=activity_days,
        include_inactive=include_inactive,
    )

    selected_character = None
    selected_progress = None
    selected_character_id = request.GET.get("character_id")
    if selected_character_id:
        try:
            selected_character_id = int(selected_character_id)
        except (TypeError, ValueError):
            selected_character_id = None

    if selected_character_id:
        for row in character_rows:
            if row["character"].id == selected_character_id:
                selected_character = row["character"]
                selected_progress = row["progress"]
                break

    character_filter_choices = _build_character_filter_choices_with_counts(character_rows)
    available_filter_values = [value for value, _label in character_filter_choices]
    if selected_character_filter not in available_filter_values:
        if CHARACTER_FILTER_CAN_FLY in available_filter_values:
            selected_character_filter = CHARACTER_FILTER_CAN_FLY
        elif available_filter_values:
            selected_character_filter = available_filter_values[0]

    filtered_character_rows = [
        row for row in character_rows
        if _matches_character_filter(row["progress"], selected_character_filter)
    ]

    # Keep row action links aligned with the active (or normalized) filter.
    for row in character_rows:
        action_params = _pilot_detail_action_params(
            row["character"].id,
            selected_character_filter,
            export_mode,
            export_language,
            summary_group=summary_group,
            activity_days=activity_days,
            include_inactive=include_inactive,
        )
        row["action_url"] = (
            f"{reverse('mastery:pilot_fitting_detail', args=[fitting.id])}?"
            f"{urlencode(action_params)}"
        )

    # If the selected character has been filtered out, reset to first visible character
    if selected_character is not None:
        in_filtered = any(row["character"].id == selected_character.id for row in filtered_character_rows)
        if not in_filtered:
            selected_character = None
            selected_progress = None

    if selected_character is None and filtered_character_rows:
        selected_character = filtered_character_rows[0]["character"]
        selected_progress = filtered_character_rows[0]["progress"]


    if selected_progress is not None:
        selected_progress = {
            **selected_progress,
            "missing_required": pilot_progress_service.localize_missing_rows(
                selected_progress.get("missing_required", []),
                language=export_language,
            ),
            "missing_recommended": pilot_progress_service.localize_missing_rows(
                selected_progress.get("missing_recommended", []),
                language=export_language,
            ),
        }

    for row in character_rows:
        row["is_selected"] = bool(selected_character and row["character"].id == selected_character.id)
    for row in filtered_character_rows:
        row["is_selected"] = bool(selected_character and row["character"].id == selected_character.id)

    export_lines = [] if not selected_progress else pilot_progress_service.build_export_lines(
        selected_progress,
        export_mode,
        character=selected_character,
        language=export_language,
    )
    export_mode_labels = dict(pilot_progress_service.export_mode_choices())
    selected_mode_stats = None if not selected_progress else (
        selected_progress.get("mode_stats", {}).get(export_mode)
        or selected_progress.get("mode_stats", {}).get(pilot_progress_service.EXPORT_MODE_RECOMMENDED)
    )
    skill_plan_summary = None if not selected_progress else pilot_progress_service.build_skill_plan_summary(
        selected_progress,
        export_mode,
        character=selected_character,
        language=export_language,
    )
    recommended_plan_clone_profile = pilot_progress_service.summarize_plan_clone_requirements(
        fitting_map.skillset,
        cache_context={},
    )
    if not isinstance(recommended_plan_clone_profile, dict):
        recommended_plan_clone_profile = {}

    context = {
        "fitting": fitting,
        "doctrine": doctrine,
        "fitting_priority": int(getattr(fitting_map, "priority", 0) or 0),
        "doctrine_priority": int(getattr(getattr(fitting_map, "doctrine_map", None), "priority", 0) or 0),
        "skillset": fitting_map.skillset,
        "character_rows": character_rows,
        "filtered_character_rows": filtered_character_rows,
        "character_filter_choices": character_filter_choices,
        "selected_character_filter": selected_character_filter,
        "selected_character": selected_character,
        "selected_progress": selected_progress,
        "export_mode": export_mode,
        "export_mode_choices": pilot_progress_service.export_mode_choices(),
        "export_mode_label": export_mode_labels.get(export_mode, export_mode.title()),
        "selected_mode_stats": selected_mode_stats,
        "selected_export_lines": export_lines,
        "skill_plan_summary": skill_plan_summary,
        "recommended_plan_skill_count": int(recommended_plan_clone_profile.get("recommended_plan_skill_count", 0) or 0),
        "recommended_plan_omega_skill_count": int(
            recommended_plan_clone_profile.get("recommended_plan_omega_skill_count", 0) or 0
        ),
        "recommended_plan_alpha_compatible": bool(
            recommended_plan_clone_profile.get("recommended_plan_alpha_compatible", True)
        ),
        "export_language": export_language,
        "export_language_scope_label": _("Affects export and selected missing-skill labels"),
        "export_language_choices": pilot_progress_service.export_language_choices(),
        "summary_group_id": None if summary_group is None else summary_group.id,
        "activity_days": activity_days,
        "include_inactive": include_inactive,
    }
    return render(request, "mastery/pilot_fitting_detail.html", context)


@login_required
@permissions_required('mastery.basic_access')
def pilot_fitting_skillplan_export_view(request, fitting_id):
    """Pilot fitting skillplan export view."""
    fitting, fitting_map, _doctrine = _get_accessible_fitting_or_404(request.user, fitting_id)
    missing_error = _missing_skillset_error(fitting_map)
    if missing_error:
        return HttpResponseBadRequest(missing_error)

    character_id = request.GET.get("character_id")
    if not character_id:
        return HttpResponseBadRequest(_("character_id is required"))

    try:
        character_id = int(character_id)
    except (TypeError, ValueError):
        return HttpResponseBadRequest(_("invalid character_id"))

    raw_group_id = request.GET.get("group_id")
    activity_days = _parse_activity_days(request.GET.get("activity_days"), default=14)
    include_inactive = request.GET.get("include_inactive") == "1"
    summary_group = _get_summary_group_by_id(raw_group_id)
    if request.user.has_perm("mastery.doctrine_summary") and raw_group_id and summary_group is None:
        return HttpResponseBadRequest(_("Invalid summary group"))
    available_characters = _get_pilot_detail_characters(
        request.user,
        summary_group=summary_group,
        activity_days=activity_days,
        include_inactive=include_inactive,
    )
    if hasattr(available_characters, "filter"):
        character = available_characters.filter(id=character_id).first()
    else:
        character = next((obj for obj in available_characters if obj.id == character_id), None)
    if character is None:
        return HttpResponseBadRequest(_("character not found"))

    export_mode = _parse_export_mode(request.GET.get("mode"))
    export_language = _parse_export_language(request.GET.get("language"))
    progress = pilot_progress_service.build_for_character(
        character=character,
        skillset=fitting_map.skillset,
        include_export_lines=False,
        cache_context={},
    )
    lines = pilot_progress_service.build_export_lines(
        progress,
        export_mode,
        character=character,
        language=export_language,
    )
    content = "\n".join(lines) if lines else _("No missing skills for this fitting.")

    response = HttpResponse(content, content_type="text/plain; charset=utf-8")
    response[
        "Content-Disposition"
    ] = f'attachment; filename="skillplan-{export_mode}-fit-{fitting.id}-char-{character.id}.txt"'
    return response
