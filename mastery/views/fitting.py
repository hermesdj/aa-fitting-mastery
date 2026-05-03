"""Fitting management views (skill editor, preview, suggestions)."""
from allianceauth.authentication.decorators import permissions_required
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from .common import (
    Doctrine,
    DoctrineSkillSetGroupMap,
    Fitting,
    FittingSkillsetMap,
    ItemType,
    _apply_preview_suggestions,
    _bad_request_response,
    _build_fitting_preview_context,
    _build_fitting_skills_ajax_response,
    _finalize_fitting_skills_action,
    _get_doctrine_and_map_for_fitting,
    _is_ajax_request,
    _parse_mastery_level,
    _parse_posted_int,
    control_service,
    doctrine_map_service,
    doctrine_skill_service,
    extractor_service,
    fitting_map_service,
)
from .deps import approval_service


def _resolve_fitting_context(
    request,
    fitting_id: int,
    *,
    create_doctrine_map: bool = True,
    missing_map_message: str | None = None,
):
    """Load fitting/doctrine/context once and handle common error responses."""
    fitting, doctrine, doctrine_map, fitting_map = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return None, _bad_request_response(request, _("No doctrine found for fitting"))

    if doctrine_map is None:
        if not create_doctrine_map:
            return None, _bad_request_response(request, missing_map_message or _("No doctrine map found for fitting"))
        doctrine_map = doctrine_map_service.create_doctrine_map(doctrine)

    return (fitting, doctrine, doctrine_map, fitting_map), None


def _regenerate_fitting_plan(doctrine_map, fitting, user):
    """Regenerate one fitting skillset with standard modified metadata."""
    doctrine_skill_service.generate_for_fitting(
        doctrine_map,
        fitting,
        modified_by=user,
        status=FittingSkillsetMap.ApprovalStatus.IN_PROGRESS,
    )


def _alpha_conversion_adjustments(skill_rows: list[dict]) -> tuple[bool, list[tuple[int, int]]]:
    """Return convertibility and per-skill target levels for Alpha conversion."""
    adjustments: list[tuple[int, int]] = []
    for row in skill_rows:
        if row.get("is_blacklisted"):
            continue

        if bool(row.get("required_requires_omega")):
            return False, []

        skill_type_id = int(row.get("skill_type_id", 0) or 0)
        recommended_level = int(row.get("recommended_level", 0) or 0)
        max_alpha_level = int(row.get("max_alpha_level", 0) or 0)
        if skill_type_id <= 0:
            continue

        if recommended_level > max_alpha_level:
            adjustments.append((skill_type_id, max_alpha_level))

    return True, adjustments


def _require_post_and_resolve(
    request,
    fitting_id: int,
    *,
    create_doctrine_map: bool = True,
    missing_map_message: str | None = None,
):
    """Common POST + context resolution helper.

    Returns (resolved, error_response) where resolved is the tuple
    (fitting, doctrine, doctrine_map, fitting_map) or None on error.
    """
    if request.method != "POST":
        return None, _bad_request_response(request, _("POST required"))

    return _resolve_fitting_context(
        request,
        fitting_id,
        create_doctrine_map=create_doctrine_map,
        missing_map_message=missing_map_message,
    )


@login_required
@permissions_required('mastery.manage_fittings')
def fitting_skills_view(request, fitting_id):
    """Fitting skills view."""
    fitting, doctrine, doctrine_map, fitting_map = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return HttpResponseBadRequest(_("No doctrine found for fitting"))

    if doctrine_map is None:
        doctrine_map = doctrine_map_service.create_doctrine_map(doctrine)
        fitting_map = FittingSkillsetMap.objects.filter(fitting_id=fitting_id).first()

    context = _build_fitting_preview_context(
        fitting=fitting,
        doctrine_map=doctrine_map,
        fitting_map=fitting_map,
    )
    context["doctrine"] = doctrine

    return render(request, "mastery/fitting_skills.html", context)


@login_required
@permissions_required('mastery.manage_fittings')
def update_fitting_mastery(request, fitting_id):
    """Update fitting mastery."""
    if request.method != "POST":
        return _bad_request_response(request, _("POST required"))

    doctrine_id = request.POST.get("doctrine_id")
    doctrine = get_object_or_404(Doctrine, id=doctrine_id)
    fitting = get_object_or_404(Fitting, id=fitting_id)
    doctrine_map = DoctrineSkillSetGroupMap.objects.filter(doctrine=doctrine).first()

    if doctrine_map is None:
        doctrine_map = doctrine_map_service.create_doctrine_map(doctrine)

    fitting_map = fitting_map_service.create_fitting_map(doctrine_map, fitting)
    try:
        fitting_map.mastery_level = _parse_mastery_level(request.POST.get("mastery_level"))
    except ValueError as ex:
        return _bad_request_response(request, str(ex))
    fitting_map.save(update_fields=["mastery_level"])

    doctrine_skill_service.generate_for_fitting(
        doctrine_map,
        fitting,
        modified_by=request.user,
        status=FittingSkillsetMap.ApprovalStatus.IN_PROGRESS,
    )

    if _is_ajax_request(request):
        return _build_fitting_skills_ajax_response(
            request,
            fitting=fitting,
            doctrine=doctrine,
            doctrine_map=doctrine_map,
            fitting_map=fitting_map,
            message=_("Mastery updated"),
        )

    next_url = request.POST.get("next")
    if next_url:
        messages.success(request, _("Mastery updated"))
        return redirect(next_url)

    messages.success(request, _("Mastery updated"))
    return redirect('mastery:doctrine_detail', doctrine_id=doctrine_id)


@login_required
@permissions_required('mastery.manage_fittings')
def toggle_skill_blacklist_view(request, fitting_id):
    """Toggle skill blacklist view."""
    try:
        skill_type_id = _parse_posted_int(request.POST.get("skill_type_id"), "skill_type_id")
    except ValueError as ex:
        return _bad_request_response(request, str(ex))
    resolved, error_response = _require_post_and_resolve(request, fitting_id)
    if error_response:
        return error_response
    fitting, doctrine, doctrine_map, _unused = resolved

    should_blacklist = request.POST.get("value")

    if should_blacklist in ("true", "false"):
        value = should_blacklist == "true"
    else:
        current_blacklist = control_service.get_blacklist(fitting_id)
        value = skill_type_id not in current_blacklist

    control_service.set_blacklist(fitting_id=fitting_id, skill_type_id=skill_type_id, value=value)
    _regenerate_fitting_plan(doctrine_map, fitting, request.user)

    return _finalize_fitting_skills_action(
        request,
        fitting=fitting,
        doctrine=doctrine,
        doctrine_map=doctrine_map,
        message=_("Skill blacklist updated"),
    )


@login_required
@permissions_required('mastery.manage_fittings')
def update_skill_recommended_view(request, fitting_id):
    """Update skill recommended view."""
    try:
        skill_type_id = _parse_posted_int(request.POST.get("skill_type_id"), "skill_type_id")
    except ValueError as ex:
        return _bad_request_response(request, str(ex))
    raw_level = request.POST.get("recommended_level")
    try:
        level = None if raw_level in (None, "") else _parse_posted_int(raw_level, "recommended_level")
    except ValueError as ex:
        return _bad_request_response(request, str(ex))

    if level is not None and level not in range(0, 6):
        return _bad_request_response(request, _("recommended_level must be between 0 and 5"))

    resolved, error_response = _require_post_and_resolve(request, fitting_id)
    if error_response:
        return error_response
    fitting, doctrine, doctrine_map, _unused = resolved

    required_by_skill = extractor_service.get_required_skills_for_fitting(fitting)
    required_level = int(required_by_skill.get(skill_type_id, 0) or 0)
    if level is not None and level < required_level:
        return _bad_request_response(
            request,
            _("recommended_level cannot be lower than required level (%(level)s)") % {"level": required_level},
        )

    control_service.set_recommended_level(
        fitting_id=fitting_id,
        skill_type_id=skill_type_id,
        level=level,
    )
    _regenerate_fitting_plan(doctrine_map, fitting, request.user)

    return _finalize_fitting_skills_action(
        request,
        fitting=fitting,
        doctrine=doctrine,
        doctrine_map=doctrine_map,
        message=_("Recommended level updated"),
    )


@login_required
@permissions_required('mastery.manage_fittings')
def update_skill_group_controls_view(request, fitting_id):
    """Update skill group controls view."""
    try:
        skill_type_ids = [
            _parse_posted_int(skill_type_id, "skill_type_ids")
            for skill_type_id in request.POST.getlist("skill_type_ids")
            if skill_type_id not in (None, "")
        ]
    except ValueError as ex:
        return _bad_request_response(request, str(ex))

    if not skill_type_ids:
        return _bad_request_response(request, _("No skills provided"))

    action = request.POST.get("action")
    resolved, error_response = _require_post_and_resolve(request, fitting_id)
    if error_response:
        return error_response
    fitting, doctrine, doctrine_map, _unused = resolved

    if action == "blacklist_group":
        control_service.set_blacklist_batch(fitting_id=fitting_id, skill_type_ids=skill_type_ids, value=True)
        message = _("Skill group blacklisted")
    elif action == "unblacklist_group":
        control_service.set_blacklist_batch(fitting_id=fitting_id, skill_type_ids=skill_type_ids, value=False)
        message = _("Skill group unblacklisted")
    elif action in {"set_group_recommended", "clear_group_recommended"}:
        level = None
        message = _("Group recommended level cleared")
        if action == "set_group_recommended":
            raw_level = request.POST.get("recommended_level")
            if raw_level not in (None, ""):
                try:
                    level = _parse_posted_int(raw_level, "recommended_level")
                except ValueError as ex:
                    return _bad_request_response(request, str(ex))
                if level not in range(0, 6):
                    return _bad_request_response(request, _("recommended_level must be between 0 and 5"))

                required_by_skill = extractor_service.get_required_skills_for_fitting(fitting)
                invalid_skill_ids = [
                    skill_type_id
                    for skill_type_id in skill_type_ids
                    if level < int(required_by_skill.get(skill_type_id, 0) or 0)
                ]
                if invalid_skill_ids:
                    return _bad_request_response(
                        request,
                        _("recommended_level cannot be lower than required level for one or more selected skills"),
                    )
                message = _("Group recommended level updated")

        control_service.set_recommended_level_batch(
            fitting_id=fitting_id,
            skill_type_ids=skill_type_ids,
            level=level,
        )
    else:
        return _bad_request_response(request, _("Unsupported action"))

    _regenerate_fitting_plan(doctrine_map, fitting, request.user)

    return _finalize_fitting_skills_action(
        request,
        fitting=fitting,
        doctrine=doctrine,
        doctrine_map=doctrine_map,
        message=message,
    )


@login_required
@permissions_required('mastery.manage_fittings')
def add_manual_skill_view(request, fitting_id):
    """Add manual skill view."""
    skill_name = (request.POST.get("skill_name") or "").strip()
    if not skill_name:
        return _bad_request_response(request, _("skill_name is required"))

    try:
        recommended_level = _parse_posted_int(request.POST.get("recommended_level"), "recommended_level")
    except ValueError as ex:
        return _bad_request_response(request, str(ex))

    if recommended_level not in range(0, 6):
        return _bad_request_response(request, _("recommended_level must be between 0 and 5"))

    resolved, error_response = _require_post_and_resolve(request, fitting_id)
    if error_response:
        return error_response
    fitting, doctrine, doctrine_map, _unused = resolved

    skill = ItemType.objects.filter(
        name__iexact=skill_name,
        group__category__name__iexact="Skill",
    ).first()
    if skill is None:
        return _bad_request_response(request, _("Skill not found: %(skill_name)s") % {"skill_name": skill_name})

    control_service.add_manual_skill(
        fitting_id=fitting_id,
        skill_type_id=skill.id,
        level=recommended_level,
    )

    _regenerate_fitting_plan(doctrine_map, fitting, request.user)

    return _finalize_fitting_skills_action(
        request,
        fitting=fitting,
        doctrine=doctrine,
        doctrine_map=doctrine_map,
        message=_("Manual skill added"),
    )


@login_required
@permissions_required('mastery.manage_fittings')
def remove_manual_skill_view(request, fitting_id):
    """Remove manual skill view."""
    try:
        skill_type_id = _parse_posted_int(request.POST.get("skill_type_id"), "skill_type_id")
    except ValueError as ex:
        return _bad_request_response(request, str(ex))

    resolved, error_response = _require_post_and_resolve(request, fitting_id)
    if error_response:
        return error_response
    fitting, doctrine, doctrine_map, _unused = resolved

    control_service.remove_manual_skill(fitting_id=fitting_id, skill_type_id=skill_type_id)
    _regenerate_fitting_plan(doctrine_map, fitting, request.user)

    return _finalize_fitting_skills_action(
        request,
        fitting=fitting,
        doctrine=doctrine,
        doctrine_map=doctrine_map,
        message=_("Manual skill removed"),
    )


@login_required
@permissions_required('mastery.manage_fittings')
def apply_suggestions_view(request, fitting_id):
    """Apply suggestions view."""
    resolved, error_response = _require_post_and_resolve(
        request,
        fitting_id,
        create_doctrine_map=False,
        missing_map_message=_("No doctrine map found for fitting"),
    )
    if error_response:
        return error_response
    fitting, doctrine, doctrine_map, _unused = resolved

    applied_count = _apply_preview_suggestions(
        fitting=fitting,
        doctrine_map=doctrine_map,
        modified_by=request.user,
    )
    if applied_count:
        message = ngettext(
            "Applied %(count)d suggestion",
            "Applied %(count)d suggestions",
            applied_count,
        ) % {"count": applied_count}
        message_level = "success"
    else:
        message = _("No pending suggestion to apply")
        message_level = "info"

    return _finalize_fitting_skills_action(
        request,
        fitting=fitting,
        doctrine=doctrine,
        doctrine_map=doctrine_map,
        message=message,
        message_level=message_level,
    )


@login_required
@permissions_required('mastery.manage_fittings')
def apply_group_suggestions_view(request, fitting_id):
    """Apply group suggestions view."""
    resolved, error_response = _require_post_and_resolve(
        request,
        fitting_id,
        create_doctrine_map=False,
        missing_map_message=_("No doctrine map found for fitting"),
    )
    if error_response:
        return error_response
    fitting, doctrine, doctrine_map, _unused = resolved

    try:
        allowed_skill_ids = {
            _parse_posted_int(skill_type_id, "skill_type_ids")
            for skill_type_id in request.POST.getlist("skill_type_ids")
            if skill_type_id not in (None, "")
        }
    except ValueError as ex:
        return _bad_request_response(request, str(ex))

    if not allowed_skill_ids:
        return _bad_request_response(request, _("No skills provided"))

    applied_count = _apply_preview_suggestions(
        fitting=fitting,
        doctrine_map=doctrine_map,
        allowed_skill_ids=allowed_skill_ids,
        modified_by=request.user,
    )
    if applied_count:
        message = ngettext(
            "Applied %(count)d suggestion for this group",
            "Applied %(count)d suggestions for this group",
            applied_count,
        ) % {"count": applied_count}
        message_level = "success"
    else:
        message = _("No pending suggestion in this group")
        message_level = "info"

    return _finalize_fitting_skills_action(
        request,
        fitting=fitting,
        doctrine=doctrine,
        doctrine_map=doctrine_map,
        message=message,
        message_level=message_level,
    )


@login_required
@permissions_required('mastery.manage_fittings')
def apply_skill_suggestion_view(request, fitting_id):
    """Apply skill suggestion view."""
    try:
        skill_type_id = _parse_posted_int(request.POST.get("skill_type_id"), "skill_type_id")
    except ValueError as ex:
        return _bad_request_response(request, str(ex))

    resolved, error_response = _require_post_and_resolve(
        request,
        fitting_id,
        create_doctrine_map=False,
        missing_map_message=_("No doctrine map found for fitting"),
    )
    if error_response:
        return error_response
    fitting, doctrine, doctrine_map, _unused = resolved

    applied_count = _apply_preview_suggestions(
        fitting=fitting,
        doctrine_map=doctrine_map,
        allowed_skill_ids={skill_type_id},
        modified_by=request.user,
    )
    if applied_count:
        message = _("Suggestion applied")
        message_level = "success"
    else:
        message = _("No pending suggestion for this skill")
        message_level = "info"

    return _finalize_fitting_skills_action(
        request,
        fitting=fitting,
        doctrine=doctrine,
        doctrine_map=doctrine_map,
        message=message,
        message_level=message_level,
    )


@login_required
@permissions_required('mastery.manage_fittings')
def make_recommended_plan_alpha_compatible_view(request, fitting_id):
    """Clamp recommended levels to Alpha caps when the required plan allows it."""
    resolved, error_response = _require_post_and_resolve(request, fitting_id)
    if error_response:
        return error_response
    fitting, doctrine, doctrine_map, _unused = resolved

    preview = doctrine_skill_service.preview_fitting(doctrine_map=doctrine_map, fitting=fitting)
    is_convertible, adjustments = _alpha_conversion_adjustments(preview["skills"])
    if not is_convertible:
        return _bad_request_response(
            request,
            _("Recommended plan cannot be made Alpha compatible because at least one required skill needs Omega"),
        )

    if not adjustments:
        return _bad_request_response(request, _("Recommended plan is already Alpha compatible"))

    for skill_type_id, alpha_level in adjustments:
        control_service.set_recommended_level(
            fitting_id=fitting_id,
            skill_type_id=skill_type_id,
            level=alpha_level,
        )

    _regenerate_fitting_plan(doctrine_map, fitting, request.user)
    return _finalize_fitting_skills_action(
        request,
        fitting=fitting,
        doctrine=doctrine,
        doctrine_map=doctrine_map,
        message=_("Recommended plan converted to Alpha compatibility"),
    )


@login_required
@permissions_required('mastery.manage_fittings')
def update_fitting_approval_status_view(request, fitting_id):
    """Update the approval workflow status for one fitting skill plan."""
    resolved, error_response = _require_post_and_resolve(request, fitting_id)
    if error_response:
        return error_response
    fitting, doctrine, doctrine_map, fitting_map = resolved

    if fitting_map is None:
        fitting_map = fitting_map_service.create_fitting_map(doctrine_map, fitting)

    action = request.POST.get("action")
    if action == "approve":
        if not getattr(fitting_map, "last_synced_at", None):
            return _bad_request_response(request, _("Skill plan must be synchronised before it can be approved"))
        approval_service.approve(fitting_map, user=request.user)
        message = _("Skill plan approved")
    elif action == "mark_in_progress":
        approval_service.mark_status(
            fitting_map,
            status=FittingSkillsetMap.ApprovalStatus.IN_PROGRESS,
        )
        message = _("Skill plan marked as in progress")
    elif action == "mark_not_approved":
        approval_service.mark_status(
            fitting_map,
            status=FittingSkillsetMap.ApprovalStatus.NOT_APPROVED,
        )
        message = _("Skill plan marked as not approved")
    else:
        return _bad_request_response(request, _("Unsupported action"))

    return _finalize_fitting_skills_action(
        request,
        fitting=fitting,
        doctrine=doctrine,
        doctrine_map=doctrine_map,
        message=message,
    )


@login_required
@permissions_required('mastery.basic_access')
def fitting_skills_preview_view(request, fitting_id):
    """Fitting skills preview view."""
    fitting, doctrine, doctrine_map, fitting_map = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return HttpResponseBadRequest(_("No doctrine found for fitting"))

    if doctrine_map is None:
        doctrine_map = doctrine_map_service.create_doctrine_map(doctrine)
        fitting_map = FittingSkillsetMap.objects.filter(fitting_id=fitting_id).first()

    is_approved = bool(
        fitting_map
        and getattr(
            fitting_map,
            "status",
            FittingSkillsetMap.ApprovalStatus.NOT_APPROVED,
        )
        == FittingSkillsetMap.ApprovalStatus.APPROVED
    )
    if not is_approved and not request.user.has_perm("mastery.manage_fittings"):
        return HttpResponseBadRequest(_("No approved skillset configured for this fitting yet"))

    try:
        mastery_level = _parse_mastery_level(request.GET.get("mastery_level"))
    except ValueError as ex:
        return HttpResponseBadRequest(str(ex))

    context = _build_fitting_preview_context(
        fitting=fitting,
        doctrine_map=doctrine_map,
        fitting_map=fitting_map,
        mastery_level=mastery_level,
    )

    return render(request, "mastery/partials/fitting_skill_preview.html", context)
