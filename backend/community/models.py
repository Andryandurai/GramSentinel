"""Community layer — GramSentinel.

Schema-level privacy boundary (Section 13): nothing in this module has a
foreign key to `patients.Patient` or `assessments.PatientAssessment`. Community
tables only ever hold counts tied to a village/facility and a time window.
"""

from django.conf import settings
from django.db import models

from core.constants import DataQuality, SignalCategory, SourceKind


class DataSource(models.Model):
    """A registered contributor of community signals.

    In the prototype every source is simulated through the Integration Layer;
    `channel` records how it *would* arrive in a real deployment (Section 8).
    """

    class Channel(models.TextChoices):
        API = "API", "Authorised API"
        EXPORT = "EXPORT", "Approved aggregated export"
        PORTAL = "PORTAL", "Reporting portal / mobile form"
        PUBLIC_FEED = "PUBLIC_FEED", "Public machine-readable feed"
        INTERNAL = "INTERNAL", "Computed internally by GramSentinel"

    code = models.CharField(max_length=48, unique=True)
    name = models.CharField(max_length=160)
    kind = models.CharField(max_length=32, choices=SourceKind.choices)
    channel = models.CharField(
        max_length=16, choices=Channel.choices, default=Channel.PORTAL
    )
    village = models.ForeignKey(
        "core.Village", on_delete=models.CASCADE, related_name="data_sources"
    )
    facility = models.ForeignKey(
        "core.Facility",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="data_sources",
    )
    is_active = models.BooleanField(default=True)
    simulated = models.BooleanField(
        default=True,
        help_text="True for the whole prototype. No real institutional feed exists.",
    )
    last_report_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "When this source last successfully delivered data, set by the "
            "Integration Layer on every accepted record. Null means nothing "
            "has ever been received — which is not the same as a zero reading."
        ),
    )

    class Meta:
        ordering = ["kind", "name"]

    def __str__(self) -> str:
        return f"{self.name} [{self.kind}]"


class CommunityReport(models.Model):
    """A CHW/PHC worker's structured village-level observation.

    Village-level counts by category — never household identities.

    The four `*_cases` columns are the original schema and are preserved. The
    broader category set lives in `CommunityReportEntry`; the legacy columns
    are kept in sync for the four categories they represent, so existing rows
    and any code reading them continue to work unchanged.
    """

    worker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="community_reports",
    )
    village = models.ForeignKey(
        "core.Village", on_delete=models.PROTECT, related_name="community_reports"
    )
    week_label = models.CharField(max_length=16, help_text="e.g. 2026-W32")
    period_start = models.DateField()
    period_end = models.DateField()

    fever_cases = models.PositiveIntegerField(default=0)
    respiratory_cases = models.PositiveIntegerField(default=0)
    diarrhoeal_cases = models.PositiveIntegerField(default=0)
    other_cases = models.PositiveIntegerField(default=0)
    unusual_observation = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    submitted_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set when a health officer has opened this report.",
    )

    # --- offline capture provenance -------------------------------------
    # `submitted_at` is when the report reached the server. For a report
    # captured without connectivity that can be hours after the worker
    # actually recorded it, and an officer reading "6 fever cases" needs to
    # know which of those two times the observation belongs to.
    captured_offline = models.BooleanField(
        default=False,
        help_text="True when this report was recorded on a device with no connectivity.",
    )
    client_created_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "When the worker completed the report on their device. Device "
            "clock, so it is displayed as the worker's own record of when they "
            "observed this — never used for ordering against server times."
        ),
    )

    class Meta:
        ordering = ["-period_start"]
        unique_together = [("village", "week_label", "worker")]

    def __str__(self) -> str:
        return f"CHW report {self.village.code} {self.week_label}"

    @property
    def total_reported_cases(self) -> int:
        return sum(entry.case_count for entry in self.entries.all())

    @property
    def has_described_concerns(self) -> bool:
        """True when the worker wrote up something the category list can't say."""
        return any(entry.description.strip() for entry in self.entries.all())


class CommunityReportEntry(models.Model):
    """One reported category within a community report.

    This is what makes the expanded category set possible without adding
    twenty columns to CommunityReport. `description` carries the worker's own
    words for categories where the label alone is not enough — an "Other"
    entry is meaningless to an officer without it.

    A count here is a *reported observation*, never a confirmed case.
    """

    report = models.ForeignKey(
        CommunityReport, on_delete=models.CASCADE, related_name="entries"
    )
    category = models.CharField(max_length=32, choices=SignalCategory.choices)
    case_count = models.PositiveIntegerField(
        default=0, help_text="Reported/observed cases. Not confirmed diagnoses."
    )
    description = models.TextField(
        blank=True,
        help_text="What the worker observed. Required for 'Other' categories.",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["category", "id"]
        verbose_name_plural = "community report entries"

    def __str__(self) -> str:
        return f"{self.get_category_display()} × {self.case_count}"


class CommunitySignal(models.Model):
    """One normalised measurement from one source, for one category and window.

    `is_reported=False` is the explicit representation of missing data. A source
    that did not submit is stored with `value=None`, never as zero — absence of
    a report is not absence of cases (Safety Engine R8).
    """

    source = models.ForeignKey(
        DataSource, on_delete=models.CASCADE, related_name="signals"
    )
    village = models.ForeignKey(
        "core.Village", on_delete=models.PROTECT, related_name="signals"
    )
    category = models.CharField(max_length=32, choices=SignalCategory.choices)
    week_label = models.CharField(max_length=16)
    period_start = models.DateField()
    period_end = models.DateField()

    value = models.FloatField(null=True, blank=True)
    baseline = models.FloatField(null=True, blank=True)
    unit = models.CharField(max_length=32, blank=True)
    is_reported = models.BooleanField(default=True)
    data_quality = models.CharField(
        max_length=16, choices=DataQuality.choices, default=DataQuality.GOOD
    )
    metadata = models.JSONField(default=dict, blank=True)

    ingested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period_start", "source__kind"]
        unique_together = [("source", "category", "week_label")]
        indexes = [
            models.Index(fields=["village", "week_label", "category"]),
        ]

    def __str__(self) -> str:
        shown = "not submitted" if not self.is_reported else self.value
        return f"{self.source.kind}/{self.category} {self.week_label} = {shown}"

    @property
    def change_pct(self) -> float | None:
        if not self.is_reported or self.value is None:
            return None
        if self.baseline in (None, 0):
            return None
        return (self.value - self.baseline) / self.baseline * 100.0


class OfflineSubmission(models.Model):
    """Receipt for one offline-captured report that reached the server.

    This is what makes "store it only once" true rather than hoped for. An
    unstable connection retries: the same report can arrive two or five times,
    and every one of those attempts carries the same `client_report_uid`
    generated on the device when the worker first saved it. The first arrival
    creates a receipt; every later arrival finds it and is answered with the
    report that already exists, without re-running the pipeline.

    Why a separate table rather than a unique column on `CommunityReport`:
    reports are written with `update_or_create` keyed on
    (village, week_label, worker), so a second report for the same week
    overwrites the first row. A uid stored on that row would be overwritten
    with it, and a late retry of the *first* report would then look unseen and
    be processed a second time. A receipt is never overwritten, so the
    guarantee holds however the reports collapse.

    Receipts are kept after the report they point at is gone
    (`on_delete=SET_NULL`): a retry arriving later must still be recognised as
    something already handled.
    """

    client_report_uid = models.UUIDField(
        unique=True,
        help_text="Generated on the device when the report was saved, before any sync.",
    )
    worker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="offline_submissions",
    )
    village = models.ForeignKey(
        "core.Village", on_delete=models.PROTECT, related_name="offline_submissions"
    )
    report = models.ForeignKey(
        CommunityReport,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="offline_submissions",
    )
    client_created_at = models.DateTimeField(
        help_text="Device clock — when the worker completed the report offline."
    )
    received_at = models.DateTimeField(auto_now_add=True)
    retry_count = models.PositiveSmallIntegerField(
        default=0,
        help_text="How many duplicate deliveries of this report the server absorbed.",
    )

    class Meta:
        ordering = ["-received_at"]

    def __str__(self) -> str:
        return f"Offline submission {self.client_report_uid}"

    @property
    def sync_delay_seconds(self) -> float | None:
        """How long the report waited on the device before it synced."""

        if not self.client_created_at or not self.received_at:
            return None
        return (self.received_at - self.client_created_at).total_seconds()
