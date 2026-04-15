"""CRUD operations for per-fitting skill controls and blacklists."""
from mastery.models.fitting_skill_control import FittingSkillControl


class SkillControlService:
    """Manage per-fitting skill control flags and manual overrides."""

    @staticmethod
    def get_blacklist(fitting_id: int) -> set:
        """Return blacklisted skill IDs for a fitting."""
        return set(
            FittingSkillControl.objects.filter(
                fitting_id=fitting_id,
                is_blacklisted=True
            ).values_list('skill_type_id', flat=True)
        )

    def apply_blacklist(self, fitting_id: int, skills: dict) -> dict:
        """Filter out blacklisted skill IDs from a `{skill_id: level}` mapping."""
        blacklist = self.get_blacklist(fitting_id)
        return {
            skill_type_id: level for skill_type_id, level in skills.items() if skill_type_id not in blacklist
        }

    @staticmethod
    def set_blacklist(fitting_id: int, skill_type_id: int, value: bool):
        """Set or clear blacklist state for one skill in a fitting."""
        obj, _ = FittingSkillControl.objects.update_or_create(
            fitting_id=fitting_id,
            skill_type_id=skill_type_id,
            defaults={'is_blacklisted': value}
        )
        return obj

    @staticmethod
    def get_controls_map(fitting_id: int) -> dict:
        """Return all persisted control flags for a fitting keyed by skill ID."""
        rows = FittingSkillControl.objects.filter(fitting_id=fitting_id).values(
            "skill_type_id",
            "is_blacklisted",
            "is_suggested",
            "reason",
            "recommended_level_override",
            "is_manual",
        )
        return {
            row["skill_type_id"]: row
            for row in rows
        }

    @staticmethod
    def add_manual_skill(fitting_id: int, skill_type_id: int, level: int):
        """Create/update a manual skill override with recommended target level."""
        obj, _ = FittingSkillControl.objects.update_or_create(
            fitting_id=fitting_id,
            skill_type_id=skill_type_id,
            defaults={
                "is_manual": True,
                "is_blacklisted": False,
                "recommended_level_override": level,
            },
        )
        return obj

    @staticmethod
    def remove_manual_skill(fitting_id: int, skill_type_id: int):
        """Delete manual override rows for a specific fitting skill."""
        return FittingSkillControl.objects.filter(
            fitting_id=fitting_id,
            skill_type_id=skill_type_id,
            is_manual=True,
        ).delete()

    @staticmethod
    def set_recommended_level(fitting_id: int, skill_type_id: int, level):
        """Persist recommended level override for one fitting skill."""
        obj, _ = FittingSkillControl.objects.update_or_create(
            fitting_id=fitting_id,
            skill_type_id=skill_type_id,
            defaults={'recommended_level_override': level}
        )
        return obj

    def set_blacklist_batch(self, fitting_id: int, skill_type_ids: list, value: bool):
        """Apply blacklist state to multiple skills for the same fitting."""
        for skill_type_id in skill_type_ids:
            self.set_blacklist(fitting_id=fitting_id, skill_type_id=skill_type_id, value=value)

    def set_recommended_level_batch(self, fitting_id: int, skill_type_ids: list, level):
        """Apply the same recommended-level override to multiple fitting skills."""
        for skill_type_id in skill_type_ids:
            self.set_recommended_level(
                fitting_id=fitting_id,
                skill_type_id=skill_type_id,
                level=level,
            )

    @staticmethod
    def sync_suggestions(fitting_id: int, suggestions: dict):
        """Replace stored suggestion flags/reasons for a fitting from preview data."""
        FittingSkillControl.objects.filter(fitting_id=fitting_id).update(
            is_suggested=False,
            reason=None,
        )

        for skill_type_id, suggestion in suggestions.items():
            FittingSkillControl.objects.update_or_create(
                fitting_id=fitting_id,
                skill_type_id=skill_type_id,
                defaults={
                    'is_suggested': True,
                    'reason': suggestion['reason'],
                },
            )
