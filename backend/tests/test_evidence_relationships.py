"""Source agreement / disagreement — Evidence Relationships.

Exercises `alerts.evidence_relationships.build_evidence_relationships`
directly (unit-level classification) and through the `/api/alerts/<id>/
evidence/` endpoint it is wired into (integration-level: shape, and that a
village-scoped officer cannot reach another village's relationships).
"""

from __future__ import annotations

import pytest

from alerts.evidence_relationships import build_evidence_relationships
from core.constants import DataQuality, SignalCategory, SourceKind
from integrations.ingestion import ingest_batch

from .test_api import CORROBORATED, seed_alert

pytestmark = pytest.mark.django_db


def test_all_corroborating_sources_agree_when_all_rise(village, sources):
    """The original 5-source Kovilur-style scenario: CHW/PHC/PHARMACY/SCHOOL
    all rise together, so every comparable pair should AGREE, and WEATHER/LAB
    (different category in this implementation) should be NOT_COMPARABLE."""

    alert = seed_alert(village, sources)
    evidence = list(alert.evidence.all())

    result = build_evidence_relationships(alert, evidence)

    assert result["anchor"] is not None
    assert len(result["edges"]) == 3  # 4 comparable sources -> anchor + 3 edges
    assert all(e["relationship"] == "AGREE" for e in result["edges"])
    assert result["summary"] == {
        "agree_count": 3,
        "disagree_count": 0,
        "not_comparable_count": 2,
        "has_disagreement": False,
    }
    not_comparable_kinds = {c["source_kind"] for c in result["context"]}
    assert not_comparable_kinds == {SourceKind.WEATHER, SourceKind.LAB}


def test_single_source_disagrees_with_the_rest(village, sources):
    """Only PHC moves; CHW/PHARMACY/SCHOOL stay flat -> every edge disagrees
    with the PHC anchor, and each disagreement carries a non-fabricated,
    non-causal investigation note."""

    week_label = "2026-W33"
    ingest_batch(
        [
            {
                "source_code": sources[SourceKind.CHW].code,
                "category": SignalCategory.FEVER,
                "week_label": week_label,
                "value": 4,
                "baseline": 4,
                "is_reported": True,
                "data_quality": DataQuality.GOOD,
            },
            {
                "source_code": sources[SourceKind.PHC].code,
                "category": SignalCategory.FEVER,
                "week_label": week_label,
                "value": 20,
                "baseline": 12,
                "is_reported": True,
                "data_quality": DataQuality.GOOD,
            },
            {
                "source_code": sources[SourceKind.PHARMACY].code,
                "category": SignalCategory.FEVER,
                "week_label": week_label,
                "value": 141,
                "baseline": 140,
                "is_reported": True,
                "data_quality": DataQuality.GOOD,
            },
            {
                "source_code": sources[SourceKind.SCHOOL].code,
                "category": SignalCategory.FEVER,
                "week_label": week_label,
                "value": 5.0,
                "baseline": 5.0,
                "is_reported": True,
                "data_quality": DataQuality.GOOD,
            },
        ],
        week_label=week_label,
    )

    from alerts.services import run_community_pipeline

    outcome = run_community_pipeline(village, week_label, SignalCategory.FEVER)
    assert outcome["alert_raised"] is True
    alert = outcome["alert"]
    evidence = list(alert.evidence.all())

    result = build_evidence_relationships(alert, evidence)

    assert result["anchor"]["source_kind"] == SourceKind.PHC
    assert len(result["edges"]) == 3
    assert all(e["relationship"] == "DISAGREE" for e in result["edges"])
    assert result["summary"]["has_disagreement"] is True
    for edge in result["edges"]:
        assert edge["investigate"] is not None
        assert "investigate why" in edge["investigate"].lower()
        # Never claims causality or that one source is wrong — the opposite
        # is stated explicitly instead.
        assert "proves" not in edge["reason"].lower()
        assert "does not mean either source is wrong" in edge["investigate"].lower()


def test_not_reported_source_is_not_comparable_not_fabricated(village, sources):
    """A source that did not submit must never be silently compared as if it
    agreed or disagreed — it has to show up as NOT_COMPARABLE with a reason
    that says it did not report, not as a fabricated relationship."""

    week_label = "2026-W34"
    ingest_batch(
        [
            {
                "source_code": sources[SourceKind.CHW].code,
                "category": SignalCategory.FEVER,
                "week_label": week_label,
                "value": 12,
                "baseline": 5,
                "is_reported": True,
                "data_quality": DataQuality.GOOD,
            },
            {
                "source_code": sources[SourceKind.PHC].code,
                "category": SignalCategory.FEVER,
                "week_label": week_label,
                "value": None,
                "baseline": None,
                "is_reported": False,
            },
        ],
        week_label=week_label,
    )

    from alerts.services import run_community_pipeline

    outcome = run_community_pipeline(village, week_label, SignalCategory.FEVER)
    assert outcome["alert_raised"] is True
    alert = outcome["alert"]
    evidence = list(alert.evidence.all())

    result = build_evidence_relationships(alert, evidence)

    # Only CHW is directly comparable (PHC did not report); no edges possible.
    assert result["edges"] == []
    not_reported = [c for c in result["context"] if c["source_kind"] == SourceKind.PHC]
    assert not_reported, "PHC should be listed as not-comparable context"
    assert "did not submit" in not_reported[0]["reason"]


def test_evidence_endpoint_exposes_relationships(officer_api, village, sources):
    alert = seed_alert(village, sources)
    response = officer_api.get(f"/api/alerts/{alert.id}/evidence/")

    assert response.status_code == 200
    relationships = response.data["relationships"]
    assert relationships["anchor"]["source_kind"] in {
        SourceKind.CHW,
        SourceKind.PHC,
        SourceKind.PHARMACY,
        SourceKind.SCHOOL,
    }
    assert relationships["summary"]["agree_count"] == 3
    assert len(relationships["edges"]) == 3
    for edge in relationships["edges"]:
        assert edge["relationship_label"] in {"Agrees", "Disagrees"}
        assert edge["statement"]
        assert edge["reason"]


def test_relationships_are_village_scoped(api, village, other_village, sources):
    """A village-scoped officer must not be able to read another village's
    evidence relationships by guessing the alert id — same isolation rule
    already enforced for the rest of the alert endpoints."""

    from django.contrib.auth import get_user_model

    from community.models import DataSource

    User = get_user_model()
    scoped_officer = User.objects.create_user(
        username="officer.scoped",
        password="demo1234",
        role=User.Role.HEALTH_OFFICER,
        full_name="Village-scoped Officer",
        village=village,
        district="Thiruvannamalai",
    )
    api.force_authenticate(user=scoped_officer)

    other_sources = {
        kind: DataSource.objects.create(
            code=f"{kind}-{other_village.code}",
            name=f"{kind} — {other_village.name}",
            kind=kind,
            channel=source.channel,
            village=other_village,
        )
        for kind, source in sources.items()
    }
    other_alert = seed_alert(other_village, other_sources, week_label="2026-W40")

    response = api.get(f"/api/alerts/{other_alert.id}/evidence/")
    assert response.status_code == 404
