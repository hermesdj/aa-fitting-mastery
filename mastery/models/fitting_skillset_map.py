"""Fitting to SkillSet mapping model."""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
from fittings.models import Fitting
from memberaudit.models import SkillSet

from mastery.models import DoctrineSkillSetGroupMap


class FittingSkillsetMap(models.Model):
    """FittingSkillsetMap Django model."""

    class ApprovalStatus(models.TextChoices):
        """Workflow states for one fitting skill plan."""

        IN_PROGRESS = "in_progress", _("In progress")
        NOT_APPROVED = "not_approved", _("Not approved")
        APPROVED = "approved", _("Approved")

    doctrine_map = models.ForeignKey(
        DoctrineSkillSetGroupMap,
        on_delete=models.CASCADE,
        verbose_name=_("doctrine map"),
        to_field="id",
        related_name="fittings"
    )

    fitting = models.ForeignKey(
        Fitting,
        on_delete=models.DO_NOTHING,
        verbose_name=_("fitting"),
        to_field="id"
    )

    skillset = models.ForeignKey(
        SkillSet,
        on_delete=models.DO_NOTHING,
        verbose_name=_("skillset"),
        to_field="id"
    )

    mastery_level = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("mastery level")
    )

    priority = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        verbose_name=_("priority"),
        help_text=_("Fitting training priority from 0 (default, no highlight) to 10 (highest)."),
    )

    last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("last synced at"),
    )

    status = models.CharField(
        max_length=24,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.NOT_APPROVED,
        verbose_name=_("approval status"),
    )

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_mastery_fitting_maps",
        verbose_name=_("approved by"),
    )

    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("approved at"),
    )

    modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="modified_mastery_fitting_maps",
        verbose_name=_("modified by"),
    )

    modified_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("modified at"),
    )

    class Meta:
        """Model metadata (ordering, indexes and constraints)."""
        unique_together = ("fitting_id", "skillset_id")
