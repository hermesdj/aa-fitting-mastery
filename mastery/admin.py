"""Admin registrations for Fitting Mastery models."""
from django.contrib import admin

from .app_settings import securegroups_installed


# ──────────────────────────────────────────────────────────────────────────────
# Secure Groups integration (optional)
# ──────────────────────────────────────────────────────────────────────────────

if securegroups_installed():
    from mastery.secure_groups import (
        MasteryDoctrineReadinessFilter,
        MasteryFittingEliteFilter,
        MasteryFittingProgressFilter,
        MasteryFittingStatusFilter,
    )

    @admin.register(MasteryFittingStatusFilter)
    class MasteryFittingStatusFilterAdmin(admin.ModelAdmin):
        """Admin for mastery fitting status smart filter."""
        list_display = ("name", "description", "fitting_map", "minimum_status", "check_all_characters")
        list_filter = ("minimum_status", "check_all_characters")
        search_fields = ("name", "description")

    @admin.register(MasteryFittingProgressFilter)
    class MasteryFittingProgressFilterAdmin(admin.ModelAdmin):
        """Admin for mastery fitting progress smart filter."""
        list_display = ("name", "description", "fitting_map", "minimum_progress_pct", "use_required_plan")
        list_filter = ("use_required_plan",)
        search_fields = ("name", "description")

    @admin.register(MasteryDoctrineReadinessFilter)
    class MasteryDoctrineReadinessFilterAdmin(admin.ModelAdmin):
        """Admin for mastery doctrine readiness smart filter."""
        list_display = ("name", "description", "doctrine_map", "minimum_fittings", "approved_only")
        list_filter = ("approved_only",)
        search_fields = ("name", "description")

    @admin.register(MasteryFittingEliteFilter)
    class MasteryFittingEliteFilterAdmin(admin.ModelAdmin):
        """Admin for mastery fitting elite smart filter."""
        list_display = ("name", "description", "fitting_map")
        search_fields = ("name", "description")
