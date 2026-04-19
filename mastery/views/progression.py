"""Views for skill plan progressions (read-only, accessible to basic_access)."""
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render, get_object_or_404

from mastery.models import SkillPlanProgression
from mastery.services.progressions import SkillPlanProgressionService


@login_required
@permission_required("mastery.basic_access", raise_exception=True)
def progression_list_view(request):
    """Display all active skill learning progressions."""
    progressions_state = SkillPlanProgressionService.bulk_get_user_progressions(
        request.user
    )

    context = {
        "progressions_state": progressions_state,
    }
    return render(request, "mastery/progression/progression_list.html", context)


@login_required
@permission_required("mastery.basic_access", raise_exception=True)
def progression_detail_view(request, progression_id):
    """Display a single progression with the user's progress."""
    progression = get_object_or_404(
        SkillPlanProgression.objects.prefetch_related("steps"),
        id=progression_id,
        is_active=True,
    )

    progression_state = SkillPlanProgressionService.calculate_user_progression_state(
        request.user, progression
    )

    context = {
        "progression": progression,
        "progression_state": progression_state,
    }
    return render(request, "mastery/progression/progression_detail.html", context)
