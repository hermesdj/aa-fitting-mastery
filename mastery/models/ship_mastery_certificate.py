from django.db import models

from .ship_mastery import ShipMastery


class ShipMasteryCertificate(models.Model):
    mastery = models.ForeignKey(ShipMastery, on_delete=models.CASCADE)
    certificate_id = models.IntegerField()

    class Meta:
        indexes = [
            models.Index(fields=["certificate_id"])
        ]
