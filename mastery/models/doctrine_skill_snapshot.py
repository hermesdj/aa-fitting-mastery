"""Snapshot of skills computed for a doctrine fitting."""
from django.db import models
from django.utils.translation import gettext_lazy as _
from eve_sde.models import ItemType
from fittings.models import Doctrine, Fitting

NAMES_MAX_LENGTH = 255


class DoctrineSkillSnapshot(models.Model):
    """DoctrineSkillSnapshot Django model."""
    doctrine = models.ForeignKey(
        Doctrine,
        on_delete=models.DO_NOTHING,
        verbose_name=_("doctrine"),
        to_field="id"
    )
    doctrine_name = models.CharField(
        max_length=NAMES_MAX_LENGTH,
        verbose_name=_("doctrine name")
    )

    fitting = models.ForeignKey(
        Fitting,
        on_delete=models.DO_NOTHING,
        verbose_name=_("fitting"),
        to_field="id",
        related_name="+"
    )

    fitting_name = models.CharField(
        max_length=NAMES_MAX_LENGTH,
        verbose_name=_("fitting name")
    )

    ship_type = models.ForeignKey(
        ItemType,
        on_delete=models.DO_NOTHING,
        verbose_name=_("ship type"),
        to_field="id",
        related_name="+"
    )
    ship_name = models.CharField(
        max_length=NAMES_MAX_LENGTH
    )

    skill_type = models.ForeignKey(
        ItemType,
        on_delete=models.DO_NOTHING,
        verbose_name=_("skill type"),
        to_field="id",
        related_name="+"
    )

    required_level = models.PositiveIntegerField(
        default=0,
        verbose_name=_("required level")
    )
    recommended_level = models.PositiveIntegerField(
        default=0,
        verbose_name=_("recommended level")
    )

    is_required = models.BooleanField(default=False)
    is_recommended = models.BooleanField(default=False)

    level_gap = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
