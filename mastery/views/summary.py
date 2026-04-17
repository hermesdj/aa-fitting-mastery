"""Summary/reporting views for doctrine readiness."""
import csv

from allianceauth.authentication.decorators import permissions_required
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from mastery.models import SummaryAudienceEntity, SummaryAudienceGroup
from mastery.services.pilots.status_buckets import (
    BUCKET_ALMOST_ELITE,
    BUCKET_ALMOST_FIT,
    BUCKET_CAN_FLY,
    BUCKET_ELITE,
    BUCKET_NEEDS_TRAINING,
    bucket_choice_list,
    thresholds,
)

from .common import (
    _approved_fitting_maps,
    _annotate_member_detail_pilots,
    _build_doctrine_summary,
    _build_fitting_kpis,
    _build_fitting_user_rows,
    _build_member_groups_for_summary,
    _get_accessible_fitting_or_404,
    _get_selected_summary_group,
    _parse_activity_days,
    _parse_export_mode,
    _summary_entity_catalog,
    _missing_skillset_error,
    pilot_access_service,
    pilot_progress_service,
)

_MEMBER_COVERAGE_FILTERS = {value for value, _label in bucket_choice_list(include_all=True)}

def _summary_fitting_member_coverage_csv_response(fitting, user_rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="fitting-{fitting.id}-member-coverage.csv"'
    )

    writer = csv.writer(response)
    writer.writerow(
        [
            "member_username",
            "main_character",
            "bucket",
            "character_name",
            "required_pct",
            "recommended_pct",
            "required_missing_sp",
            "recommended_missing_sp",
            "can_fly",
        ]
    )

    bucket_fields = [
        (BUCKET_ELITE, "elite_pilots"),
        (BUCKET_ALMOST_ELITE, "almost_elite_pilots"),
        (BUCKET_CAN_FLY, "can_fly_pilots"),
        (BUCKET_ALMOST_FIT, "almost_fit_pilots"),
        (BUCKET_NEEDS_TRAINING, "needs_training_pilots"),
    ]

    for row in user_rows:
        username = getattr(row.get("user"), "username", "")
        main_character = getattr(row.get("main_character"), "character_name", "")
        for bucket_name, field_name in bucket_fields:
            for pilot in row.get(field_name, []):
                progress = pilot.get("progress", {})
                character_name = getattr(
                    getattr(pilot.get("character"), "eve_character", None),
                    "character_name",
                    "",
                )
                writer.writerow(
                    [
                        username,
                        main_character,
                        bucket_name,
                        character_name,
                        float(progress.get("required_pct") or 0),
                        float(progress.get("recommended_pct") or 0),
                        int(pilot.get("required_missing_sp") or 0),
                        int(pilot.get("recommended_missing_sp") or 0),
                        bool(progress.get("can_fly")),
                    ]
                )

    return response


@login_required
@permissions_required('mastery.doctrine_summary')
def summary_list_view(request):
    """Summary list view."""
    activity_days = _parse_activity_days(request.GET.get("activity_days"), default=14)
    include_inactive = request.GET.get("include_inactive") == "1"
    search_query = (request.GET.get("q") or "").strip().lower()
    summary_groups, selected_group = _get_selected_summary_group(request.GET.get("group_id"))

    member_groups = _build_member_groups_for_summary(
        summary_group=selected_group,
        activity_days=activity_days,
        include_inactive=include_inactive,
    )

    doctrines = pilot_access_service.accessible_doctrines(request.user).prefetch_related("fittings__ship_type")
    fitting_maps = _approved_fitting_maps()
    progress_cache = {}
    progress_context = {}

    doctrine_summaries = []
    for doctrine in doctrines:
        if search_query and search_query not in doctrine.name.lower():
            fitting_names = [f"{fit.name} {fit.ship_type.name}".lower() for fit in doctrine.fittings.all()]
            if not any(search_query in name for name in fitting_names):
                continue
        summary_item = _build_doctrine_summary(
            doctrine=doctrine,
            fitting_maps=fitting_maps,
            member_groups=member_groups,
            progress_cache=progress_cache,
            progress_context=progress_context,
        )
        doctrine_summaries += [summary_item]

    context = {
        "doctrine_summaries": doctrine_summaries,
        "summary_groups": summary_groups,
        "selected_group": selected_group,
        "activity_days": activity_days,
        "include_inactive": include_inactive,
        "search_query": request.GET.get("q", ""),
        "member_count": len(member_groups),
        "active_character_count": sum(group["active_count"] for group in member_groups),
        "status_thresholds": thresholds(),
    }
    return render(request, "mastery/summary_list_view.html", context)


@login_required
@permissions_required('mastery.doctrine_summary')
def summary_doctrine_detail_view(request, doctrine_id):
    """Summary doctrine detail view."""
    activity_days = _parse_activity_days(request.GET.get("activity_days"), default=14)
    include_inactive = request.GET.get("include_inactive") == "1"
    summary_groups, selected_group = _get_selected_summary_group(request.GET.get("group_id"))

    if selected_group is None:
        return HttpResponseBadRequest("No summary group configured")

    doctrine = get_object_or_404(
        pilot_access_service.accessible_doctrines(request.user).prefetch_related("fittings__ship_type"),
        id=doctrine_id,
    )
    fitting_maps = _approved_fitting_maps()
    member_groups = _build_member_groups_for_summary(
        summary_group=selected_group,
        activity_days=activity_days,
        include_inactive=include_inactive,
    )
    progress_cache = {}
    progress_context = {}
    summary = _build_doctrine_summary(
        doctrine=doctrine,
        fitting_maps=fitting_maps,
        member_groups=member_groups,
        progress_cache=progress_cache,
        progress_context=progress_context,
    )
    for fit in summary["fittings"]:
        if fit.get("configured"):
            fit["kpis"] = _build_fitting_kpis(fit.get("user_rows", []))

    return render(
        request,
        "mastery/summary_doctrine_detail.html",
        {
            "summary": summary,
            "summary_groups": summary_groups,
            "selected_group": selected_group,
            "activity_days": activity_days,
            "include_inactive": include_inactive,
        },
    )


@login_required
@permissions_required('mastery.doctrine_summary')
def summary_fitting_detail_view(request, fitting_id):
    """Summary fitting detail view."""
    activity_days = _parse_activity_days(request.GET.get("activity_days"), default=14)
    include_inactive = request.GET.get("include_inactive") == "1"
    export_mode = _parse_export_mode(request.GET.get("export_mode"))
    selected_member_filter = (request.GET.get("kpi_filter") or "all").strip().lower()
    if selected_member_filter not in _MEMBER_COVERAGE_FILTERS:
        selected_member_filter = "all"
    summary_groups, selected_group = _get_selected_summary_group(request.GET.get("group_id"))

    if selected_group is None:
        return HttpResponseBadRequest("No summary group configured")

    fitting, fitting_map, doctrine = _get_accessible_fitting_or_404(request.user, fitting_id)
    missing_error = _missing_skillset_error(fitting_map)
    if missing_error:
        return HttpResponseBadRequest(missing_error)

    member_groups = _build_member_groups_for_summary(
        summary_group=selected_group,
        activity_days=activity_days,
        include_inactive=include_inactive,
    )

    progress_cache = {}
    progress_context = {}
    user_rows = _build_fitting_user_rows(
        fitting_map=fitting_map,
        member_groups=member_groups,
        progress_cache=progress_cache,
        progress_context=progress_context,
    )
    fitting_kpis = _build_fitting_kpis(user_rows)
    user_rows = _annotate_member_detail_pilots(user_rows)

    if request.GET.get("format") == "csv":
        return _summary_fitting_member_coverage_csv_response(fitting=fitting, user_rows=user_rows)

    return render(
        request,
        "mastery/summary_fitting_detail.html",
        {
            "fitting": fitting,
            "fitting_map": fitting_map,
            "doctrine": doctrine,
            "fitting_kpis": fitting_kpis,
            "user_rows": user_rows,
            "summary_groups": summary_groups,
            "selected_group": selected_group,
            "activity_days": activity_days,
            "include_inactive": include_inactive,
            "export_mode": export_mode,
            "selected_member_filter": selected_member_filter,
            "export_mode_choices": pilot_progress_service.export_mode_choices(),
            "status_thresholds": thresholds(),
        },
    )


@login_required
@permissions_required('mastery.manage_summary_groups')
def summary_settings_view(request):
    """Summary settings view."""
    selected_group_id = request.GET.get("group_id")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create_group":
            name = (request.POST.get("name") or "").strip()
            description = (request.POST.get("description") or "").strip()
            if not name:
                return HttpResponseBadRequest("name is required")
            SummaryAudienceGroup.objects.create(name=name, description=description)
            messages.success(request, "Summary group created")
            return redirect("mastery:summary_settings")

        if action == "delete_group":
            group = get_object_or_404(SummaryAudienceGroup, id=request.POST.get("group_id"))
            group.delete()
            messages.success(request, "Summary group deleted")
            return redirect("mastery:summary_settings")

        if action == "toggle_group_active":
            group = get_object_or_404(SummaryAudienceGroup, id=request.POST.get("group_id"))
            group.is_active = not group.is_active
            group.save(update_fields=["is_active"])
            messages.success(request, "Summary group updated")
            return redirect(f"{redirect('mastery:summary_settings').url}?group_id={group.id}")

        if action == "add_entry":
            group = get_object_or_404(SummaryAudienceGroup, id=request.POST.get("group_id"))
            entity_type = request.POST.get("entity_type")
            if entity_type not in {SummaryAudienceEntity.TYPE_CORPORATION, SummaryAudienceEntity.TYPE_ALLIANCE}:
                return HttpResponseBadRequest("invalid entity_type")
            try:
                entity_id = int(request.POST.get("entity_id"))
            except (TypeError, ValueError):
                return HttpResponseBadRequest("invalid entity_id")
            label = (request.POST.get("label") or "").strip()

            SummaryAudienceEntity.objects.update_or_create(
                group=group,
                entity_type=entity_type,
                entity_id=entity_id,
                defaults={"label": label},
            )
            messages.success(request, "Entry saved")
            return redirect(f"{redirect('mastery:summary_settings').url}?group_id={group.id}")

        if action == "delete_entry":
            entry = get_object_or_404(SummaryAudienceEntity, id=request.POST.get("entry_id"))
            group_id = entry.group_id
            entry.delete()
            messages.success(request, "Entry deleted")
            return redirect(f"{redirect('mastery:summary_settings').url}?group_id={group_id}")

        return HttpResponseBadRequest("Unsupported action")

    summary_groups, selected_group = _get_selected_summary_group(selected_group_id)
    corporation_options, alliance_options = _summary_entity_catalog()

    corp_name_map = {obj["id"]: obj["name"] for obj in corporation_options}
    alliance_name_map = {obj["id"]: obj["name"] for obj in alliance_options}
    selected_group_entries = []
    existing_corp_ids = set()
    existing_alliance_ids = set()
    if selected_group:
        for entry in selected_group.entries.all():
            if entry.entity_type == SummaryAudienceEntity.TYPE_CORPORATION:
                entity_name = corp_name_map.get(entry.entity_id) or f"Corporation #{entry.entity_id}"
                existing_corp_ids.add(entry.entity_id)
            else:
                entity_name = alliance_name_map.get(entry.entity_id) or f"Alliance #{entry.entity_id}"
                existing_alliance_ids.add(entry.entity_id)
            selected_group_entries.append(
                {
                    "entry": entry,
                    "entity_name": entity_name,
                }
            )

    corporation_options = [obj for obj in corporation_options if obj["id"] not in existing_corp_ids]
    alliance_options = [obj for obj in alliance_options if obj["id"] not in existing_alliance_ids]

    return render(
        request,
        "mastery/summary_settings.html",
        {
            "summary_groups": summary_groups,
            "selected_group": selected_group,
            "selected_group_entries": selected_group_entries,
            "entity_type_choices": SummaryAudienceEntity.TYPE_CHOICES,
            "corporation_options": corporation_options,
            "alliance_options": alliance_options,
        },
    )
