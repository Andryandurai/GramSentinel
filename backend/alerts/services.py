"""Running the community pipeline and persisting what it produced.

This is where Stage 3's reasoning, Stage 4's verdict and Stage 5's human-facing
output become database rows an officer can open.

The one behaviour worth reading closely: on a BLOCK verdict no Alert is
created. The SafetyCheck is still written, so the block is auditable, but the
finding does not reach a human as an alert. The engine's authority is real, not
cosmetic.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction

from agents.orchestration import CommunityOrchestrator
from community.aggregation import aggregated_individual_snapshot
from core.constants import SafetyVerdict, SignalCategory
from core.models import Village
from integrations.ingestion import build_agent_payloads, week_bounds_from_label

from .models import AgentRun, Alert, AlertEvidence, SafetyCheck

logger = logging.getLogger("gramsentinel.pipeline")

CATEGORY_TITLES = {
    SignalCategory.FEVER: "Fever-related signals rising",
    SignalCategory.RESPIRATORY: "Respiratory signals rising",
    SignalCategory.DIARRHOEAL: "Diarrhoeal signals rising",
    SignalCategory.OTHER: "Health signals rising",
}


def _persist_trace(result: dict[str, Any], village: Village, week_label: str) -> None:
    runs = [
        AgentRun(
            run_id=result["run_id"],
            stage=entry["stage"],
            agent_name=entry["agent"],
            agent_layer=entry["layer"],
            village=village,
            week_label=week_label,
            sequence=entry["sequence"],
            input_summary=entry["input_summary"],
            output=entry["output"],
            status=entry["status"],
            duration_ms=entry["duration_ms"],
            used_llm=entry["used_llm"],
        )
        for entry in result.get("agent_trace", [])
    ]
    AgentRun.objects.bulk_create(runs)


def _persist_evidence(alert: Alert, cards: list[dict[str, Any]]) -> None:
    AlertEvidence.objects.bulk_create(
        [
            AlertEvidence(
                alert=alert,
                source_kind=card["source_kind"],
                source_name=card.get("source_name", ""),
                category=card.get("category", ""),
                village_code=card.get("village_code", ""),
                week_label=card.get("week_label", ""),
                baseline=card.get("baseline"),
                current_value=card.get("current_value"),
                change_pct=card.get("change_pct"),
                unit=card.get("unit", ""),
                data_quality=card["data_quality"],
                status=card["status"],
                is_corroborating=bool(card.get("is_corroborating")),
                explanation=card.get("explanation", ""),
                produced_by_agent=card.get("produced_by_agent", ""),
            )
            for card in cards
        ]
    )


@transaction.atomic
def run_community_pipeline(
    village: Village,
    week_label: str,
    category: str = SignalCategory.FEVER,
) -> dict[str, Any]:
    """Six stages end to end for one village-week, persisted.

    Idempotent per (village, week, category): re-running replaces the previous
    alert and its evidence rather than stacking duplicates, so a demo can be
    re-run without polluting the dashboard.
    """

    period_start, period_end = week_bounds_from_label(week_label)

    source_payloads = build_agent_payloads(village, week_label, category)
    snapshot = aggregated_individual_snapshot(village, week_label)

    orchestrator = CommunityOrchestrator()
    result = orchestrator.run(
        village={
            "code": village.code,
            "name": village.name,
            "cluster": village.cluster,
            "district": village.district,
        },
        week_label=week_label,
        category=category,
        source_payloads=source_payloads,
        individual_snapshot=snapshot,
    )

    _persist_trace(result, village, week_label)

    safety = result["safety"]
    candidate = result["candidate_pattern"]
    cross = result["cross_level"]
    cards = result["evidence_cards"]

    # Re-running the same window supersedes the previous result.
    Alert.objects.filter(
        village=village, week_label=week_label, category=category
    ).delete()

    blocked = safety["verdict"] == SafetyVerdict.BLOCK
    nothing_to_raise = safety["corroborating_source_count"] == 0

    if blocked or nothing_to_raise:
        SafetyCheck.objects.create(
            alert=None,
            scope=SafetyCheck.Scope.COMMUNITY,
            verdict=safety["verdict"],
            passed=safety["passed"],
            status=safety["status"],
            rules=safety["rules_checked"],
            reasons=safety["reasons"],
            engine_version=safety["engine_version"],
            village=village,
            week_label=week_label,
        )
        reason = (
            "blocked by the deterministic safety engine"
            if blocked
            else "no independent source exceeded its baseline"
        )
        logger.info(
            "[PIPELINE] %s %s: no alert raised (%s)", village.code, week_label, reason
        )
        return {
            "alert": None,
            "alert_raised": False,
            "reason": reason,
            "safety": safety,
            "result": result,
        }

    alert = Alert.objects.create(
        village=village,
        cluster=village.cluster,
        category=category,
        week_label=week_label,
        period_start=period_start,
        period_end=period_end,
        title=f"{CATEGORY_TITLES.get(category, 'Health signals rising')} — {village.cluster}",
        summary=candidate.get("narrative", ""),
        severity=safety.get("severity") or Alert.Severity.LOW,
        confidence=safety.get("confidence", 0.0),
        corroborating_source_count=safety.get("corroborating_source_count", 0),
        cross_level_verdict=cross.get("verdict", ""),
        cross_level_statement=cross.get("statement", ""),
        safety_verdict=safety["verdict"],
        safety_status=safety["status"],
        status=Alert.Status.DETECTED,
        orchestration_run_id=result["run_id"],
        narrative_used_llm=result.get("used_llm", False),
    )

    _persist_evidence(alert, cards)

    SafetyCheck.objects.create(
        alert=alert,
        scope=SafetyCheck.Scope.COMMUNITY,
        verdict=safety["verdict"],
        passed=safety["passed"],
        status=safety["status"],
        rules=safety["rules_checked"],
        reasons=safety["reasons"],
        engine_version=safety["engine_version"],
        village=village,
        week_label=week_label,
    )

    logger.info(
        "[PIPELINE] %s %s: alert %s raised (%s / %s, %d corroborating sources)",
        village.code,
        week_label,
        alert.alert_uid,
        alert.severity,
        safety["verdict"],
        alert.corroborating_source_count,
    )

    _broadcast(alert)

    return {
        "alert": alert,
        "alert_raised": True,
        "reason": "",
        "safety": safety,
        "result": result,
    }


def _broadcast(alert: Alert) -> None:
    """Optional real-time nudge. Never load-bearing — polling works fine."""

    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        layer = get_channel_layer()
        if layer is None:
            return
        async_to_sync(layer.group_send)(
            "officer_alerts",
            {
                "type": "alert.created",
                "payload": {
                    "alert_uid": str(alert.alert_uid),
                    "title": alert.title,
                    "severity": alert.severity,
                    "cluster": alert.cluster,
                    "week_label": alert.week_label,
                    "safety_verdict": alert.safety_verdict,
                },
            },
        )
    except Exception as exc:  # noqa: BLE001 - real-time is best-effort only
        logger.debug("Real-time broadcast skipped: %s", exc)
