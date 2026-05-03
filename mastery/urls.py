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
    # Summaries
    path("summaries/", views.summary_list_view, name="summary_list"),
    path("summaries/debug/p2-metrics/", views.summary_p2_metrics_debug_view, name="summary_p2_metrics_debug"),
    path("summaries/doctrine/<int:doctrine_id>/", views.summary_doctrine_detail_view, name="summary_doctrine_detail"),
    path("summaries/fitting/<int:fitting_id>/", views.summary_fitting_detail_view, name="summary_fitting_detail"),
    path("summaries/settings/", views.summary_settings_view, name="summary_settings"),
    # Doctrine Management
    path("doctrines/", views.doctrine_list_view, name="doctrine_list"),
    path("doctrines/<int:doctrine_id>/", views.doctrine_detail_view, name="doctrine_detail"),
    path("doctrines/<int:doctrine_id>/generate/", views.generate_doctrine, name="generate_doctrine"),
    path("doctrines/<int:doctrine_id>/sync/", views.sync_doctrine, name="sync_doctrine"),
    path("doctrines/<int:doctrine_id>/mastery/", views.update_doctrine_mastery, name="update_doctrine_mastery"),
    path("doctrines/<int:doctrine_id>/priority/", views.update_doctrine_priority, name="update_doctrine_priority"),

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
    path(
        "fitting/<int:fitting_id>/skills/make-alpha-compatible/",
        views.make_recommended_plan_alpha_compatible_view,
        name="make_recommended_plan_alpha_compatible",
    ),
    path("fitting/<int:fitting_id>/mastery/", views.update_fitting_mastery, name="update_fitting_mastery"),
    path("fitting/<int:fitting_id>/priority/", views.update_fitting_priority, name="update_fitting_priority"),
    path("fitting/<int:fitting_id>/blacklist/", views.toggle_skill_blacklist_view, name="toggle_skill_blacklist_view"),
]
