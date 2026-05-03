"""Public views API for the mastery app."""

from .common import (  # re-exported helpers used in tests and by modules
    _build_fitting_skills_ajax_response,
    _get_doctrine_and_map_for_fitting,
    _group_preview_skills,
    _resolve_row_levels,
    extractor_service,
)
from .doctrine import (
    doctrine_detail_view,
    doctrine_list_view,
    generate_doctrine,
    sync_doctrine,
    update_doctrine_mastery,
    update_doctrine_priority,
    update_fitting_priority,
)
from .fitting import (
    add_manual_skill_view,
    apply_group_suggestions_view,
    apply_skill_suggestion_view,
    apply_suggestions_view,
    fitting_skills_preview_view,
    fitting_skills_view,
    make_recommended_plan_alpha_compatible_view,
    remove_manual_skill_view,
    toggle_skill_blacklist_view,
    update_fitting_approval_status_view,
    update_fitting_mastery,
    update_skill_group_controls_view,
    update_skill_recommended_view,
)
from .pilot import (
    index,
    pilot_fitting_detail_view,
    pilot_fitting_skillplan_export_view,
)
from .summary import (
    summary_doctrine_detail_view,
    summary_fitting_detail_view,
    summary_list_view,
    summary_p2_metrics_debug_view,
    summary_settings_view,
)

__all__ = [
    "_build_fitting_skills_ajax_response",
    "_get_doctrine_and_map_for_fitting",
    "_group_preview_skills",
    "_resolve_row_levels",
    "extractor_service",
    "add_manual_skill_view",
    "apply_group_suggestions_view",
    "apply_skill_suggestion_view",
    "apply_suggestions_view",
    "doctrine_detail_view",
    "doctrine_list_view",
    "fitting_skills_preview_view",
    "fitting_skills_view",
    "generate_doctrine",
    "index",
    "make_recommended_plan_alpha_compatible_view",
    "pilot_fitting_detail_view",
    "pilot_fitting_skillplan_export_view",
    "remove_manual_skill_view",
    "summary_doctrine_detail_view",
    "summary_fitting_detail_view",
    "summary_list_view",
    "summary_p2_metrics_debug_view",
    "summary_settings_view",
    "sync_doctrine",
    "toggle_skill_blacklist_view",
    "update_fitting_approval_status_view",
    "update_doctrine_mastery",
    "update_doctrine_priority",
    "update_fitting_mastery",
    "update_fitting_priority",
    "update_skill_group_controls_view",
    "update_skill_recommended_view",
]

