from allianceauth.authentication.decorators import permissions_required
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render

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


@login_required
@permissions_required('mastery.manage_fittings')
def fitting_skills_view(request, fitting_id):
    fitting, doctrine, doctrine_map, fitting_map = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return HttpResponseBadRequest("No doctrine found for fitting")

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
    if request.method != "POST":
        return _bad_request_response(request, "POST required")

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

    doctrine_skill_service.generate_for_fitting(doctrine_map, fitting)

    if _is_ajax_request(request):
        return _build_fitting_skills_ajax_response(
            request,
            fitting=fitting,
            doctrine=doctrine,
            doctrine_map=doctrine_map,
            fitting_map=fitting_map,
            message="Mastery updated",
        )

    next_url = request.POST.get("next")
    if next_url:
        messages.success(request, "Mastery updated")
        return redirect(next_url)

    messages.success(request, "Mastery updated")
    return redirect('mastery:doctrine_detail', doctrine_id=doctrine_id)


@login_required
@permissions_required('mastery.manage_fittings')
def toggle_skill_blacklist_view(request, fitting_id):
    if request.method != "POST":
        return _bad_request_response(request, "POST required")

    try:
        skill_type_id = _parse_posted_int(request.POST.get("skill_type_id"), "skill_type_id")
    except ValueError as ex:
        return _bad_request_response(request, str(ex))
    fitting, doctrine, doctrine_map, _ = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return _bad_request_response(request, "No doctrine found for fitting")

    if doctrine_map is None:
        doctrine_map = doctrine_map_service.create_doctrine_map(doctrine)

    should_blacklist = request.POST.get("value")

    if should_blacklist in ("true", "false"):
        value = should_blacklist == "true"
    else:
        current_blacklist = control_service.get_blacklist(fitting_id)
        value = skill_type_id not in current_blacklist

    control_service.set_blacklist(fitting_id=fitting_id, skill_type_id=skill_type_id, value=value)
    doctrine_skill_service.generate_for_fitting(doctrine_map, fitting)

    return _finalize_fitting_skills_action(
        request,
        fitting=fitting,
        doctrine=doctrine,
        doctrine_map=doctrine_map,
        message="Skill blacklist updated",
    )


@login_required
@permissions_required('mastery.manage_fittings')
def update_skill_recommended_view(request, fitting_id):
    if request.method != "POST":
        return _bad_request_response(request, "POST required")

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
        return _bad_request_response(request, "recommended_level must be between 0 and 5")

    fitting, doctrine, doctrine_map, _ = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return _bad_request_response(request, "No doctrine found for fitting")

    if doctrine_map is None:
        doctrine_map = doctrine_map_service.create_doctrine_map(doctrine)

    required_by_skill = extractor_service.get_required_skills_for_fitting(fitting)
    required_level = int(required_by_skill.get(skill_type_id, 0) or 0)
    if level is not None and level < required_level:
        return _bad_request_response(
            request,
            f"recommended_level cannot be lower than required level ({required_level})",
        )

    control_service.set_recommended_level(
        fitting_id=fitting_id,
        skill_type_id=skill_type_id,
        level=level,
    )
    doctrine_skill_service.generate_for_fitting(doctrine_map, fitting)

    return _finalize_fitting_skills_action(
        request,
        fitting=fitting,
        doctrine=doctrine,
        doctrine_map=doctrine_map,
        message="Recommended level updated",
    )


@login_required
@permissions_required('mastery.manage_fittings')
def update_skill_group_controls_view(request, fitting_id):
    if request.method != "POST":
        return _bad_request_response(request, "POST required")

    try:
        skill_type_ids = [
            _parse_posted_int(skill_type_id, "skill_type_ids")
            for skill_type_id in request.POST.getlist("skill_type_ids")
            if skill_type_id not in (None, "")
        ]
    except ValueError as ex:
        return _bad_request_response(request, str(ex))

    if not skill_type_ids:
        return _bad_request_response(request, "No skills provided")

    action = request.POST.get("action")
    fitting, doctrine, doctrine_map, _ = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return _bad_request_response(request, "No doctrine found for fitting")

    if doctrine_map is None:
        doctrine_map = doctrine_map_service.create_doctrine_map(doctrine)

    if action == "blacklist_group":
        control_service.set_blacklist_batch(fitting_id=fitting_id, skill_type_ids=skill_type_ids, value=True)
        message = "Skill group blacklisted"
    elif action == "unblacklist_group":
        control_service.set_blacklist_batch(fitting_id=fitting_id, skill_type_ids=skill_type_ids, value=False)
        message = "Skill group unblacklisted"
    elif action in {"set_group_recommended", "clear_group_recommended"}:
        level = None
        message = "Group recommended level cleared"
        if action == "set_group_recommended":
            raw_level = request.POST.get("recommended_level")
            if raw_level not in (None, ""):
                try:
                    level = _parse_posted_int(raw_level, "recommended_level")
                except ValueError as ex:
                    return _bad_request_response(request, str(ex))
                if level not in range(0, 6):
                    return _bad_request_response(request, "recommended_level must be between 0 and 5")

                required_by_skill = extractor_service.get_required_skills_for_fitting(fitting)
                invalid_skill_ids = [
                    skill_type_id
                    for skill_type_id in skill_type_ids
                    if level < int(required_by_skill.get(skill_type_id, 0) or 0)
                ]
                if invalid_skill_ids:
                    return _bad_request_response(
                        request,
                        "recommended_level cannot be lower than required level for one or more selected skills",
                    )
                message = "Group recommended level updated"

        control_service.set_recommended_level_batch(
            fitting_id=fitting_id,
            skill_type_ids=skill_type_ids,
            level=level,
        )
    else:
        return _bad_request_response(request, "Unsupported action")

    doctrine_skill_service.generate_for_fitting(doctrine_map, fitting)

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
    if request.method != "POST":
        return _bad_request_response(request, "POST required")

    skill_name = (request.POST.get("skill_name") or "").strip()
    if not skill_name:
        return _bad_request_response(request, "skill_name is required")

    try:
        recommended_level = _parse_posted_int(request.POST.get("recommended_level"), "recommended_level")
    except ValueError as ex:
        return _bad_request_response(request, str(ex))

    if recommended_level not in range(0, 6):
        return _bad_request_response(request, "recommended_level must be between 0 and 5")

    fitting, doctrine, doctrine_map, _ = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return _bad_request_response(request, "No doctrine found for fitting")

    if doctrine_map is None:
        doctrine_map = doctrine_map_service.create_doctrine_map(doctrine)

    skill = ItemType.objects.filter(
        name__iexact=skill_name,
        group__category__name__iexact="Skill",
    ).first()
    if skill is None:
        return _bad_request_response(request, f"Skill not found: {skill_name}")

    control_service.add_manual_skill(
        fitting_id=fitting_id,
        skill_type_id=skill.id,
        level=recommended_level,
    )

    doctrine_skill_service.generate_for_fitting(doctrine_map, fitting)

    return _finalize_fitting_skills_action(
        request,
        fitting=fitting,
        doctrine=doctrine,
        doctrine_map=doctrine_map,
        message="Manual skill added",
    )


@login_required
@permissions_required('mastery.manage_fittings')
def remove_manual_skill_view(request, fitting_id):
    if request.method != "POST":
        return _bad_request_response(request, "POST required")

    try:
        skill_type_id = _parse_posted_int(request.POST.get("skill_type_id"), "skill_type_id")
    except ValueError as ex:
        return _bad_request_response(request, str(ex))

    fitting, doctrine, doctrine_map, _ = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return _bad_request_response(request, "No doctrine found for fitting")

    if doctrine_map is None:
        doctrine_map = doctrine_map_service.create_doctrine_map(doctrine)

    control_service.remove_manual_skill(fitting_id=fitting_id, skill_type_id=skill_type_id)
    doctrine_skill_service.generate_for_fitting(doctrine_map, fitting)

    return _finalize_fitting_skills_action(
        request,
        fitting=fitting,
        doctrine=doctrine,
        doctrine_map=doctrine_map,
        message="Manual skill removed",
    )


@login_required
@permissions_required('mastery.manage_fittings')
def apply_suggestions_view(request, fitting_id):
    if request.method != "POST":
        return _bad_request_response(request, "POST required")

    fitting, doctrine, doctrine_map, _ = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return _bad_request_response(request, "No doctrine found for fitting")

    if doctrine_map is None:
        return _bad_request_response(request, "No doctrine map found for fitting")

    applied_count = _apply_preview_suggestions(fitting=fitting, doctrine_map=doctrine_map)
    if applied_count:
        message = f"Applied {applied_count} suggestion(s)"
        message_level = "success"
    else:
        message = "No pending suggestion to apply"
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
    if request.method != "POST":
        return _bad_request_response(request, "POST required")

    fitting, doctrine, doctrine_map, _ = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return _bad_request_response(request, "No doctrine found for fitting")

    if doctrine_map is None:
        return _bad_request_response(request, "No doctrine map found for fitting")

    try:
        allowed_skill_ids = {
            _parse_posted_int(skill_type_id, "skill_type_ids")
            for skill_type_id in request.POST.getlist("skill_type_ids")
            if skill_type_id not in (None, "")
        }
    except ValueError as ex:
        return _bad_request_response(request, str(ex))

    if not allowed_skill_ids:
        return _bad_request_response(request, "No skills provided")

    applied_count = _apply_preview_suggestions(
        fitting=fitting,
        doctrine_map=doctrine_map,
        allowed_skill_ids=allowed_skill_ids,
    )
    if applied_count:
        message = f"Applied {applied_count} suggestion(s) for this group"
        message_level = "success"
    else:
        message = "No pending suggestion in this group"
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
    if request.method != "POST":
        return _bad_request_response(request, "POST required")

    try:
        skill_type_id = _parse_posted_int(request.POST.get("skill_type_id"), "skill_type_id")
    except ValueError as ex:
        return _bad_request_response(request, str(ex))

    fitting, doctrine, doctrine_map, _ = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return _bad_request_response(request, "No doctrine found for fitting")

    if doctrine_map is None:
        return _bad_request_response(request, "No doctrine map found for fitting")

    applied_count = _apply_preview_suggestions(
        fitting=fitting,
        doctrine_map=doctrine_map,
        allowed_skill_ids={skill_type_id},
    )
    if applied_count:
        message = "Suggestion applied"
        message_level = "success"
    else:
        message = "No pending suggestion for this skill"
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
def fitting_skills_preview_view(request, fitting_id):
    fitting, doctrine, doctrine_map, fitting_map = _get_doctrine_and_map_for_fitting(fitting_id)

    if doctrine is None:
        return HttpResponseBadRequest("No doctrine found for fitting")

    if doctrine_map is None:
        doctrine_map = doctrine_map_service.create_doctrine_map(doctrine)
        fitting_map = FittingSkillsetMap.objects.filter(fitting_id=fitting_id).first()

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

