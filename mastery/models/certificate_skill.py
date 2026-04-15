"""Certificate-to-skill relationship model."""
from django.db import models
from eve_sde.models import ItemType


class CertificateSkill(models.Model):
    """CertificateSkill Django model."""
    certificate_id = models.IntegerField()
    skill_type = models.ForeignKey(ItemType, on_delete=models.CASCADE, related_name="+")
    level_basic = models.IntegerField(null=True)
    level_standard = models.IntegerField(null=True)
    level_improved = models.IntegerField(null=True)
    level_advanced = models.IntegerField(null=True)
    level_elite = models.IntegerField(null=True)

    class Meta:
        """Model metadata (ordering, indexes and constraints)."""
        indexes = [
            models.Index(fields=["certificate_id"])
        ]
