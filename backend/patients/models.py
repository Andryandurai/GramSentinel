"""Individual layer — RuralCare.

Records here never cross into community surveillance. Only aggregates do, via
`community.aggregation` (Section 7.3 / 26). All demonstration records are
synthetic.
"""

from django.conf import settings
from django.db import models


class Patient(models.Model):
    class Sex(models.TextChoices):
        FEMALE = "F", "Female"
        MALE = "M", "Male"
        OTHER = "O", "Other"
        UNKNOWN = "U", "Not stated"

    patient_code = models.CharField(
        max_length=32,
        unique=True,
        help_text="Local identifier. Synthetic in the prototype.",
    )
    display_name = models.CharField(
        max_length=120,
        blank=True,
        help_text="Synthetic name used only inside the individual layer.",
    )
    age_years = models.PositiveSmallIntegerField(null=True, blank=True)
    age_months = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Used for infants; the red-flag rule set treats <2 months specially.",
    )
    sex = models.CharField(max_length=1, choices=Sex.choices, default=Sex.UNKNOWN)
    village = models.ForeignKey(
        "core.Village", on_delete=models.PROTECT, related_name="patients"
    )
    linked_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="patient_profile",
        help_text="Set only when the optional patient portal is used.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="registered_patients",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["patient_code"]

    def __str__(self) -> str:
        return f"{self.patient_code} ({self.display_name or 'unnamed'})"

    @property
    def age_in_months(self) -> int | None:
        if self.age_months is not None:
            return self.age_months
        if self.age_years is not None:
            return self.age_years * 12
        return None
