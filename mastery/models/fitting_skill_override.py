from django.db import models
from eve_sde.models import ItemType
from fittings.models import Fitting

class FittingSkillOverride(models.Model):
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

    is_blacklisted = models.BooleanField(default=True)

    class Meta:
        unique_together = ('fitting_id', 'skill_type_id')