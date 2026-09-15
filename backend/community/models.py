"""Community layer — GramSentinel.

Schema-level privacy boundary (Section 13): nothing in this module has a
foreign key to `patients.Patient` or `assessments.PatientAssessment`. Community
tables only ever hold counts tied to a village/facility and a time window.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

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

    submitted_at = models.DateTimeField(
        auto_now_add=True,
        help_text=(
            "The server's own authoritative receipt time. This IS the "
            "'server_received_at' concept for offline sync — a separate, "
            "identically-timed column was not added, to avoid storing the "
            "same moment twice."
        ),
    )
    acknowledged_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set when a health officer has opened this report.",
    )

    # --- Offline Community Reporting -------------------------------------
    client_created_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "When the worker actually filled this report in, if it was "
            "queued on the device before syncing. Never overwritten by the "
            "sync time — `submitted_at` above is when the server received "
            "it, which can be well after this."
        ),
    )
    idempotency_key = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        unique=True,
        help_text=(
            "Client-generated key so an offline retry (timeout, dropped "
            "connection, duplicate tap) can never create a second report. "
            "`null` (not '') for rows with no key, so multiple online "
            "submissions can coexist under one UNIQUE constraint — NULL is "
            "not compared equal to NULL in SQL, unlike two empty strings "
            "would be."
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


class LocalSignalReport(models.Model):
    """A Health Worker's own flag that a specific signal on their Local
    Signals page deserves the Health Officer's attention.

    Distinct from `CommunityReport` (a worker's whole-week submission across
    every category) and from `alerts.Alert` (the system-generated, safety-
    gated GramSentinel signal): this is a lightweight human "please look at
    this" note layered on a `CommunitySignal` the worker is already looking
    at. It never creates or feeds an `Alert` — raising one still goes
    through the existing evidence/safety pipeline untouched.

    Display fields are denormalised from the signal at report time (the
    same "every model carries its own explicit reference, never a join"
    convention `SimulationFeedback`/`AlertEvidence` already use elsewhere in
    this codebase), so the report stays meaningful even if the underlying
    signal is later superseded. `signal` itself is kept for traceability
    only and is nullable so a signal's own deletion never deletes the human
    record of having reported it.
    """

    signal = models.ForeignKey(
        CommunitySignal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="worker_reports",
    )
    worker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="local_signal_reports",
    )
    village = models.ForeignKey(
        "core.Village", on_delete=models.PROTECT, related_name="local_signal_reports"
    )

    category = models.CharField(max_length=32, choices=SignalCategory.choices)
    source_kind = models.CharField(max_length=32, choices=SourceKind.choices)
    week_label = models.CharField(max_length=16)
    baseline = models.FloatField(null=True, blank=True)
    value = models.FloatField(null=True, blank=True)
    unit = models.CharField(max_length=32, blank=True)
    change_pct = models.FloatField(null=True, blank=True)

    note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set when a health officer has opened this report.",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["village", "-created_at"])]
        constraints = [
            # Same signal, same worker: a double-click, refresh or retry
            # must not create a second row. A later reporting period is
            # always a different `signal` (CommunitySignal's own uniqueness
            # is per source/category/week), so it is never blocked by this.
            models.UniqueConstraint(
                fields=["worker", "signal"], name="unique_local_signal_report_per_worker_signal"
            ),
        ]

    def __str__(self) -> str:
        return f"Local signal report: {self.category} {self.week_label} ({self.village.code})"


class OperationalContextMode(models.TextChoices):
    """See `community/operational_context.py`'s module docstring for the
    full explanation of each mode's effect on evidence."""

    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE", "Temporarily unavailable"
    EXPECTED_VARIATION = "EXPECTED_VARIATION", "Expected unusual activity"


class SourceOperationalContext(models.Model):
    """A human-recorded, time-bounded reason a source's own reading should
    not count as independent corroborating evidence — a school holiday, a
    PHC vaccination camp, a known reporting outage.

    This never mutates, hides, or deletes anything the source actually
    reported (see `community/operational_context.py`). It only changes how
    that reading is *interpreted* while the window applies. There is no
    "active" boolean column: whether a context currently applies is always
    computed live from `starts_on`/`ends_on`/`cancelled_at`, so a stale flag
    can never drift out of sync with the dates it was configured for.
    """

    source = models.ForeignKey(
        DataSource, on_delete=models.CASCADE, related_name="operational_contexts"
    )
    mode = models.CharField(max_length=32, choices=OperationalContextMode.choices)
    reason = models.CharField(max_length=200)
    notes = models.TextField(blank=True, default="")

    starts_on = models.DateField()
    ends_on = models.DateField()

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    #: Set by "Restore now" (Section 21). The originally configured
    #: `starts_on`/`ends_on` are preserved unchanged — cancellation is
    #: recorded as its own fact, not by silently shortening the window —
    #: so a historical snapshot taken before cancellation still shows
    #: exactly what was configured at that time.
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-starts_on"]
        indexes = [models.Index(fields=["source", "starts_on", "ends_on"])]

    def __str__(self) -> str:
        return f"{self.source.name}: {self.mode} {self.starts_on} -> {self.ends_on}"

    def is_applicable(self, period_start, period_end, *, as_of=None) -> bool:
        """Does this context cover ANY part of [period_start, period_end]?

        Both `starts_on`/`ends_on` are inclusive: a context configured
        15 Sep -> 28 Sep applies to any period touching that range, and a
        period beginning 29 Sep is unaffected — no manual restore needed.

        A cancellation stops the context from applying to any period
        starting on/after the cancellation date, but never retroactively:
        a period entirely before `cancelled_at` is unaffected, which is
        what keeps an already-persisted historical evidence snapshot
        correct even after the record it was taken from is later
        cancelled or edited.
        """

        if self.cancelled_at is not None:
            as_of = as_of or timezone.now()
            if self.cancelled_at <= as_of and period_start >= self.cancelled_at.date():
                return False
        return self.starts_on <= period_end and self.ends_on >= period_start
