"""Doctrine to SkillSetGroup mapping model."""
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from fittings.models import Doctrine
from memberaudit.models import SkillSetGroup


class DoctrineSkillSetGroupMap(models.Model):
    """DoctrineSkillSetGroupMap Django model."""
    doctrine = models.ForeignKey(
        Doctrine,
        on_delete=models.DO_NOTHING,
        verbose_name="doctrine",
        to_field="id"
    )

    skillset_group = models.ForeignKey(
        SkillSetGroup,
        on_delete=models.DO_NOTHING,
        verbose_name="skillset group"
    )

    default_mastery_level = models.PositiveIntegerField(
        default=4,
        verbose_name="default mastery level"
    )

    priority = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        verbose_name="priority",
        help_text="Doctrine training priority from 0 (default, no highlight) to 10 (highest).",
        db_index=True,
    )

    class Meta:
        """Model metadata (ordering, indexes and constraints)."""
        unique_together = ("doctrine_id", "skillset_group_id")
