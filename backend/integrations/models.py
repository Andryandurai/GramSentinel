"""Integration Layer audit.

Data *acquisition* varies per source — API, approved export, reporting portal,
mobile form, public feed. Data *processing* does not: once a record is here it
goes through the same validation and normalisation regardless of how it
arrived. This model records which channel each batch came through, so Stage 1
is inspectable rather than assumed.

Every channel is simulated in the prototype. No real institutional feed exists.
"""

from django.db import models

from community.models import DataSource


class IngestionEvent(models.Model):
    class Result(models.TextChoices):
        ACCEPTED = "ACCEPTED", "Accepted"
        REJECTED = "REJECTED", "Rejected in validation"
        PARTIAL = "PARTIAL", "Accepted with flags"

    source = models.ForeignKey(
        DataSource,
        on_delete=models.CASCADE,
        related_name="ingestion_events",
        null=True,
        blank=True,
    )
    channel = models.CharField(max_length=16, choices=DataSource.Channel.choices)
    week_label = models.CharField(max_length=16, blank=True)
    records_received = models.PositiveIntegerField(default=0)
    records_accepted = models.PositiveIntegerField(default=0)
    records_rejected = models.PositiveIntegerField(default=0)
    records_deduplicated = models.PositiveIntegerField(default=0)
    missing_flagged = models.PositiveIntegerField(default=0)
    result = models.CharField(
        max_length=16, choices=Result.choices, default=Result.ACCEPTED
    )
    validation_notes = models.JSONField(default=list, blank=True)
    simulated = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Ingestion {self.channel} {self.week_label} [{self.result}]"
