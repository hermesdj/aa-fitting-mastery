"""Fitting to SkillSet mapping model."""
from django.db import models
from fittings.models import Fitting
from memberaudit.models import SkillSet

from mastery.models import DoctrineSkillSetGroupMap


class FittingSkillsetMap(models.Model):
    """FittingSkillsetMap Django model."""
    doctrine_map = models.ForeignKey(
        DoctrineSkillSetGroupMap,
        on_delete=models.CASCADE,
        verbose_name="doctrine map",
        to_field="id",
        related_name="fittings"
    )

    fitting = models.ForeignKey(
        Fitting,
        on_delete=models.DO_NOTHING,
        verbose_name="fitting",
        to_field="id"
    )

    skillset = models.ForeignKey(
        SkillSet,
        on_delete=models.DO_NOTHING,
        verbose_name="skillset",
        to_field="id"
    )

    mastery_level = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="mastery level"
    )

    last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="last synced at",
    )

    class Meta:
        """Model metadata (ordering, indexes and constraints)."""
        unique_together = ("fitting_id", "skillset_id")
