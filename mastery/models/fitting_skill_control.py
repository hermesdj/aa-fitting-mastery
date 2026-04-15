"""Per-fitting, per-skill control overrides (blacklist, recommended level)."""
from django.db import models
from eve_sde.models import ItemType
from fittings.models import Fitting


class FittingSkillControl(models.Model):
    """FittingSkillControl Django model."""
    fitting = models.ForeignKey(
        Fitting,
        on_delete=models.DO_NOTHING,
        verbose_name="fitting",
        to_field="id"
    )

    skill_type = models.ForeignKey(
        ItemType,
        on_delete=models.DO_NOTHING,
        verbose_name="skill type",
        to_field="id",
        related_name="+"
    )

    is_blacklisted = models.BooleanField(
        default=False,
        verbose_name="is blacklisted"
    )

    is_suggested = models.BooleanField(
        default=False,
        verbose_name="is suggested"
    )

    reason = models.CharField(
        max_length=255,
        null=True,
        blank=True
    )

    recommended_level_override = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="recommended level override"
    )

    is_manual = models.BooleanField(
        default=False,
        verbose_name="is manual"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Model metadata (ordering, indexes and constraints)."""
        unique_together = ('fitting_id', 'skill_type_id')
        indexes = [
            models.Index(fields=["fitting_id"])
        ]
