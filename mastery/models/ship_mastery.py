from django.db import models
from eve_sde.models import ItemType


class ShipMastery(models.Model):
    ship_type = models.ForeignKey(ItemType, on_delete=models.CASCADE, related_name="+")
    level = models.IntegerField()