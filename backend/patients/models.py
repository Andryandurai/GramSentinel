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

    # --- Patient details (persist across every assessment, never stored
    # per-encounter) — a worker may leave any of these blank, and none of
    # them is read by triage/safety logic; they exist only to keep a more
    # complete patient record. ------------------------------------------
    height_cm = models.FloatField(
        null=True, blank=True, help_text="Height in centimetres, if recorded."
    )
    weight_kg = models.FloatField(
        null=True, blank=True, help_text="Weight in kilograms, if recorded."
    )
    phone_number = models.CharField(max_length=32, blank=True)
    house_location = models.CharField(
        max_length=200,
        blank=True,
        help_text=(
            "A local reference for finding the household (e.g. 'Near the "
            "temple', 'House 24') — never GPS coordinates or a formal "
            "postal address."
        ),
    )

    village = models.ForeignKey(
        "core.Village", on_delete=models.PROTECT, related_name="patients"
    )
    linked_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="patient_profile",
        help_text="Legacy field: linked a patient record to its own login "
        "for the optional patient portal, which has been removed from the "
        "application. No code path sets this any more.",
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
