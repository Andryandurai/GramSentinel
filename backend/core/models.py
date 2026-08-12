"""Shared geography.

Villages and facilities live here rather than in `community` so that both the
individual layer (users, patients) and the community layer can reference them
without a circular app dependency.

`Village.cluster` is the geographic unit the Safety Engine's geographic
consistency rule (R3) operates on: a pharmacy trend in one cluster does not
corroborate school absenteeism in another.
"""

from django.db import models


class Village(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    cluster = models.CharField(
        max_length=120,
        help_text="Geographic cluster used for corroboration (Safety Engine R3).",
    )
    block = models.CharField(max_length=120, blank=True)
    district = models.CharField(max_length=120, blank=True)
    population = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Facility(models.Model):
    class Kind(models.TextChoices):
        PHC = "PHC", "Primary Health Centre"
        SUB_CENTRE = "SUB_CENTRE", "Sub-centre"
        PHARMACY = "PHARMACY", "Pharmacy"
        SCHOOL = "SCHOOL", "School"
        LAB = "LAB", "Laboratory"

    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=160)
    kind = models.CharField(max_length=24, choices=Kind.choices)
    village = models.ForeignKey(
        Village, on_delete=models.CASCADE, related_name="facilities"
    )

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "facilities"

    def __str__(self) -> str:
        return f"{self.name} [{self.kind}]"
