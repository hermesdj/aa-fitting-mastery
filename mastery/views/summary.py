"""Summary/reporting views for doctrine readiness."""
import csv
from datetime import timezone as dt_timezone
from time import perf_counter

from allianceauth.authentication.decorators import permissions_required
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.utils.translation import gettext as _
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
    _prime_summary_character_skills_cache_context,
    _summary_entity_catalog,
    _missing_skillset_error,
    pilot_access_service,
    pilot_progress_service,
)

_MEMBER_COVERAGE_FILTERS = {value for value, _label in bucket_choice_list(include_all=True)}
_SUMMARY_DEBUG_METRICS_SESSION_KEY = "mastery_p2_metrics_debug_snapshots"
_SUMMARY_DEBUG_METRICS_DEFAULT_PER_SOURCE_LIMIT = 5
_SUMMARY_DEBUG_METRICS_PER_SOURCE_LIMITS = {
    # Legacy alias kept for compatibility with older snapshots/emitters.
    "summary_view": 5,
    "summary_list": 5,
    "summary_doctrine_detail": 5,
    "summary_fitting_detail": 5,
}


def _summary_debug_snapshot_limit_for_source(source: str) -> int:
    """Return retention limit for one snapshot source."""
    normalized_source = str(source or "").strip() or "unknown"
    configured = _SUMMARY_DEBUG_METRICS_PER_SOURCE_LIMITS.get(
        normalized_source,
        _SUMMARY_DEBUG_METRICS_DEFAULT_PER_SOURCE_LIMIT,
    )
    return max(1, int(configured))


def _summary_debug_enabled(request) -> bool:
    """Return whether request-scoped summary debug metrics should be collected."""
    return bool(request.user.has_perm("mastery.manage_fittings"))


def _start_summary_debug_trace(request) -> dict | None:
    """Capture request-scoped baseline values for summary debug instrumentation."""
    if not request.user.has_perm("mastery.manage_fittings"):
        return None

    return {
        "started_at": perf_counter(),
        "sql_queries_start": len(getattr(connection, "queries", [])),
    }


def _summary_phase_metrics(progress_context: dict | None, phase_name: str, metric_name: str) -> dict:
    """Return a mutable phase metrics bucket inside a progress context."""
    if progress_context is None:
        return {}
    return progress_context.setdefault(phase_name, {}).setdefault(metric_name, {})


def _store_summary_metrics_debug_snapshot(
    request,
    source: str,
    progress_context: dict | None,
    trace: dict | None = None,
) -> None:
    """Persist the latest summary debug metrics in session for plugin admins."""
    if progress_context is None:
        return
    if not _summary_debug_enabled(request):
        return

    session = getattr(request, "session", None)
    if session is None:
        return

    summary_view_metrics = _summary_phase_metrics(progress_context, "p0_metrics", "summary_view")
    if trace is not None:
        summary_view_metrics.setdefault(
            "view_total_ms",
            round((perf_counter() - float(trace.get("started_at", 0.0))) * 1000, 2),
        )
        summary_view_metrics.setdefault(
            "sql_query_count",
            max(0, len(getattr(connection, "queries", [])) - int(trace.get("sql_queries_start", 0))),
        )

    metrics = {
        key: value
        for key, value in progress_context.items()
        if key.endswith("_metrics") and isinstance(value, dict) and value
    }
    if not metrics:
        return

    snapshot = {
        "captured_at": timezone.now().isoformat(),
        "source": source,
        "metrics": metrics,
    }
    snapshots = list(session.get(_SUMMARY_DEBUG_METRICS_SESSION_KEY, []))
    snapshots.append(snapshot)

    # Keep an independent retention window per source (no shared global cap).
    retained_reversed = []
    retained_counts: dict[str, int] = {}
    for row in reversed(snapshots):
        row_source = str(row.get("source") or "unknown")
        source_limit = _summary_debug_snapshot_limit_for_source(row_source)
        current_count = retained_counts.get(row_source, 0)
        if current_count >= source_limit:
            continue
        retained_counts[row_source] = current_count + 1
        retained_reversed.append(row)

    retained_reversed.reverse()
    session[_SUMMARY_DEBUG_METRICS_SESSION_KEY] = retained_reversed


def _store_p2_metrics_debug_snapshot(request, source: str, progress_context: dict | None) -> None:
    """Backward-compatible wrapper for storing summary debug snapshots."""
    _store_summary_metrics_debug_snapshot(
        request=request,
        source=source,
        progress_context=progress_context,
    )

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
    debug_trace = _start_summary_debug_trace(request)
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
    _prime_summary_character_skills_cache_context(
        member_groups=member_groups,
        cache_context=progress_context,
    )

    # Build doctrine-id → priority map from already-prefetched doctrine_map FK (no extra DB query)
    doctrine_priority_map: dict[int, int] = {}
    for fitting_map in fitting_maps.values():
        dm = getattr(fitting_map, "doctrine_map", None)
        if dm is not None:
            doc_id = getattr(dm, "doctrine_id", None)
            if doc_id is not None:
                doctrine_priority_map[doc_id] = int(getattr(dm, "priority", 0) or 0)

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
            doctrine_priority=doctrine_priority_map.get(doctrine.id, 0),
        )
        if int(summary_item.get("configured_fittings", 0)) <= 0:
            continue
        doctrine_summaries += [summary_item]

    _summary_phase_metrics(progress_context, "p0_metrics", "summary_view").update(
        {
            "member_groups": len(member_groups),
            "active_characters_total": sum(group["active_count"] for group in member_groups),
            "progress_cache_entries": len(progress_cache),
            "visible_doctrines": len(doctrine_summaries),
        }
    )
    _store_summary_metrics_debug_snapshot(
        request=request,
        source="summary_list",
        progress_context=progress_context,
        trace=debug_trace,
    )

    doctrine_summaries.sort(
        key=lambda item: (
            -int(item.get("priority", 0) or 0),
            (item["doctrine"].name or "").lower(),
        )
    )

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
    debug_trace = _start_summary_debug_trace(request)
    activity_days = _parse_activity_days(request.GET.get("activity_days"), default=14)
    include_inactive = request.GET.get("include_inactive") == "1"
    summary_groups, selected_group = _get_selected_summary_group(request.GET.get("group_id"))

    if selected_group is None:
        return HttpResponseBadRequest(_("No summary group configured"))

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
    _prime_summary_character_skills_cache_context(
        member_groups=member_groups,
        cache_context=progress_context,
    )

    # Derive doctrine priority from already-prefetched doctrine_map (no extra DB query)
    _doctrine_priority: int = 0
    for fitting_map in fitting_maps.values():
        dm = getattr(fitting_map, "doctrine_map", None)
        if dm is not None and getattr(dm, "doctrine_id", None) == doctrine.id:
            _doctrine_priority = int(getattr(dm, "priority", 0) or 0)
            break

    summary = _build_doctrine_summary(
        doctrine=doctrine,
        fitting_maps=fitting_maps,
        member_groups=member_groups,
        progress_cache=progress_cache,
        progress_context=progress_context,
        doctrine_priority=_doctrine_priority,
    )

    _summary_phase_metrics(progress_context, "p0_metrics", "summary_view").update(
        {
            "member_groups": len(member_groups),
            "active_characters_total": sum(group["active_count"] for group in member_groups),
            "progress_cache_entries": len(progress_cache),
            "configured_fittings": int(summary.get("configured_fittings", 0) or 0),
            "fittings_total": int(summary.get("fittings_total", 0) or 0),
        }
    )
    _store_summary_metrics_debug_snapshot(
        request=request,
        source="summary_doctrine_detail",
        progress_context=progress_context,
        trace=debug_trace,
    )

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
    debug_trace = _start_summary_debug_trace(request)
    activity_days = _parse_activity_days(request.GET.get("activity_days"), default=14)
    include_inactive = request.GET.get("include_inactive") == "1"
    export_mode = _parse_export_mode(request.GET.get("export_mode"))
    selected_member_filter = (request.GET.get("kpi_filter") or "all").strip().lower()
    if selected_member_filter not in _MEMBER_COVERAGE_FILTERS:
        selected_member_filter = "all"
    summary_groups, selected_group = _get_selected_summary_group(request.GET.get("group_id"))

    if selected_group is None:
        return HttpResponseBadRequest(_("No summary group configured"))

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
    _prime_summary_character_skills_cache_context(
        member_groups=member_groups,
        cache_context=progress_context,
    )
    user_rows = _build_fitting_user_rows(
        fitting_map=fitting_map,
        member_groups=member_groups,
        progress_cache=progress_cache,
        progress_context=progress_context,
    )
    user_rows = _annotate_member_detail_pilots(user_rows)
    fitting_kpis = _build_fitting_kpis(user_rows)

    _summary_phase_metrics(progress_context, "p0_metrics", "summary_view").update(
        {
            "member_groups": len(member_groups),
            "active_characters_total": sum(group["active_count"] for group in member_groups),
            "progress_cache_entries": len(progress_cache),
            "user_rows": len(user_rows),
            "flyable_now_users": int(fitting_kpis.get("flyable_now_users", 0) or 0),
        }
    )
    _store_summary_metrics_debug_snapshot(
        request=request,
        source="summary_fitting_detail",
        progress_context=progress_context,
        trace=debug_trace,
    )

    if request.GET.get("format") == "csv":
        return _summary_fitting_member_coverage_csv_response(fitting=fitting, user_rows=user_rows)

    doctrine_priority = 0 if doctrine is None else int(
        getattr(getattr(fitting_map, "doctrine_map", None), "priority", 0) or 0
    )

    return render(
        request,
        "mastery/summary_fitting_detail.html",
        {
            "fitting": fitting,
            "fitting_map": fitting_map,
            "doctrine": doctrine,
            "doctrine_priority": doctrine_priority,
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
                return HttpResponseBadRequest(_("name is required"))
            SummaryAudienceGroup.objects.create(name=name, description=description)
            messages.success(request, _("Summary group created"))
            return redirect("mastery:summary_settings")

        if action == "delete_group":
            group = get_object_or_404(SummaryAudienceGroup, id=request.POST.get("group_id"))
            group.delete()
            messages.success(request, _("Summary group deleted"))
            return redirect("mastery:summary_settings")

        if action == "toggle_group_active":
            group = get_object_or_404(SummaryAudienceGroup, id=request.POST.get("group_id"))
            group.is_active = not group.is_active
            group.save(update_fields=["is_active"])
            messages.success(request, _("Summary group updated"))
            return redirect(f"{redirect('mastery:summary_settings').url}?group_id={group.id}")

        if action == "add_entry":
            group = get_object_or_404(SummaryAudienceGroup, id=request.POST.get("group_id"))
            entity_type = request.POST.get("entity_type")
            if entity_type not in {SummaryAudienceEntity.TYPE_CORPORATION, SummaryAudienceEntity.TYPE_ALLIANCE}:
                return HttpResponseBadRequest(_("invalid entity_type"))
            try:
                entity_id = int(request.POST.get("entity_id"))
            except (TypeError, ValueError):
                return HttpResponseBadRequest(_("invalid entity_id"))
            label = (request.POST.get("label") or "").strip()

            SummaryAudienceEntity.objects.update_or_create(
                group=group,
                entity_type=entity_type,
                entity_id=entity_id,
                defaults={"label": label},
            )
            messages.success(request, _("Entry saved"))
            return redirect(f"{redirect('mastery:summary_settings').url}?group_id={group.id}")

        if action == "delete_entry":
            entry = get_object_or_404(SummaryAudienceEntity, id=request.POST.get("entry_id"))
            group_id = entry.group_id
            entry.delete()
            messages.success(request, _("Entry deleted"))
            return redirect(f"{redirect('mastery:summary_settings').url}?group_id={group_id}")

        return HttpResponseBadRequest(_("Unsupported action"))

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


@login_required
@permissions_required('mastery.manage_fittings')
def summary_p2_metrics_debug_view(request):
    """Display request snapshots of summary optimization metrics for plugin admins."""
    raw_snapshots = list(getattr(request, "session", {}).get(_SUMMARY_DEBUG_METRICS_SESSION_KEY, []))
    raw_snapshots.reverse()

    snapshots = []
    grouped_sources: dict[str, dict] = {}
    for index, snapshot in enumerate(raw_snapshots, start=1):
        normalized = dict(snapshot)
        metrics = normalized.get("metrics") or {}
        p0_metrics = (metrics.get("p0_metrics") or {}).get("summary_view") or {}

        try:
            priority_score_ms = int(round(float(p0_metrics.get("view_total_ms") or 0)))
        except (TypeError, ValueError):
            priority_score_ms = 0

        captured_at = normalized.get("captured_at")
        captured_at_human = str(captured_at or "")
        captured_at_short = captured_at_human
        if captured_at:
            parsed_dt = parse_datetime(str(captured_at))
            if parsed_dt is not None:
                if timezone.is_naive(parsed_dt):
                    parsed_dt = timezone.make_aware(parsed_dt, dt_timezone.utc)
                parsed_utc = parsed_dt.astimezone(dt_timezone.utc)
                captured_at_human = parsed_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
                captured_at_short = parsed_utc.strftime("%d %b %H:%M")

        normalized["priority_score_ms"] = priority_score_ms
        normalized["priority_rank"] = index
        normalized["captured_at_human"] = captured_at_human
        normalized["captured_at_short"] = captured_at_short
        snapshots.append(normalized)

        source_name = str(normalized.get("source") or "unknown")
        source_group = grouped_sources.setdefault(
            source_name,
            {
                "source": source_name,
                "snapshots": [],
                "max_priority_score_ms": 0,
            },
        )
        source_group["snapshots"].append(normalized)
        source_group["max_priority_score_ms"] = max(
            int(source_group["max_priority_score_ms"]),
            int(priority_score_ms),
        )

    snapshot_sources = list(grouped_sources.values())

    return render(
        request,
        "mastery/summary_p2_metrics_debug.html",
        {
            "snapshots": snapshots,
            "snapshot_sources": snapshot_sources,
            "snapshot_count": len(snapshots),
        },
    )
