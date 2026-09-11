from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Platform user.

    Role drives backend permission enforcement (Section 23 / 37). The frontend
    also hides what a role may not use, but that is a usability measure and is
    never relied upon for access control.
    """

    class Role(models.TextChoices):
        CHW_PHC_WORKER = "CHW_PHC_WORKER", "CHW / PHC Worker"
        HEALTH_OFFICER = "HEALTH_OFFICER", "Health Officer"
        PATIENT = "PATIENT", "Patient"
        ADMIN = "ADMIN", "Administrator"

    role = models.CharField(
        max_length=32, choices=Role.choices, default=Role.CHW_PHC_WORKER
    )
    full_name = models.CharField(max_length=160, blank=True)
    village = models.ForeignKey(
        "core.Village",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
        help_text="Worker's own area. Scopes what local signals they may read.",
    )
    facility = models.ForeignKey(
        "core.Facility",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff",
    )
    district = models.CharField(
        max_length=120,
        blank=True,
        help_text="Health officer's district of responsibility.",
    )

    # --- Professional profile -------------------------------------------
    # Optional throughout: a profile is something staff fill in, not a second
    # set of mandatory registration fields. Nothing here affects sign-in —
    # username and password are untouched by the profile endpoints.
    phone_number = models.CharField(max_length=32, blank=True)
    staff_id = models.CharField(
        max_length=32,
        blank=True,
        help_text="Employee / worker identifier used by the health department.",
    )
    qualification = models.CharField(max_length=160, blank=True)
    experience_years = models.PositiveSmallIntegerField(null=True, blank=True)
    photo = models.TextField(
        blank=True,
        help_text=(
            "Profile photograph as a validated data URI. Stored on the record "
            "rather than in a public media directory so it is only ever served "
            "through an authenticated, village-scoped endpoint."
        ),
    )
    profile_updated_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.username} <{self.role}>"

    @property
    def display_name(self) -> str:
        return self.full_name or self.get_full_name() or self.username

    @property
    def has_photo(self) -> bool:
        return bool(self.photo)

    @property
    def initials(self) -> str:
        """Fallback used wherever a photograph has not been uploaded."""

        parts = [p for p in self.display_name.replace(".", " ").split() if p]
        letters = [p[0] for p in parts if p[0].isalpha()]
        return "".join(letters[:2]).upper() or self.username[:2].upper()

    @property
    def is_worker(self) -> bool:
        return self.role == self.Role.CHW_PHC_WORKER

    @property
    def is_officer(self) -> bool:
        return self.role == self.Role.HEALTH_OFFICER

    @property
    def is_platform_admin(self) -> bool:
        return self.role == self.Role.ADMIN or self.is_superuser
