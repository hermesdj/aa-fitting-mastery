"""Service for fitting skill plan approval workflow."""

from django.utils import timezone

from mastery.models import FittingSkillsetMap


class FittingApprovalService:
    """Handle approval and audit transitions for fitting skill plans."""

    @staticmethod
    def mark_modified(
        fitting_map: FittingSkillsetMap,
        *,
        user=None,
        status: str | None = None,
    ) -> FittingSkillsetMap:
        """Mark a skill plan as changed and invalidate any existing approval."""
        fitting_map.status = status or FittingSkillsetMap.ApprovalStatus.IN_PROGRESS
        fitting_map.approved_by = None
        fitting_map.approved_at = None
        fitting_map.modified_by = user
        fitting_map.modified_at = timezone.now()
        fitting_map.save(
            update_fields=[
                "status",
                "approved_by",
                "approved_at",
                "modified_by",
                "modified_at",
            ]
        )
        return fitting_map

    @staticmethod
    def mark_status(
        fitting_map: FittingSkillsetMap,
        *,
        status: str,
    ) -> FittingSkillsetMap:
        """Set a non-approved workflow status and clear approval metadata."""
        fitting_map.status = status
        fitting_map.approved_by = None
        fitting_map.approved_at = None
        fitting_map.save(update_fields=["status", "approved_by", "approved_at"])
        return fitting_map

    @staticmethod
    def approve(fitting_map: FittingSkillsetMap, *, user) -> FittingSkillsetMap:
        """Approve a fitting skill plan."""
        fitting_map.status = FittingSkillsetMap.ApprovalStatus.APPROVED
        fitting_map.approved_by = user
        fitting_map.approved_at = timezone.now()
        fitting_map.save(update_fields=["status", "approved_by", "approved_at"])
        return fitting_map
