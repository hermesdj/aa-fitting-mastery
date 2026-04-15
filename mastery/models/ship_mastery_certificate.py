"""Ship mastery certificate model."""
from django.db import models

from .ship_mastery import ShipMastery


class ShipMasteryCertificate(models.Model):
    """ShipMasteryCertificate Django model."""
    mastery = models.ForeignKey(ShipMastery, on_delete=models.CASCADE)
    certificate_id = models.IntegerField()

    class Meta:
        """Model metadata (ordering, indexes and constraints)."""
        indexes = [
            models.Index(fields=["certificate_id"])
        ]
