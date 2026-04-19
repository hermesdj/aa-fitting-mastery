"""Skill Plan Progression models for learning path management."""
from django.db import models
from memberaudit.models import SkillSetGroup


class SkillPlanProgression(models.Model):
    """A learning progression: an ordered sequence of skill plans for pilots to learn."""

    name = models.CharField(
        max_length=255,
        unique=True,
        verbose_name="name",
        help_text="Name of this learning progression (e.g., 'Basic Pilot Path')"
    )
    description = models.TextField(
        blank=True,
        verbose_name="description",
        help_text="Description of the learning path and its purpose"
    )
    order = models.PositiveIntegerField(
        default=0,
        verbose_name="order",
        help_text="Display order in progression lists"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="is active",
        help_text="Inactive progressions are hidden from pilot views"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="created at"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="updated at"
    )

    class Meta:
        verbose_name = "skill plan progression"
        verbose_name_plural = "skill plan progressions"
        ordering = ["order", "name"]
        default_permissions = ()

    def __str__(self):
        return self.name


class SkillPlanProgressionStep(models.Model):
    """A single step in a skill plan progression."""

    progression = models.ForeignKey(
        SkillPlanProgression,
        on_delete=models.CASCADE,
        related_name="steps",
        verbose_name="progression"
    )
    skillset_group = models.ForeignKey(
        SkillSetGroup,
        on_delete=models.CASCADE,
        verbose_name="skillset group",
        help_text="The skillset group to learn at this step"
    )
    step_number = models.CharField(
        max_length=10,
        verbose_name="step number",
        help_text="Step identifier (e.g., '1', '2', '3a', '3b')"
    )
    is_required = models.BooleanField(
        default=True,
        verbose_name="is required",
        help_text="If False, this is an optional branch that pilots can choose instead of another"
    )
    branch_key = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="branch key",
        help_text="Group key for branching (e.g., 'step_3' groups 3a and 3b as alternatives)"
    )
    description = models.TextField(
        blank=True,
        verbose_name="description",
        help_text="Why this skillset is needed at this step"
    )
    order = models.PositiveIntegerField(
        verbose_name="order",
        help_text="Display order within the progression"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="created at"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="updated at"
    )

    class Meta:
        verbose_name = "skill plan progression step"
        verbose_name_plural = "skill plan progression steps"
        ordering = ["progression_id", "order"]
        unique_together = ("progression_id", "skillset_group_id")
        default_permissions = ()

    def __str__(self):
        return f"{self.progression.name} - Step {self.step_number}"
