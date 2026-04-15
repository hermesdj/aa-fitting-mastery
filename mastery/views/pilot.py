"""Pilot-facing views: doctrine/fitting progress for individual users."""

from allianceauth.authentication.decorators import permissions_required
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render

from .common import (
    FittingSkillsetMap,
    _get_accessible_fitting_or_404,
    _get_member_characters,
    _get_pilot_detail_characters,
    _get_summary_group_by_id,
    _parse_export_language,
    _parse_export_mode,
    pilot_access_service,
    pilot_progress_service,
)


@login_required
@permissions_required('mastery.basic_access')
def index(request):
    """Render pilot overview cards across accessible doctrines and fittings."""
    doctrines = pilot_access_service.accessible_doctrines(request.user)
    member_characters = list(_get_member_characters(request.user))
    selected_character_id = request.GET.get("character_id")
    selected_status = (request.GET.get("status") or "all").strip().lower()
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

    fitting_maps = {
        obj.fitting.pk: obj
        for obj in FittingSkillsetMap.objects.select_related("skillset", "doctrine_map").all()
    }

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
                name_match = (
                    not search_query
                    or search_query in doctrine.name.lower()
                    or search_query in fitting.name.lower()
                    or search_query in fitting.ship_type.name.lower()
                )
                if not name_match:
                    continue
                fitting_cards.append(
                    {
                        "fitting": fitting,
                        "is_configured": False,
                        "characters": [],
                        "best_required_pct": 0,
                        "best_recommended_pct": 0,
                        "can_any_fly": False,
                        "selected_progress": None,
                    }
                )
                continue

            character_rows = []
            for character in member_characters:
                progress = pilot_progress_service.build_for_character(
                    character=character,
                    skillset=fitting_map.skillset,
                )
                character_rows.append(
                    {
                        "character": character,
                        "progress": progress,
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

            if selected_status == "flyable" and (not progress_for_filter or not progress_for_filter["can_fly"]):
                continue
            if selected_status == "training":
                if selected_character_id:
                    if not progress_for_filter or progress_for_filter["can_fly"]:
                        continue
                else:
                    if character_rows and all(row["progress"]["can_fly"] for row in character_rows):
                        continue
                    if not character_rows and (not progress_for_filter or progress_for_filter["can_fly"]):
                        continue
            if selected_status == "elite" and (
                not progress_for_filter or progress_for_filter["status_label"] != "Elite ready"
            ):
                continue

            configured_fittings_count += 1
            if progress_for_filter and progress_for_filter["can_fly"]:
                flyable_fittings_count += 1

            fitting_cards.append(
                {
                    "fitting": fitting,
                    "is_configured": True,
                    "skillset": fitting_map.skillset,
                    "characters": character_rows,
                    "best_required_pct": max(
                        (row["progress"]["required_pct"] for row in character_rows), default=0
                    ),
                    "best_recommended_pct": max(
                        (row["progress"]["recommended_pct"] for row in character_rows), default=0
                    ),
                    "can_any_fly": any(row["progress"]["can_fly"] for row in character_rows),
                    "selected_progress": selected_progress,
                }
            )

        if fitting_cards:
            doctrine_cards.append(
                {
                    "doctrine": doctrine,
                    "fittings": sorted(fitting_cards, key=lambda x: x["fitting"].name.lower()),
                }
            )

    context = {
        "doctrine_cards": doctrine_cards,
        "character_count": len(member_characters),
        "member_characters": member_characters,
        "selected_character": selected_character,
        "selected_character_id": selected_character_id,
        "selected_status": selected_status,
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
    if not fitting_map:
        return HttpResponseBadRequest("No skillset configured for this fitting yet")

    export_mode = _parse_export_mode(request.GET.get("export_mode"))
    export_language = _parse_export_language(request.GET.get("export_language"))
    raw_group_id = request.GET.get("group_id")
    summary_group = _get_summary_group_by_id(raw_group_id)
    if request.user.has_perm("mastery.doctrine_summary") and raw_group_id and summary_group is None:
        return HttpResponseBadRequest("Invalid summary group")
    member_characters = list(_get_pilot_detail_characters(request.user, summary_group=summary_group))
    character_rows = []
    for character in member_characters:
        progress = pilot_progress_service.build_for_character(
            character=character,
            skillset=fitting_map.skillset,
        )
        character_rows.append(
            {
                "character": character,
                "progress": progress,
            }
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

    if selected_character is None and character_rows:
        selected_character = character_rows[0]["character"]
        selected_progress = character_rows[0]["progress"]

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

    context = {
        "fitting": fitting,
        "doctrine": doctrine,
        "skillset": fitting_map.skillset,
        "character_rows": character_rows,
        "selected_character": selected_character,
        "selected_progress": selected_progress,
        "export_mode": export_mode,
        "export_mode_choices": pilot_progress_service.export_mode_choices(),
        "export_mode_label": export_mode_labels.get(export_mode, export_mode.title()),
        "selected_mode_stats": selected_mode_stats,
        "selected_export_lines": export_lines,
        "skill_plan_summary": skill_plan_summary,
        "export_language": export_language,
        "export_language_scope_label": "Affects export and selected missing-skill labels",
        "export_language_choices": pilot_progress_service.export_language_choices(),
        "summary_group_id": None if summary_group is None else summary_group.id,
    }
    return render(request, "mastery/pilot_fitting_detail.html", context)


@login_required
@permissions_required('mastery.basic_access')
def pilot_fitting_skillplan_export_view(request, fitting_id):
    """Pilot fitting skillplan export view."""
    fitting, fitting_map, _ = _get_accessible_fitting_or_404(request.user, fitting_id)
    if not fitting_map:
        return HttpResponseBadRequest("No skillset configured for this fitting yet")

    character_id = request.GET.get("character_id")
    if not character_id:
        return HttpResponseBadRequest("character_id is required")

    try:
        character_id = int(character_id)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("invalid character_id")

    raw_group_id = request.GET.get("group_id")
    summary_group = _get_summary_group_by_id(raw_group_id)
    if request.user.has_perm("mastery.doctrine_summary") and raw_group_id and summary_group is None:
        return HttpResponseBadRequest("Invalid summary group")
    character = _get_pilot_detail_characters(request.user, summary_group=summary_group).filter(id=character_id).first()
    if character is None:
        return HttpResponseBadRequest("character not found")

    export_mode = _parse_export_mode(request.GET.get("mode"))
    export_language = _parse_export_language(request.GET.get("language"))
    progress = pilot_progress_service.build_for_character(character=character, skillset=fitting_map.skillset)
    lines = pilot_progress_service.build_export_lines(
        progress,
        export_mode,
        character=character,
        language=export_language,
    )
    content = "\n".join(lines) if lines else "No missing skills for this fitting."

    response = HttpResponse(content, content_type="text/plain; charset=utf-8")
    response[
        "Content-Disposition"
    ] = f'attachment; filename="skillplan-{export_mode}-fit-{fitting.id}-char-{character.id}.txt"'
    return response
