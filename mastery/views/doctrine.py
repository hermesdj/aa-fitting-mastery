"""Doctrine management views for the mastery app."""

from allianceauth.authentication.decorators import permissions_required
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from .common import (
    Doctrine,
    DoctrineSkillSetGroupMap,
    Fitting,
    FittingSkillsetMap,
    MASTERY_LEVEL_CHOICES,
    _build_actor_display,
    _build_fitting_skills_ajax_response,
    _get_approval_status_badge_class,
    _get_approval_status_label,
    _get_doctrine_and_map_for_fitting,
    _get_mastery_label,
    _get_user_display,
    _is_ajax_request,
    _parse_mastery_level,
    doctrine_map_service,
    fitting_map_service,
)


@login_required
@permissions_required('mastery.manage_fittings')
def doctrine_list_view(request):
    """Render doctrine overview with initialization/configuration status per doctrine."""
    doctrines = Doctrine.objects.prefetch_related("fittings")

    data = []

    for doctrine in doctrines:
        fittings = doctrine.fittings.all()
        total = fittings.count()

        doctrine_map = DoctrineSkillSetGroupMap.objects.filter(doctrine=doctrine).first()
        initialized = doctrine_map is not None
        configured = (
            0 if doctrine_map is None
            else FittingSkillsetMap.objects.filter(doctrine_map=doctrine_map).count()
        )

        data.append(
            {
                "id": doctrine.pk,
                "name": doctrine.name,
                "initialized": initialized,
                "total": total,
                "configured": configured,
                "icon_url": doctrine.icon_url,
                "priority": 0 if doctrine_map is None else int(getattr(doctrine_map, "priority", 0) or 0),
                "default_mastery_level": None if doctrine_map is None else doctrine_map.default_mastery_level,
                "default_mastery_label": (
                    None if doctrine_map is None
                    else _get_mastery_label(doctrine_map.default_mastery_level)
                ),
            }
        )

    return render(
        request,
        "mastery/doctrine_list.html",
        {
            "doctrines": data,
        },
    )


@login_required
@permissions_required('mastery.manage_fittings')
def doctrine_detail_view(request, doctrine_id):
    """Render one doctrine details and effective mastery level for each fitting."""
    doctrine = Doctrine.objects.prefetch_related("fittings").get(id=doctrine_id)
    doctrine_map = DoctrineSkillSetGroupMap.objects.filter(doctrine=doctrine).first()
    fittings_data = []

    for fitting in doctrine.fittings.all():
        fitting_map = FittingSkillsetMap.objects.select_related(
            "approved_by", "modified_by"
        ).filter(fitting=fitting).first()
        override_level = None if fitting_map is None else fitting_map.mastery_level
        doctrine_default_level = doctrine_map.default_mastery_level if doctrine_map else 4
        effective_level = override_level if override_level is not None else doctrine_default_level
        effective_level = int(effective_level or 4)
        approval_status = (
            fitting_map.status if fitting_map and fitting_map.status
            else FittingSkillsetMap.ApprovalStatus.NOT_APPROVED
        )

        fittings_data.append(
            {
                "id": fitting.id,
                "name": fitting.name,
                "ship_type_id": fitting.ship_type_type_id,
                "ship_name": fitting.ship_type.name,
                "configured": fitting_map is not None,
                "mastery_override": override_level,
                "effective_mastery_level": effective_level,
                "effective_mastery_label": _get_mastery_label(effective_level),
                "priority": 0 if fitting_map is None else int(getattr(fitting_map, "priority", 0) or 0),
                "approval_status": approval_status,
                "approval_status_label": _get_approval_status_label(approval_status),
                "approval_status_badge_class": _get_approval_status_badge_class(approval_status),
                "approved_by_display": _get_user_display(None if fitting_map is None else fitting_map.approved_by),
                "approved_by_actor": _build_actor_display(None if fitting_map is None else fitting_map.approved_by),
                "approved_at": None if fitting_map is None else fitting_map.approved_at,
                "modified_by_display": _get_user_display(None if fitting_map is None else fitting_map.modified_by),
                "modified_by_actor": _build_actor_display(None if fitting_map is None else fitting_map.modified_by),
                "modified_at": None if fitting_map is None else fitting_map.modified_at,
            }
        )

    fittings_data.sort(key=lambda item: (-int(item["priority"] or 0), item["name"].lower()))
    doctrine_default = 4 if doctrine_map is None else doctrine_map.default_mastery_level
    doctrine_priority = 0 if doctrine_map is None else int(getattr(doctrine_map, "priority", 0) or 0)
    return render(
        request,
        "mastery/doctrine_detail.html",
        {
            "doctrine": doctrine,
            "doctrine_map": doctrine_map,
            "doctrine_default_mastery_level": doctrine_default,
            "doctrine_default_mastery_label": _get_mastery_label(doctrine_default),
            "doctrine_priority": doctrine_priority,
            "mastery_choices": MASTERY_LEVEL_CHOICES,
            "fittings": fittings_data,
        },
    )


@login_required
@permissions_required('mastery.manage_fittings')
def generate_doctrine(_request, doctrine_id):  # pylint: disable=unused-argument
    """Ensure doctrine mapping exists, then redirect to doctrine details."""
    doctrine = Doctrine.objects.get(id=doctrine_id)
    has_map = DoctrineSkillSetGroupMap.objects.filter(doctrine=doctrine).exists()

    if not has_map:
        doctrine_map_service.create_doctrine_map(doctrine)

    return redirect('mastery:doctrine_detail', doctrine_id=doctrine_id)


@login_required
@permissions_required('mastery.manage_fittings')
def sync_doctrine(request, doctrine_id):
    """Force doctrine skill synchronization, then redirect to details page."""
    doctrine = Doctrine.objects.get(id=doctrine_id)
    doctrine_map_service.sync(
        doctrine,
        modified_by=request.user,
        status=FittingSkillsetMap.ApprovalStatus.IN_PROGRESS,
    )

    return redirect('mastery:doctrine_detail', doctrine_id=doctrine_id)


@login_required
@permissions_required('mastery.manage_fittings')
def update_doctrine_priority(request, doctrine_id):
    """Update the doctrine training priority (0–10)."""
    if request.method != "POST":
        return HttpResponseBadRequest(_("POST required"))

    doctrine = get_object_or_404(Doctrine, id=doctrine_id)
    doctrine_map = DoctrineSkillSetGroupMap.objects.filter(doctrine=doctrine).first()

    if doctrine_map is None:
        doctrine_map = doctrine_map_service.create_doctrine_map(doctrine)

    try:
        raw = request.POST.get("priority", "0")
        priority = int(raw)
        if priority < 0 or priority > 10:
            raise ValueError(_("Priority must be between 0 and 10."))
    except (TypeError, ValueError) as ex:
        return HttpResponseBadRequest(str(ex))

    doctrine_map.priority = priority
    doctrine_map.save(update_fields=["priority"])

    messages.success(request, _("Doctrine priority updated"))
    return redirect('mastery:doctrine_detail', doctrine_id=doctrine_id)


@login_required
@permissions_required('mastery.manage_fittings')
def update_fitting_priority(request, fitting_id):
    """Update the fitting training priority (0–10)."""
    if request.method != "POST":
        return HttpResponseBadRequest(_("POST required"))

    fitting = get_object_or_404(Fitting.objects.select_related("ship_type"), id=fitting_id)
    doctrine_id = request.POST.get("doctrine_id")
    next_url = request.POST.get("next")

    doctrine = None
    doctrine_map = None
    fitting_map = None

    if doctrine_id:
        doctrine = get_object_or_404(Doctrine, id=doctrine_id)
        doctrine_map = DoctrineSkillSetGroupMap.objects.filter(doctrine=doctrine).first()
        fitting_map = FittingSkillsetMap.objects.select_related(
            "skillset", "doctrine_map", "approved_by", "modified_by"
        ).filter(fitting_id=fitting_id).first()
    else:
        fitting, doctrine, doctrine_map, fitting_map = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return HttpResponseBadRequest(_("No doctrine found for fitting"))

    if doctrine_map is None:
        doctrine_map = doctrine_map_service.create_doctrine_map(doctrine)

    if fitting_map is None:
        fitting_map = fitting_map_service.create_fitting_map(doctrine_map, fitting)

    try:
        raw = request.POST.get("priority", "0")
        priority = int(raw)
        if priority < 0 or priority > 10:
            raise ValueError(_("Priority must be between 0 and 10."))
    except (TypeError, ValueError) as ex:
        return HttpResponseBadRequest(str(ex))

    fitting_map.priority = priority
    fitting_map.save(update_fields=["priority"])

    if _is_ajax_request(request):
        return _build_fitting_skills_ajax_response(
            request,
            fitting=fitting,
            doctrine=doctrine,
            doctrine_map=doctrine_map,
            fitting_map=fitting_map,
            message=_("Fitting priority updated"),
        )

    messages.success(request, _("Fitting priority updated"))
    if next_url:
        return redirect(next_url)
    if doctrine_id or doctrine is not None:
        return redirect('mastery:doctrine_detail', doctrine_id=doctrine.id)
    return redirect('mastery:doctrine_list')


@login_required
@permissions_required('mastery.manage_fittings')
def update_doctrine_mastery(request, doctrine_id):
    """Update default doctrine mastery level and resync all doctrine fittings."""
    if request.method != "POST":
        return HttpResponseBadRequest(_("POST required"))

    doctrine = get_object_or_404(Doctrine, id=doctrine_id)
    doctrine_map = DoctrineSkillSetGroupMap.objects.filter(doctrine=doctrine).first()

    if doctrine_map is None:
        doctrine_map = doctrine_map_service.create_doctrine_map(doctrine)

    try:
        doctrine_map.default_mastery_level = _parse_mastery_level(request.POST.get("mastery_level")) or 4
    except ValueError as ex:
        return HttpResponseBadRequest(str(ex))
    doctrine_map.save(update_fields=["default_mastery_level"])

    doctrine_map_service.sync(
        doctrine,
        modified_by=request.user,
        status=FittingSkillsetMap.ApprovalStatus.IN_PROGRESS,
    )

    return redirect('mastery:doctrine_detail', doctrine_id=doctrine_id)
