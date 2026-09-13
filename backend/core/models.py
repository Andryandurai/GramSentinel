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

    # --- Real-world community profile -----------------------------------
    # Optional, additive fields for a village whose real-world geographic
    # and demographic identity has been separately researched (as opposed
    # to a purely synthetic demonstration village). `real_world_profile`
    # is the explicit flag a serializer/view checks before rendering any
    # of these — blank/null on every village until deliberately populated,
    # so no existing village silently gains a fabricated profile.
    real_world_profile = models.BooleanField(
        default=False,
        help_text="True only for a village whose demographic/geographic "
        "profile below has been populated from real-world research, "
        "never inferred or guessed.",
    )
    state = models.CharField(max_length=120, blank=True)
    taluk = models.CharField(max_length=120, blank=True)
    pin_code = models.CharField(max_length=10, blank=True)
    census_village_code = models.CharField(max_length=20, blank=True)
    households = models.PositiveIntegerField(null=True, blank=True)
    male_population = models.PositiveIntegerField(null=True, blank=True)
    female_population = models.PositiveIntegerField(null=True, blank=True)
    children_0_6 = models.PositiveIntegerField(null=True, blank=True)
    area_hectares = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    demographic_baseline_year = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="e.g. 2011 for a Census 2011 baseline. Population/"
        "households/male/female/children figures above are as of this "
        "year — never presented as a current estimate.",
    )
    #: Free-text, provenance-aware healthcare-access facts. Each is exactly
    #: the researched value ("Available", "Yes", "Not reported") or blank
    #: when nothing was researched — never a boolean, because "not
    #: reported" is a statement about the research, not a claim that the
    #: facility does not exist.
    asha_chw_status = models.CharField(max_length=40, blank=True)
    nearby_government_phc_status = models.CharField(max_length=40, blank=True)
    health_sub_centre_status = models.CharField(max_length=40, blank=True)
    phc_inside_village_status = models.CharField(max_length=40, blank=True)
    chc_inside_village_status = models.CharField(max_length=40, blank=True)

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
