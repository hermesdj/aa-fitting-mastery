from django.db import models
from fittings.models import Doctrine
from memberaudit.models import SkillSetGroup


class DoctrineSkillSetGroupMap(models.Model):
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

    class Meta:
        unique_together = ("doctrine_id", "skillset_group_id")
