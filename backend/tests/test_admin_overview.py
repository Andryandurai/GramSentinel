"""Admin platform overview and its village filter.

Two things under test, and the second matters as much as the first:

1. The filter genuinely narrows the data — every section, not just the heading.
2. Adding a cross-village admin view did not weaken worker or officer scoping.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from alerts.models import Alert
from assessments.models import PatientAssessment
from community.models import CommunityReport, CommunityReportEntry
from core.constants import SignalCategory
from core.models import Village
from patients.models import Patient

User = get_user_model()
pytestmark = pytest.mark.django_db

OVERVIEW = "/api/admin/overview/"


@pytest.fixture
def areas(db):
    """Three isolated, test-local villages — deliberately more than the two
    the demo seed now creates, to prove the admin's cross-village
    aggregation still scales past two villages (see Part 21 of the Village C
    demo-removal task: the architecture must keep supporting more villages
    even though the demo data no longer does).

    "MLR"/"Village C" here has no relationship to the old demo's Village C
    account (`worker.c`/`officer.c`, now removed) — it is a fresh row in
    this test's own transaction, named "Village C" directly (not through
    `core.constants.DEMO_VILLAGE_LABELS`, which no longer has an "MLR"
    entry) purely so this file's existing "Village C" assertions keep
    reading naturally.
    """

    return {
        code: Village.objects.create(
            code=code, name=name, cluster=cluster, district="Thiruvannamalai"
        )
        for code, name, cluster in (
            ("KVL", "Kovilur", "Village Cluster A"),
            ("ARY", "Ariyanur", "Village Cluster A"),
            ("MLR", "Village C", "Village Cluster B"),
        )
    }


@pytest.fixture
def platform_admin(db):
    return User.objects.create_user(
        username="admin", password="demo1234", role=User.Role.ADMIN
    )


@pytest.fixture
def admin_api(platform_admin):
    client = APIClient()
    client.force_authenticate(user=platform_admin)
    return client


@pytest.fixture
def populated(areas):
    """Deliberately unequal data so a filter that does nothing is detectable."""

    counts = {"KVL": 3, "ARY": 2, "MLR": 1}
    for code, n in counts.items():
        village = areas[code]

        User.objects.create_user(
            username=f"worker.{code.lower()}",
            password="demo1234",
            role=User.Role.CHW_PHC_WORKER,
            village=village,
        )
        User.objects.create_user(
            username=f"officer.{code.lower()}",
            password="demo1234",
            role=User.Role.HEALTH_OFFICER,
            village=village,
        )

        for index in range(n):
            patient = Patient.objects.create(
                patient_code=f"{code}-P-{index:03d}",
                age_years=30,
                village=village,
            )
            PatientAssessment.objects.create(
                patient=patient,
                village=village,
                symptoms=["fever"],
                primary_category=SignalCategory.FEVER,
                triage_level="CONCERNING",
                is_draft=False,
                encounter_date="2026-08-05",
            )

        report = CommunityReport.objects.create(
            village=village,
            week_label="2026-W32",
            period_start="2026-08-03",
            period_end="2026-08-09",
        )
        CommunityReportEntry.objects.create(
            report=report,
            category=SignalCategory.SKIN if code == "ARY" else SignalCategory.FEVER,
            case_count=n * 5,
            description="Observed locally." if code == "ARY" else "",
        )

        Alert.objects.create(
            village=village,
            cluster=village.cluster,
            category=SignalCategory.FEVER,
            week_label="2026-W32",
            period_start="2026-08-03",
            period_end="2026-08-09",
            title=f"Signals rising — {village.name}",
            summary="Possible pattern.",
            severity=Alert.Severity.MODERATE,
            safety_verdict="PASS",
            corroborating_source_count=2,
        )
    return counts


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------
def test_overview_requires_authentication():
    assert APIClient().get(OVERVIEW).status_code == 401


@pytest.mark.parametrize(
    "role", [User.Role.CHW_PHC_WORKER, User.Role.HEALTH_OFFICER, User.Role.PATIENT]
)
def test_non_admin_roles_cannot_read_the_overview(db, areas, role):
    user = User.objects.create_user(
        username=f"u-{role}", password="demo1234", role=role, village=areas["KVL"]
    )
    client = APIClient()
    client.force_authenticate(user=user)
    assert client.get(OVERVIEW).status_code == 403


def test_superuser_also_counts_as_platform_admin(db, areas):
    root = User.objects.create_superuser(username="root", password="demo1234")
    client = APIClient()
    client.force_authenticate(user=root)
    assert client.get(OVERVIEW).status_code == 200


# ---------------------------------------------------------------------------
# All villages
# ---------------------------------------------------------------------------
def test_all_villages_combines_every_area(admin_api, populated):
    data = admin_api.get(OVERVIEW).data

    assert data["scope"]["mode"] == "all"
    assert data["scope"]["label"] == "All Villages"
    assert data["scope"]["village_count"] == 3
    # 3 + 2 + 1, no double counting.
    assert data["totals"]["patients"] == 6
    assert data["totals"]["assessments"] == 6
    assert data["totals"]["community_reports"] == 3
    assert data["totals"]["alerts_active"] == 3
    assert data["totals"]["workers"] == 3
    assert data["totals"]["officers"] == 3


def test_village_summary_lists_all_three_with_labels(admin_api, populated):
    summary = admin_api.get(OVERVIEW).data["village_summary"]
    labels = {row["label"]: row for row in summary}

    assert set(labels) == {"Village A", "Village B", "Village C"}
    assert labels["Village A"]["patients"] == 3
    assert labels["Village B"]["patients"] == 2
    assert labels["Village C"]["patients"] == 1


def test_village_summary_status_reflects_alert_state(admin_api, populated, areas):
    alert = Alert.objects.filter(village=areas["MLR"]).first()
    alert.status = Alert.Status.UNDER_INVESTIGATION
    alert.save(update_fields=["status"])

    summary = {r["label"]: r for r in admin_api.get(OVERVIEW).data["village_summary"]}
    assert summary["Village C"]["status"] == "Under investigation"
    assert summary["Village A"]["status"] == "Monitoring"


def test_all_villages_selector_options_are_returned(admin_api, populated):
    villages = admin_api.get(OVERVIEW).data["villages"]
    assert [v["label"] for v in villages] == ["Village B", "Village A", "Village C"]


# ---------------------------------------------------------------------------
# Individual villages — the filter must actually filter
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "code,label,patients",
    [("KVL", "Village A", 3), ("ARY", "Village B", 2), ("MLR", "Village C", 1)],
)
def test_single_village_view_is_narrowed(admin_api, populated, code, label, patients):
    data = admin_api.get(f"{OVERVIEW}?village={code}").data

    assert data["scope"]["mode"] == "village"
    assert data["scope"]["label"] == label
    assert data["totals"]["patients"] == patients
    assert data["totals"]["assessments"] == patients
    assert data["totals"]["community_reports"] == 1
    assert data["totals"]["alerts_active"] == 1
    assert data["totals"]["workers"] == 1

    # Summary, alerts and staff all narrow to the one village too.
    assert [row["label"] for row in data["village_summary"]] == [label]
    assert {a["village_label"] for a in data["alerts"]} == {label}
    assert [t["label"] for t in data["team"]] == [label]


def test_one_village_view_excludes_other_villages_entirely(admin_api, populated):
    """Every data section names the selected village and no other.

    Asserted structurally rather than by searching the payload for foreign
    names: cluster names legitimately contain the string "Village C"
    ("Village Cluster A"), so a substring check reports leaks that are not
    there.
    """

    data = admin_api.get(f"{OVERVIEW}?village=KVL").data

    referenced_codes = (
        {row["code"] for row in data["village_summary"]}
        | {row["code"] for row in data["team"]}
        | {alert["village_code"] for alert in data["alerts"]}
        | {event["village_code"] for event in data["recent_activity"]}
        | {data["scope"]["village"]["code"]}
    )
    assert referenced_codes == {"KVL"}

    referenced_labels = (
        {row["label"] for row in data["village_summary"]}
        | {alert["village_label"] for alert in data["alerts"]}
        | {event["village_label"] for event in data["recent_activity"]}
    )
    assert referenced_labels == {"Village A"}

    # Trend lines are per-category in a single-village view, never per-village.
    assert "Village B" not in data["trend"]["keys"]
    assert "Village C" not in data["trend"]["keys"]

    # `villages` is the selector's option list and must keep offering all
    # three — the dropdown could not work otherwise.
    assert {v["label"] for v in data["villages"]} == {
        "Village A",
        "Village B",
        "Village C",
    }


def test_switching_between_villages_changes_the_data(admin_api, populated):
    a = admin_api.get(f"{OVERVIEW}?village=KVL").data
    b = admin_api.get(f"{OVERVIEW}?village=ARY").data
    c = admin_api.get(f"{OVERVIEW}?village=MLR").data
    everything = admin_api.get(f"{OVERVIEW}?village=all").data

    patients = [
        a["totals"]["patients"],
        b["totals"]["patients"],
        c["totals"]["patients"],
    ]
    assert patients == [3, 2, 1]
    assert everything["totals"]["patients"] == sum(patients)


def test_recent_activity_is_scoped_and_labelled(admin_api, populated):
    everywhere = admin_api.get(OVERVIEW).data["recent_activity"]
    assert {e["village_label"] for e in everywhere} == {
        "Village A",
        "Village B",
        "Village C",
    }

    just_b = admin_api.get(f"{OVERVIEW}?village=ARY").data["recent_activity"]
    assert just_b
    assert {e["village_label"] for e in just_b} == {"Village B"}


def test_signal_categories_reflect_the_selected_village(admin_api, populated):
    """Village B reported a skin concern; the others reported fever."""

    b = admin_api.get(f"{OVERVIEW}?village=ARY").data["signal_categories"]
    assert [row["category"] for row in b] == ["SKIN"]
    assert b[0]["described"] == 1

    a = admin_api.get(f"{OVERVIEW}?village=KVL").data["signal_categories"]
    assert [row["category"] for row in a] == ["FEVER"]


def test_expanded_category_vocabulary_is_available_to_admin(admin_api, populated):
    labels = {
        row["label"]
        for row in admin_api.get(OVERVIEW).data["signal_categories"]
    }
    assert "Skin conditions / infections" in labels


def test_trend_keys_differ_between_all_and_single_village(admin_api, populated):
    everything = admin_api.get(OVERVIEW).data["trend"]
    assert set(everything["keys"]) == {"Village A", "Village B", "Village C"}

    one = admin_api.get(f"{OVERVIEW}?village=ARY").data["trend"]
    assert one["keys"] == ["Skin conditions / infections"]


# ---------------------------------------------------------------------------
# Filter input handling
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["village_a", "Village A", "kvl", "KVL"])
def test_filter_accepts_code_or_label_spellings(admin_api, populated, value):
    data = admin_api.get(f"{OVERVIEW}?village={value}").data
    assert data["scope"]["label"] == "Village A"


@pytest.mark.parametrize("value", ["", "all", "ALL"])
def test_blank_or_all_means_every_village(admin_api, populated, value):
    data = admin_api.get(f"{OVERVIEW}?village={value}").data
    assert data["scope"]["mode"] == "all"


def test_unknown_village_returns_a_clean_error(admin_api, populated):
    response = admin_api.get(f"{OVERVIEW}?village=village_z")

    assert response.status_code == 400
    assert "Unknown village filter" in response.data["detail"]
    # The caller still gets the valid options back rather than a dead end.
    assert len(response.data["villages"]) == 3
    assert "Traceback" not in str(response.data)


# ---------------------------------------------------------------------------
# Empty states
# ---------------------------------------------------------------------------
def test_empty_platform_reports_empty_rather_than_breaking(admin_api, areas):
    data = admin_api.get(OVERVIEW).data

    assert data["is_empty"] is True
    assert data["totals"]["patients"] == 0
    assert data["alerts"] == []
    assert data["recent_activity"] == []
    assert data["trend"]["points"] == []
    assert data["signal_categories"] == []


def test_village_with_no_activity_is_handled(admin_api, areas, populated):
    quiet = Village.objects.create(
        code="QUI", name="Quiet Village", cluster="Village Cluster C"
    )
    data = admin_api.get(f"{OVERVIEW}?village={quiet.code}").data

    assert data["is_empty"] is True
    assert data["totals"]["patients"] == 0
    assert data["village_summary"][0]["status"] == "Normal"
    assert data["team"][0]["workers"] == []


def test_no_villages_configured_does_not_error(admin_api, db):
    assert admin_api.get(OVERVIEW).status_code == 200


# ---------------------------------------------------------------------------
# Existing isolation must be unaffected
# ---------------------------------------------------------------------------
def test_worker_and_officer_scoping_still_holds(populated, areas):
    """Adding a cross-village admin view must not widen anyone else's access."""

    worker = User.objects.get(username="worker.kvl")
    officer = User.objects.get(username="officer.kvl")

    worker_client = APIClient()
    worker_client.force_authenticate(user=worker)
    officer_client = APIClient()
    officer_client.force_authenticate(user=officer)

    codes = [p["patient_code"] for p in worker_client.get("/api/patients/").data]
    assert all(code.startswith("KVL") for code in codes)

    alerts = officer_client.get("/api/alerts/").data
    assert {a["village_code"] for a in alerts} == {"KVL"}

    # And neither can reach the admin overview.
    assert worker_client.get(OVERVIEW).status_code == 403
    assert officer_client.get(OVERVIEW).status_code == 403


def test_admin_keeps_its_existing_cross_village_access(admin_api, populated):
    """The admin could already see every village via the officer endpoints."""

    dashboard = admin_api.get("/api/officer/dashboard/")
    assert dashboard.status_code == 200
    assert dashboard.data["scope"]["is_district_wide"] is True


def test_admin_login_still_works(populated, platform_admin):
    client = APIClient()
    response = client.post(
        "/api/auth/login/",
        {"username": "admin", "password": "demo1234"},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["user"]["role"] == "ADMIN"

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    assert client.get(OVERVIEW).status_code == 200
