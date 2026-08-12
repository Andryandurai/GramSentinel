from __future__ import annotations

import datetime as dt

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from community.models import DataSource
from core.constants import DataQuality, SignalCategory, SourceKind
from core.models import Village
from patients.models import Patient
from safety import EvidenceRecord, Hypothesis

User = get_user_model()

WEEK_LABEL = "2026-W32"
WEEK_START = dt.date(2026, 8, 3)
WEEK_END = dt.date(2026, 8, 9)


def make_record(
    source_kind: str = SourceKind.CHW,
    *,
    status: str = "ANOMALY_DETECTED",
    cluster: str = "Village Cluster A",
    week_label: str = WEEK_LABEL,
    period_start: dt.date = WEEK_START,
    period_end: dt.date = WEEK_END,
    data_quality: str = DataQuality.GOOD,
    is_corroborating: bool | None = None,
    is_reported: bool = True,
    baseline: float | None = 5.0,
    current_value: float | None = 14.0,
    change_pct: float | None = 180.0,
) -> EvidenceRecord:
    """Build one evidence record. Defaults describe a clean anomaly."""

    if is_corroborating is None:
        is_corroborating = status in {"ANOMALY_DETECTED", "CORROBORATING"} and (
            source_kind not in {SourceKind.WEATHER, SourceKind.RURALCARE_AGGREGATE}
        )
    return EvidenceRecord(
        source_kind=source_kind,
        source_name=f"{source_kind} test source",
        category=SignalCategory.FEVER,
        village_code="KVL",
        cluster=cluster,
        week_label=week_label,
        period_start=period_start,
        period_end=period_end,
        status=status,
        data_quality=data_quality,
        baseline=baseline,
        current_value=current_value,
        change_pct=change_pct,
        is_corroborating=is_corroborating,
        is_reported=is_reported,
    )


def make_hypothesis(
    records: tuple[EvidenceRecord, ...],
    *,
    kind: str = "correlation_hypothesis",
    narrative: str = (
        "Several independent sources moved above their own baselines. This is a "
        "possible pattern put forward for human review."
    ),
    cross_level_verdict: str = "CONSISTENT",
) -> Hypothesis:
    return Hypothesis(
        kind=kind,
        cluster="Village Cluster A",
        category=SignalCategory.FEVER,
        week_label=WEEK_LABEL,
        narrative=narrative,
        contributing=records,
        cross_level_verdict=cross_level_verdict,
        cross_level_statement="",
    )


@pytest.fixture
def village(db) -> Village:
    return Village.objects.create(
        code="KVL",
        name="Kovilur",
        cluster="Village Cluster A",
        block="North",
        district="Thiruvannamalai",
        population=4200,
    )


@pytest.fixture
def other_village(db) -> Village:
    return Village.objects.create(
        code="MLR", name="Melur", cluster="Village Cluster B", district="Thiruvannamalai"
    )


@pytest.fixture
def worker(db, village):
    return User.objects.create_user(
        username="worker",
        password="demo1234",
        role=User.Role.CHW_PHC_WORKER,
        full_name="Test CHW",
        village=village,
    )


@pytest.fixture
def officer(db):
    return User.objects.create_user(
        username="officer",
        password="demo1234",
        role=User.Role.HEALTH_OFFICER,
        full_name="Test Officer",
        district="Thiruvannamalai",
    )


@pytest.fixture
def patient(db, village) -> Patient:
    return Patient.objects.create(
        patient_code="KVL-P-001",
        display_name="Synthetic Patient",
        age_years=34,
        sex="F",
        village=village,
    )


@pytest.fixture
def infant(db, village) -> Patient:
    return Patient.objects.create(
        patient_code="KVL-P-INF",
        display_name="Synthetic Infant",
        age_months=1,
        sex="M",
        village=village,
    )


@pytest.fixture
def api() -> APIClient:
    return APIClient()


@pytest.fixture
def worker_api(api, worker) -> APIClient:
    api.force_authenticate(user=worker)
    return api


@pytest.fixture
def officer_api(api, officer) -> APIClient:
    api.force_authenticate(user=officer)
    return api


@pytest.fixture
def sources(db, village) -> dict[str, DataSource]:
    made = {}
    for kind, channel in [
        (SourceKind.CHW, DataSource.Channel.PORTAL),
        (SourceKind.PHC, DataSource.Channel.API),
        (SourceKind.PHARMACY, DataSource.Channel.EXPORT),
        (SourceKind.SCHOOL, DataSource.Channel.PORTAL),
        (SourceKind.WEATHER, DataSource.Channel.PUBLIC_FEED),
        (SourceKind.LAB, DataSource.Channel.API),
    ]:
        made[kind] = DataSource.objects.create(
            code=f"{kind}-KVL",
            name=f"{kind} — Kovilur",
            kind=kind,
            channel=channel,
            village=village,
        )
    return made
