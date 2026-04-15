"""Summary/reporting views for doctrine readiness."""
from allianceauth.authentication.decorators import permissions_required
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from mastery.models import FittingSkillsetMap, SummaryAudienceEntity, SummaryAudienceGroup

from .common import (
    _annotate_member_detail_pilots,
    _build_doctrine_summary,
    _build_fitting_kpis,
    _build_fitting_user_rows,
    _build_member_groups_for_summary,
    _get_accessible_fitting_or_404,
    _get_selected_summary_group,
    _parse_activity_days,
    _parse_export_mode,
    _parse_training_days,
    _summary_entity_catalog,
    pilot_access_service,
    pilot_progress_service,
)


@login_required
@permissions_required('mastery.doctrine_summary')
def summary_list_view(request):
    """Summary list view."""
    activity_days = _parse_activity_days(request.GET.get("activity_days"), default=14)
    training_days = _parse_training_days(request.GET.get("training_days"), default=7)
    include_inactive = request.GET.get("include_inactive") == "1"
    search_query = (request.GET.get("q") or "").strip().lower()
    summary_groups, selected_group = _get_selected_summary_group(request.GET.get("group_id"))

    member_groups = _build_member_groups_for_summary(
        summary_group=selected_group,
        activity_days=activity_days,
        include_inactive=include_inactive,
    )

    doctrines = pilot_access_service.accessible_doctrines(request.user).prefetch_related("fittings__ship_type")
    fitting_maps = {
        obj.fitting_id: obj
        for obj in FittingSkillsetMap.objects.select_related("skillset", "doctrine_map").all()
    }
    progress_cache = {}

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
            training_days=training_days,
        )
        doctrine_summaries += [summary_item]

    context = {
        "doctrine_summaries": doctrine_summaries,
        "summary_groups": summary_groups,
        "selected_group": selected_group,
        "activity_days": activity_days,
        "training_days": training_days,
        "include_inactive": include_inactive,
        "search_query": request.GET.get("q", ""),
        "member_count": len(member_groups),
        "active_character_count": sum(group["active_count"] for group in member_groups),
    }
    return render(request, "mastery/summary_list_view.html", context)


@login_required
@permissions_required('mastery.doctrine_summary')
def summary_doctrine_detail_view(request, doctrine_id):
    """Summary doctrine detail view."""
    activity_days = _parse_activity_days(request.GET.get("activity_days"), default=14)
    training_days = _parse_training_days(request.GET.get("training_days"), default=7)
    include_inactive = request.GET.get("include_inactive") == "1"
    summary_groups, selected_group = _get_selected_summary_group(request.GET.get("group_id"))

    if selected_group is None:
        return HttpResponseBadRequest("No summary group configured")

    doctrine = get_object_or_404(
        pilot_access_service.accessible_doctrines(request.user).prefetch_related("fittings__ship_type"),
        id=doctrine_id,
    )
    fitting_maps = {
        obj.fitting_id: obj
        for obj in FittingSkillsetMap.objects.select_related("skillset", "doctrine_map").all()
    }
    member_groups = _build_member_groups_for_summary(
        summary_group=selected_group,
        activity_days=activity_days,
        include_inactive=include_inactive,
    )
    progress_cache = {}
    summary = _build_doctrine_summary(
        doctrine=doctrine,
        fitting_maps=fitting_maps,
        member_groups=member_groups,
        progress_cache=progress_cache,
        training_days=training_days,
    )
    for fit in summary["fittings"]:
        if fit.get("configured"):
            fit["kpis"] = _build_fitting_kpis(fit.get("user_rows", []), training_days=training_days)

    return render(
        request,
        "mastery/summary_doctrine_detail.html",
        {
            "summary": summary,
            "summary_groups": summary_groups,
            "selected_group": selected_group,
            "activity_days": activity_days,
            "training_days": training_days,
            "include_inactive": include_inactive,
        },
    )


@login_required
@permissions_required('mastery.doctrine_summary')
def summary_fitting_detail_view(request, fitting_id):
    """Summary fitting detail view."""
    activity_days = _parse_activity_days(request.GET.get("activity_days"), default=14)
    training_days = _parse_training_days(request.GET.get("training_days"), default=7)
    include_inactive = request.GET.get("include_inactive") == "1"
    export_mode = _parse_export_mode(request.GET.get("export_mode"))
    summary_groups, selected_group = _get_selected_summary_group(request.GET.get("group_id"))

    if selected_group is None:
        return HttpResponseBadRequest("No summary group configured")

    fitting, fitting_map, doctrine = _get_accessible_fitting_or_404(request.user, fitting_id)
    if not fitting_map or not fitting_map.skillset:
        return HttpResponseBadRequest("No skillset configured for this fitting yet")

    member_groups = _build_member_groups_for_summary(
        summary_group=selected_group,
        activity_days=activity_days,
        include_inactive=include_inactive,
    )

    progress_cache = {}
    user_rows = _build_fitting_user_rows(
        fitting_map=fitting_map,
        member_groups=member_groups,
        progress_cache=progress_cache,
    )
    fitting_kpis = _build_fitting_kpis(user_rows, training_days=training_days)
    user_rows = _annotate_member_detail_pilots(user_rows, training_days=training_days)

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
            "training_days": training_days,
            "include_inactive": include_inactive,
            "export_mode": export_mode,
            "export_mode_choices": pilot_progress_service.export_mode_choices(),
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
