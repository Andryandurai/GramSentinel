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

    def __str__(self) -> str:
        return f"{self.username} <{self.role}>"

    @property
    def display_name(self) -> str:
        return self.full_name or self.get_full_name() or self.username

    @property
    def is_worker(self) -> bool:
        return self.role == self.Role.CHW_PHC_WORKER

    @property
    def is_officer(self) -> bool:
        return self.role == self.Role.HEALTH_OFFICER

    @property
    def is_platform_admin(self) -> bool:
        return self.role == self.Role.ADMIN or self.is_superuser
