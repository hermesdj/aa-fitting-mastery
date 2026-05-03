"""Persisted SDE clone-grade skill caps (Alpha max levels)."""

from django.db import models
from eve_sde.models import ItemType


class SdeCloneGradeSkill(models.Model):
    """Store the canonical Alpha max trainable level for each skill type."""

    skill_type = models.ForeignKey(ItemType, on_delete=models.CASCADE, related_name="+")
    max_alpha_level = models.IntegerField()

    class Meta:
        """Model metadata (ordering, indexes and constraints)."""

        constraints = [
            models.UniqueConstraint(fields=["skill_type"], name="mastery_unique_clone_grade_skill_type")
        ]
        indexes = [
            models.Index(fields=["max_alpha_level"], name="mastery_sde_max_al_63f970_idx"),
        ]
