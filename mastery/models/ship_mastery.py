"""Model for ship mastery levels."""

from django.db import models
from eve_sde.models import ItemType


class ShipMastery(models.Model):
    """Stores mastery level data per ship type."""

    ship_type = models.ForeignKey(ItemType, on_delete=models.CASCADE, related_name="+")
    level = models.IntegerField()
