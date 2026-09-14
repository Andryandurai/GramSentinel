"""Phase 7 — What-If Simulation: isolated rerun of the real pipeline
against hypothetical synthetic inputs.

The central invariant (task §11/§36): "What-If = what would happen if the
synthetic inputs changed?" Unlike Replay, this DOES rerun computation — but
only the SAME `simulation.orchestrator.MultiAgentOrchestrator` (Phase 4)
and `simulation.safety.SafetyEngine` (Phase 6) every real `advance()` call
already uses. No second scoring algorithm exists anywhere in this module.

Isolation strategy: the hypothetical event/source-signal rows are REAL,
saveable Django model instances — not hand-rolled stand-ins — so the
unmodified Phase 4 stage functions (`event.per_source_signals.all()`,
`row.source_type`/`.value`/`.reported`) work exactly as written, with zero
special-casing. They are created under a throwaway, unsaved-after-return
`SimulationSession` (`health_officer=None`, never the officer's real
session) inside one `transaction.atomic()` block that ALWAYS ends in
`transaction.set_rollback(True)` — nothing survives the request, by a
database guarantee rather than by this module's own bookkeeping. Even
before that rollback, the throwaway rows are structurally invisible to the
real session: `simulation.intelligence.build_intelligence` and
`SafetyEngine` only ever look at the officer's REAL session and the
scenario's REAL template session, never at this throwaway one.

Only the current week's SOURCE VALUES are hypothetical. The category
totals in `source_signals["categories"]` (what Signal Analysis classifies
a trend from) are copied unchanged from the real week — there is no
schema-level mapping from a `SourceKind` to a `SignalCategory` to
recompute from, and the task's own Original-vs-Hypothetical examples never
show a changed trend, only changed correlation/evidence-strength/safety.
Overriding a source's value CAN still change the result: Correlation
compares that source's own new direction against the (unchanged) primary
trend's direction, which can flip SUPPORTING/CONFLICTING and, in turn, the
deterministic evidence strength.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from rest_framework.exceptions import APIException

from .intelligence import _compute_data_quality, _evidence_strength, build_intelligence
from .investigation import suggested_decision
from .models import (
    EvidenceStrength,
    SimulationEvent,
    SimulationSession,
    SimulationSourceSignal,
    get_template_session,
)
from .orchestrator import MultiAgentOrchestrator, RELATIONSHIP_CONFLICTING, RELATIONSHIP_SUPPORTING
from .replay import _persisted_safety_for_week
from .safety import SafetyEngine
from .services import SimulationVillageMismatch, officer_may_access_village


class WhatIfValidationError(APIException):
    """A structurally-valid request that fails a What-If-specific business
    rule (unknown source type, no current week, malformed override) — a
    400, distinct from the 403 `SimulationVillageMismatch` raises."""

    status_code = 400
    default_detail = "This What-If request could not be evaluated."
    default_code = "simulation_what_if_invalid"


def _reshape_sources(rows) -> dict[str, dict[str, Any]]:
    return {row.source_type: {"value": row.value, "reported": row.reported} for row in rows}


class WhatIfEngine:
    """No instance state — same `classmethod`-only shape as
    `SimulationEngine`/`SafetyEngine`."""

    @classmethod
    def run(cls, session: SimulationSession, officer: Any, overrides: dict[str, float | None]) -> dict[str, Any]:
        # Object-level check #3 (task §31/§49) — independent of whatever
        # permission/view-layer check already ran, same rule every other
        # session method re-verifies.
        if not officer_may_access_village(session.village_id, officer):
            raise SimulationVillageMismatch()

        current_week = session.replay_position
        if current_week < 1:
            raise WhatIfValidationError(
                detail="This session has no current reporting week to run What-If against."
            )

        template = get_template_session(session.scenario)
        if template is None:
            raise WhatIfValidationError(detail="This scenario has no seeded timeline.")

        real_event = (
            template.events.filter(week_number=current_week)
            .prefetch_related("per_source_signals")
            .first()
        )
        if real_event is None:
            raise WhatIfValidationError(
                detail="The current reporting week has no recorded data to run What-If against."
            )
        previous_event = template.events.filter(week_number=current_week - 1).first()

        real_rows = list(real_event.per_source_signals.all())
        real_sources = {row.source_type: row for row in real_rows}

        # Business validation (task §24/§25): only source types this
        # session's current week actually has may be overridden — this is
        # an allowlist derived from real data, not a blocklist of
        # forbidden field names, so `village_id`/`officer_id`/patient/
        # operational identifiers are rejected the same way any other
        # unrecognised key would be, with no special-casing required.
        unknown = sorted(set(overrides) - set(real_sources))
        if unknown:
            raise WhatIfValidationError(
                detail=f"Unsupported source type(s) for this session: {', '.join(unknown)}."
            )

        prior_events = list(
            template.events.filter(week_number__lt=current_week)
            .order_by("week_number")
            .prefetch_related("per_source_signals")
        )

        hypothetical_sources: dict[str, dict[str, Any]] = {}

        with transaction.atomic():
            temp_session = SimulationSession.objects.create(
                scenario=session.scenario,
                village=session.village,
                health_officer=None,
                status=SimulationSession.Status.IN_PROGRESS,
                replay_position=current_week,
            )
            temp_event = SimulationEvent.objects.create(
                session=temp_session,
                village=session.village,
                week_number=current_week,
                source_signals=dict(real_event.source_signals),
                is_synthetic=True,
            )
            for source_type, real_row in real_sources.items():
                if source_type in overrides:
                    value = overrides[source_type]
                    reported = value is not None
                else:
                    value, reported = real_row.value, real_row.reported
                SimulationSourceSignal.objects.create(
                    event=temp_event,
                    village=session.village,
                    source_type=source_type,
                    value=value,
                    reported=reported,
                )
                hypothetical_sources[source_type] = {"value": value, "reported": reported}

            # The REAL Phase 4 pipeline, unmodified — no second scoring
            # algorithm (task §14).
            pipeline_results = MultiAgentOrchestrator.run_pipeline(temp_event, previous_event)
            by_agent = {result["agent"]: result for result in pipeline_results}

            correlation_output = by_agent.get("correlation", {}).get("output", {})
            relationships = (
                correlation_output.get("relationships", [])
                if by_agent.get("correlation", {}).get("status") == "COMPLETE"
                else []
            )
            constellation = [
                {"source": r["source"], "relation": r["relationship"], "reason": r["reason"]}
                for r in relationships
            ]
            supporting = sum(1 for c in constellation if c["relation"] == RELATIONSHIP_SUPPORTING)
            conflicting = sum(1 for c in constellation if c["relation"] == RELATIONSHIP_CONFLICTING)

            signal_output = by_agent.get("signal_analysis", {}).get("output", {})
            trend = (
                signal_output.get("trend")
                if by_agent.get("signal_analysis", {}).get("status") == "COMPLETE"
                else None
            )
            preliminary_strength = (
                _evidence_strength(trend, supporting, conflicting) if trend else EvidenceStrength.WEAK
            )

            # Same Phase 5 completeness formula, applied to the REAL prior
            # weeks plus the hypothetical current-week event in place of
            # the real one (task §27: "do not invent a new completeness
            # formula").
            data_quality = _compute_data_quality(prior_events + [temp_event])

            # `sources_conflicting`/`sources_supporting` are derived from
            # `constellation` the exact same way `simulation.intelligence
            # .build_intelligence()` already derives them for the real
            # payload (task §32: "avoid duplicate computation") — needed
            # so `suggested_decision()` below (reused unmodified from
            # Phase 9/10) can read them, since a hand-built override dict
            # would otherwise be missing keys that function expects.
            intelligence_override = {
                "constellation": constellation,
                "data_quality": data_quality,
                "explanation": {
                    "evidence_strength": preliminary_strength,
                    "sources_conflicting": [
                        c["source"] for c in constellation if c["relation"] == RELATIONSHIP_CONFLICTING
                    ],
                    "sources_supporting": [
                        c["source"] for c in constellation if c["relation"] == RELATIONSHIP_SUPPORTING
                    ],
                },
            }

            # The REAL Phase 6 SafetyEngine, unmodified, run again — never
            # skipped, never assumed to match the original result (task
            # §16/§29). `session`/`officer` here are the REAL ones, so
            # Rule 1 (village scope) and Rule 2 (reporting period) still
            # validate against genuine authorization/history, not the
            # throwaway rows.
            safety_result = SafetyEngine.evaluate(
                session,
                officer,
                ingestion_output=by_agent.get("ingestion", {}).get("output", {}),
                signal_output=signal_output,
                correlation_output=correlation_output,
                evidence_output=by_agent.get("evidence", {}).get("output", {}),
                intelligence_override=intelligence_override,
            )

            # Same reused `suggested_decision()` the real `.../intelligence/`
            # and `.../replay/` endpoints call — evaluated against the
            # HYPOTHETICAL intelligence/safety only, never persisted, never
            # a second recommendation algorithm.
            hypothetical_suggested_next_step = suggested_decision(intelligence_override, safety_result)

            # Nothing above may survive this request — this is what makes
            # the isolation a database guarantee rather than a promise
            # (task §17/§18).
            transaction.set_rollback(True)

        original_safety = _persisted_safety_for_week(session, current_week)

        # Original-side comparison figures — read the SAME way Replay reads
        # any already-computed week (`build_intelligence(as_of_week=...)`,
        # this module's own import above), never recomputed: the real
        # week's constellation/timeline are already fully determined by
        # what `advance()` persisted, exactly as Replay already treats them
        # (task §9: "use actual values produced by the existing pipeline").
        original_intelligence = build_intelligence(session, as_of_week=current_week)
        original_constellation = original_intelligence["constellation"]
        original_week_entry = next(
            (w for w in original_intelligence["timeline"] if w["week"] == current_week), None
        )
        original_payload = {
            "sources": _reshape_sources(real_rows),
            "trend": original_week_entry["status"] if original_week_entry else None,
            "constellation": original_constellation,
            "supporting_count": sum(
                1 for c in original_constellation if c["relation"] == RELATIONSHIP_SUPPORTING
            ),
            "conflicting_count": sum(
                1 for c in original_constellation if c["relation"] == RELATIONSHIP_CONFLICTING
            ),
            "missing_count": sum(
                1 for row in real_rows if not row.reported
            ),
            "gate_result": original_safety.get("gate_result") if original_safety else None,
            "evidence_strength": original_safety.get("evidence_strength") if original_safety else None,
            "human_review_required": True,
        }

        hypothetical_payload = {
            "sources": hypothetical_sources,
            "primary_signal": signal_output.get("primary_signal"),
            "trend": trend,
            "constellation": constellation,
            "supporting_count": supporting,
            "conflicting_count": conflicting,
            "missing_count": sum(
                1 for source in hypothetical_sources.values() if not source["reported"]
            ),
            "data_quality": data_quality,
            "pipeline": [
                {
                    "agent": result["agent"],
                    "status": result["status"],
                    "output": result["output"],
                }
                for result in pipeline_results
            ],
            "safety": safety_result,
            "suggested_next_step": hypothetical_suggested_next_step,
        }

        changed_sources = sorted(
            source_type
            for source_type, hypothetical_value in hypothetical_sources.items()
            if hypothetical_value != original_payload["sources"].get(source_type)
        )

        return {
            "week": current_week,
            "is_hypothetical": True,
            "original": original_payload,
            "hypothetical": hypothetical_payload,
            "changed_sources": changed_sources,
        }
