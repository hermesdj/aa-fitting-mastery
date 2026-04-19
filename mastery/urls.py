"""URL configuration for the Fitting Mastery app."""

from django.urls import path

from . import views

app_name = "mastery"  # pylint: disable=invalid-name

urlpatterns = [
    # UI
    # Pilots Access
    path("", views.index, name="pilot_index"),
    path(
        "pilot/fittings/<int:fitting_id>/",
        views.pilot_fitting_detail_view,
        name="pilot_fitting_detail",
    ),
    path(
        "pilot/fittings/<int:fitting_id>/skill-plan.txt",
        views.pilot_fitting_skillplan_export_view,
        name="pilot_fitting_skillplan_export",
    ),
    # Progressions (read-only)
    path("progressions/", views.progression_list_view, name="progression_list"),
    path(
        "progressions/<int:progression_id>/",
        views.progression_detail_view,
        name="progression_detail",
    ),
    # Progressions (editor)
    path(
        "progressions/editor/",
        views.progression_editor_list_view,
        name="progression_editor_list",
    ),
    path(
        "progressions/editor/create/",
        views.progression_editor_create_view,
        name="progression_editor_create",
    ),
    path(
        "progressions/editor/<int:progression_id>/",
        views.progression_editor_detail_view,
        name="progression_editor_detail",
    ),
    path(
        "progressions/editor/<int:progression_id>/update/",
        views.progression_editor_update_view,
        name="progression_editor_update",
    ),
    path(
        "progressions/editor/<int:progression_id>/delete/",
        views.progression_editor_delete_view,
        name="progression_editor_delete",
    ),
    path(
        "progressions/editor/<int:progression_id>/steps/create/",
        views.progression_step_add_view,
        name="progression_step_create",
    ),
    path(
        "progressions/editor/<int:progression_id>/steps/<int:step_id>/update/",
        views.progression_step_update_view,
        name="progression_step_update",
    ),
    path(
        "progressions/editor/<int:progression_id>/steps/<int:step_id>/delete/",
        views.progression_step_delete_view,
        name="progression_step_delete",
    ),
    path(
        "progressions/editor/<int:progression_id>/steps/reorder/",
        views.progression_step_reorder_view,
        name="progression_step_reorder",
    ),
    # Summaries
    path("summaries/", views.summary_list_view, name="summary_list"),
    path("summaries/doctrine/<int:doctrine_id>/", views.summary_doctrine_detail_view, name="summary_doctrine_detail"),
    path("summaries/fitting/<int:fitting_id>/", views.summary_fitting_detail_view, name="summary_fitting_detail"),
    path("summaries/settings/", views.summary_settings_view, name="summary_settings"),
    # Doctrine Management
    path("doctrines/", views.doctrine_list_view, name="doctrine_list"),
    path("doctrines/<int:doctrine_id>/", views.doctrine_detail_view, name="doctrine_detail"),
    path("doctrines/<int:doctrine_id>/generate/", views.generate_doctrine, name="generate_doctrine"),
    path("doctrines/<int:doctrine_id>/sync/", views.sync_doctrine, name="sync_doctrine"),
    path("doctrines/<int:doctrine_id>/mastery/", views.update_doctrine_mastery, name="update_doctrine_mastery"),

    # Fittings
    path("fitting/<int:fitting_id>/skills/", views.fitting_skills_view, name="fitting_skills"),
    path("fitting/<int:fitting_id>/skills/preview/", views.fitting_skills_preview_view, name="fitting_skills_preview"),
    path(
        "fitting/<int:fitting_id>/skills/apply-suggestions/",
        views.apply_suggestions_view,
        name="apply_suggestions",
    ),
    path(
        "fitting/<int:fitting_id>/skills/apply-group-suggestions/",
        views.apply_group_suggestions_view,
        name="apply_group_suggestions",
    ),
    path(
        "fitting/<int:fitting_id>/skills/apply-skill-suggestion/",
        views.apply_skill_suggestion_view,
        name="apply_skill_suggestion",
    ),
    path(
        "fitting/<int:fitting_id>/skills/approval/",
        views.update_fitting_approval_status_view,
        name="update_fitting_approval_status",
    ),
    path("fitting/<int:fitting_id>/skills/add-manual/", views.add_manual_skill_view, name="add_manual_skill"),
    path("fitting/<int:fitting_id>/skills/remove-manual/", views.remove_manual_skill_view, name="remove_manual_skill"),
    path(
        "fitting/<int:fitting_id>/skills/recommended/",
        views.update_skill_recommended_view,
        name="update_skill_recommended",
    ),
    path(
        "fitting/<int:fitting_id>/skills/group-controls/",
        views.update_skill_group_controls_view,
        name="update_skill_group_controls",
    ),
    path("fitting/<int:fitting_id>/mastery/", views.update_fitting_mastery, name="update_fitting_mastery"),
    path("fitting/<int:fitting_id>/blacklist/", views.toggle_skill_blacklist_view, name="toggle_skill_blacklist_view"),
]
