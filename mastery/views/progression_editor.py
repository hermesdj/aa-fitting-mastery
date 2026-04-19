"""Views for progression editor (manage_fittings permission required)."""
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_http_methods
from django.http import HttpResponseBadRequest
from django.db import models
from memberaudit.models import SkillSetGroup

from mastery.models import SkillPlanProgression, SkillPlanProgressionStep
from mastery.services.progressions import SkillPlanProgressionService


@login_required
@permission_required("mastery.manage_fittings", raise_exception=True)
def progression_editor_list_view(request):
    """Display all progressions for editing."""
    progressions = SkillPlanProgression.objects.prefetch_related(
        "steps"
    ).order_by("order", "name")

    context = {
        "progressions": progressions,
    }
    return render(request, "mastery/progression/editor/progression_list.html", context)


@login_required
@permission_required("mastery.manage_fittings", raise_exception=True)
def progression_editor_create_view(request):
    """Create a new progression."""
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        order = request.POST.get("order", "0")

        if not name:
            return HttpResponseBadRequest("Name is required")

        try:
            order = int(order)
        except (ValueError, TypeError):
            order = 0

        progression = SkillPlanProgression.objects.create(
            name=name,
            description=description,
            order=order,
        )
        return redirect("mastery:progression_editor_detail", progression_id=progression.id)

    context = {}
    return render(request, "mastery/progression/editor/progression_form.html", context)


@login_required
@permission_required("mastery.manage_fittings", raise_exception=True)
def progression_editor_update_view(request, progression_id):
    """Update an existing progression."""
    progression = get_object_or_404(SkillPlanProgression, id=progression_id)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        order = request.POST.get("order", str(progression.order))
        is_active = request.POST.get("is_active", "off") == "on"

        if not name:
            return HttpResponseBadRequest("Name is required")

        try:
            order = int(order)
        except (ValueError, TypeError):
            order = progression.order

        progression.name = name
        progression.description = description
        progression.order = order
        progression.is_active = is_active
        progression.save()

        return redirect("mastery:progression_editor_detail", progression_id=progression.id)

    context = {
        "progression": progression,
        "edit_mode": True,
    }
    return render(request, "mastery/progression/editor/progression_form.html", context)


@login_required
@permission_required("mastery.manage_fittings", raise_exception=True)
@require_http_methods(["POST"])
def progression_editor_delete_view(request, progression_id):
    """Delete a progression."""
    progression = get_object_or_404(SkillPlanProgression, id=progression_id)
    progression.delete()
    return redirect("mastery:progression_editor_list")


@login_required
@permission_required("mastery.manage_fittings", raise_exception=True)
def progression_editor_detail_view(request, progression_id):
    """Show progression editor with steps management."""
    progression = get_object_or_404(
        SkillPlanProgression.objects.prefetch_related("steps"),
        id=progression_id,
    )

    context = {
        "progression": progression,
        "skillset_groups": SkillSetGroup.objects.all().order_by("name"),
    }
    return render(request, "mastery/progression/editor/progression_detail.html", context)


@login_required
@permission_required("mastery.manage_fittings", raise_exception=True)
def progression_step_add_view(request, progression_id):
    """Add a new step to a progression."""
    progression = get_object_or_404(SkillPlanProgression, id=progression_id)

    if request.method == "POST":
        skillset_group_id = request.POST.get("skillset_group_id")
        step_number = request.POST.get("step_number", "").strip()
        description = request.POST.get("description", "").strip()
        is_required = request.POST.get("is_required", "on") == "on"
        branch_key = request.POST.get("branch_key", "").strip() or None

        if not skillset_group_id or not step_number:
            return HttpResponseBadRequest("Skillset group and step number are required")

        try:
            skillset_group = SkillSetGroup.objects.get(id=int(skillset_group_id))
        except (SkillSetGroup.DoesNotExist, ValueError, TypeError):
            return HttpResponseBadRequest("Invalid skillset group")

        # Calculate the next order
        max_order = progression.steps.aggregate(
            models.Max("order")
        )["order__max"]
        next_order = (max_order or -1) + 1

        SkillPlanProgressionStep.objects.create(
            progression=progression,
            skillset_group=skillset_group,
            step_number=step_number,
            description=description,
            is_required=is_required,
            branch_key=branch_key,
            order=next_order,
        )

        return redirect(
            "mastery:progression_editor_detail",
            progression_id=progression.id,
        )

    context = {
        "progression": progression,
        "skillset_groups": SkillSetGroup.objects.all().order_by("name"),
    }
    return render(request, "mastery/progression/editor/step_form.html", context)


@login_required
@permission_required("mastery.manage_fittings", raise_exception=True)
def progression_step_update_view(request, progression_id, step_id):
    """Update an existing progression step."""
    progression = get_object_or_404(SkillPlanProgression, id=progression_id)
    step = get_object_or_404(SkillPlanProgressionStep, id=step_id, progression=progression)

    if request.method == "POST":
        skillset_group_id = request.POST.get("skillset_group_id")
        step_number = request.POST.get("step_number", "").strip()
        description = request.POST.get("description", "").strip()
        is_required = request.POST.get("is_required", "off") == "on"
        branch_key = request.POST.get("branch_key", "").strip() or None

        if not skillset_group_id or not step_number:
            return HttpResponseBadRequest("Skillset group and step number are required")

        try:
            skillset_group = SkillSetGroup.objects.get(id=int(skillset_group_id))
        except (SkillSetGroup.DoesNotExist, ValueError, TypeError):
            return HttpResponseBadRequest("Invalid skillset group")

        step.skillset_group = skillset_group
        step.step_number = step_number
        step.description = description
        step.is_required = is_required
        step.branch_key = branch_key
        step.save()

        return redirect(
            "mastery:progression_editor_detail",
            progression_id=progression.id,
        )

    context = {
        "progression": progression,
        "step": step,
        "skillset_groups": SkillSetGroup.objects.all().order_by("name"),
        "edit_mode": True,
    }
    return render(request, "mastery/progression/editor/step_form.html", context)


@login_required
@permission_required("mastery.manage_fittings", raise_exception=True)
@require_http_methods(["POST"])
def progression_step_delete_view(request, progression_id, step_id):
    """Delete a progression step."""
    progression = get_object_or_404(SkillPlanProgression, id=progression_id)
    step = get_object_or_404(SkillPlanProgressionStep, id=step_id, progression=progression)
    step.delete()

    return redirect(
        "mastery:progression_editor_detail",
        progression_id=progression.id,
    )


@login_required
@permission_required("mastery.manage_fittings", raise_exception=True)
@require_http_methods(["POST"])
def progression_step_reorder_view(request, progression_id):
    """Reorder steps within a progression."""
    progression = get_object_or_404(SkillPlanProgression, id=progression_id)
    step_order = request.POST.getlist("step_ids[]")

    if not step_order:
        return HttpResponseBadRequest("No steps provided")

    try:
        step_ids = [int(sid) for sid in step_order]
        SkillPlanProgressionService.reorder_progression_steps(progression_id, step_ids)
    except (ValueError, TypeError):
        return HttpResponseBadRequest("Invalid step IDs")

    return redirect(
        "mastery:progression_editor_detail",
        progression_id=progression.id,
    )
