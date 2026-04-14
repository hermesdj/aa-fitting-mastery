from django.db import models


class SummaryAudienceGroup(models.Model):
    name = models.CharField(max_length=120, unique=True)
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class SummaryAudienceEntity(models.Model):
    TYPE_CORPORATION = "corporation"
    TYPE_ALLIANCE = "alliance"
    TYPE_CHOICES = (
        (TYPE_CORPORATION, "Corporation"),
        (TYPE_ALLIANCE, "Alliance"),
    )

    group = models.ForeignKey(
        SummaryAudienceGroup,
        on_delete=models.CASCADE,
        related_name="entries",
    )
    entity_type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    entity_id = models.PositiveIntegerField()
    label = models.CharField(max_length=120, blank=True)

    class Meta:
        unique_together = (("group", "entity_type", "entity_id"),)
        ordering = ["entity_type", "entity_id"]
        indexes = [
            models.Index(fields=["entity_type", "entity_id"]),
        ]

    def __str__(self) -> str:
        suffix = f" ({self.label})" if self.label else ""
        return f"{self.group.name}: {self.entity_type} #{self.entity_id}{suffix}"

