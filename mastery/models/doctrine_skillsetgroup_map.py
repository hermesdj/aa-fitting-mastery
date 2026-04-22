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

    def __str__(self) -> str:
        """Readable label for admin selects and FK displays."""
        doctrine_name = getattr(self.doctrine, "name", "") if getattr(self, "doctrine", None) else ""
        group_name = getattr(self.skillset_group, "name", "") if getattr(self, "skillset_group", None) else ""

        if doctrine_name and group_name and doctrine_name != group_name:
            return f"{doctrine_name} [{group_name}]"
        if doctrine_name:
            return str(doctrine_name)
        if group_name:
            return str(group_name)
        return f"Doctrine map #{getattr(self, 'pk', '?')}"
