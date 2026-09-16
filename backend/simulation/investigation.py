"""Phase 9 — Investigation Notebook.

Pure derive/persist logic over data Phase 4/5/6 already computed. Nothing
here recomputes a trend, a source relationship, a completeness percentage,
or a safety verdict — it only reshapes/labels `simulation.intelligence
.build_intelligence()`'s and `SafetyEngine`'s existing output for an
investigation workspace, and manages the officer's own notes/checklist/
observations/decision on the session's one `SimulationInvestigation` row.
No LLM is ever consulted here (task §28/§45: "keep PDF generation
deterministic. Do not call an LLM just to generate a report" — the same is
true of every other function in this module).
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from django.utils import timezone

from .models import (
    InvestigationDecision,
    SafetyGateResult,
    SimulationFeedback,
    SimulationInvestigation,
    SimulationSession,
    get_template_session,
)

# ---------------------------------------------------------------------------
# Checklist — task §18: only show items relevant to THIS session's actual
# sources, never a fixed list assumed to exist for every scenario.
# ---------------------------------------------------------------------------
_FIXED_CHECKLIST_ITEMS: tuple[tuple[str, str], ...] = (
    ("timeline_reviewed", "Reviewed signal timeline"),
    ("missing_data_reviewed", "Reviewed missing data"),
    ("contradictions_reviewed", "Reviewed contradictory evidence"),
    ("community_context_reviewed", "Reviewed community context"),
    ("field_observations_reviewed", "Reviewed field observations"),
    ("human_verification_completed", "Human verification completed"),
)

_SOURCE_CHECKLIST_LABEL: dict[str, str] = {
    "CHW": "Reviewed CHW evidence",
    "PHC": "Reviewed PHC evidence",
    "PHARMACY": "Reviewed pharmacy evidence",
    "SCHOOL": "Reviewed school signal",
    "WEATHER": "Reviewed weather/environment evidence",
    "LAB": "Reviewed laboratory evidence",
    "RURALCARE_AGGREGATE": "Reviewed aggregated RuralCare signal",
}


def checklist_items(intelligence: dict[str, Any]) -> list[dict[str, str]]:
    """The checklist SHAPE for this session right now — always freshly
    derived from `intelligence["data_quality"]["sources"]` (never a
    hardcoded universal list), plus the fixed non-source items. A session
    with only CHW/PHC sources never shows a pharmacy or lab item."""

    items = [
        {
            "key": f"source_{source['source']}",
            "label": _SOURCE_CHECKLIST_LABEL.get(
                source["source"], f"Reviewed {source['source']} evidence"
            ),
        }
        for source in intelligence.get("data_quality", {}).get("sources", [])
    ]
    items.extend({"key": key, "label": label} for key, label in _FIXED_CHECKLIST_ITEMS)
    return items


def normalize_checklist(raw: dict[str, Any] | None, items: list[dict[str, str]]) -> dict[str, bool]:
    """Never trusts a persisted or client-supplied shape wholesale: only
    keys that belong to THIS session's current item set survive, and every
    expected key is always present (absent = not yet reviewed) — the
    frontend never has to guess whether a missing key means false or
    "not asked yet" (task §39/§40: no arbitrary keys accepted)."""

    raw = raw or {}
    return {item["key"]: bool(raw.get(item["key"], False)) for item in items}


def compute_progress(checklist: dict[str, bool]) -> dict[str, int]:
    total = len(checklist)
    checked = sum(1 for value in checklist.values() if value)
    percent = round(checked / total * 100) if total else 0
    return {"checked": checked, "total": total, "percent": percent}


# ---------------------------------------------------------------------------
# Activity history — server-derived only (task §26/§41).
# ---------------------------------------------------------------------------
def append_activity(investigation: SimulationInvestigation, event_type: str, actor: Any) -> None:
    """Appends one `{timestamp, event_type, actor}` entry to `investigation
    .activity_history` in place. Does not save — callers persist this
    alongside whatever else changed in the same request, one write instead
    of two. `actor` is always the authenticated `request.user`, never a
    client-supplied value."""

    actor_label = getattr(actor, "username", None) or "system"
    history = list(investigation.activity_history or [])
    history.append(
        {
            "timestamp": timezone.now().isoformat(),
            "event_type": event_type,
            "actor": actor_label,
        }
    )
    investigation.activity_history = history


# ---------------------------------------------------------------------------
# Overview / contradictions / suggested decision — all reshape existing
# Phase 5/6 output; none of this recomputes anything (task §8/§12/§36).
# ---------------------------------------------------------------------------
def build_overview(
    session: SimulationSession,
    investigation: SimulationInvestigation,
    intelligence: dict[str, Any],
    safety: dict[str, Any],
) -> dict[str, Any]:
    template = get_template_session(session.scenario)
    total_weeks = template.events.count() if template is not None else 0
    explanation = intelligence.get("explanation", {})
    timeline = intelligence.get("timeline", [])
    latest_point = timeline[-1] if timeline else None
    latest_result = session.results.order_by("-created_at").first()

    return {
        "investigation_id": investigation.id,
        "session_id": session.id,
        "village_code": session.village.code,
        "village_name": session.village.name,
        "scenario_name": session.scenario.name,
        "week": session.replay_position,
        "total_weeks": total_weeks,
        "status": investigation.status,
        "status_display": investigation.get_status_display(),
        "primary_signal": latest_point["primary_signal"] if latest_point else None,
        "trend": latest_point["status"] if latest_point else None,
        "evidence_strength": explanation.get("evidence_strength"),
        "investigation_priority": latest_result.investigation_priority if latest_result else "",
        "safety_gate_result": safety.get("gate_result"),
        "sources_supporting": explanation.get("sources_supporting", []),
        "sources_conflicting": explanation.get("sources_conflicting", []),
        "sources_insufficient": explanation.get("sources_insufficient", []),
        "why_am_i_seeing_this": explanation.get("routed_reason"),
    }


#: Fixed, generic investigation prompts (task §13: "these are investigation
#: prompts, NOT causal conclusions") — never source-specific, never a
#: causal claim like "X caused Y".
_VERIFICATION_PROMPTS: tuple[str, ...] = (
    "Verify the reporting period aligns across sources.",
    "Check whether the source populations differ.",
    "Check for delayed or backlogged reporting.",
    "Verify data completeness for the conflicting source.",
    "Check whether the sample size is sufficient to compare.",
)


def build_contradictions(intelligence: dict[str, Any]) -> list[dict[str, Any]]:
    """Every CONFLICTING entry from Phase 4's own correlation output
    (`source_fusion`, Phase 5's per-source read of it) — never a second
    correlation pass, never a source-to-source causal claim, only the
    already-computed `reason` text plus fixed verification prompts."""

    return [
        {
            "source": entry["source"],
            "relation": entry["relation"],
            "reason": entry["reason"],
            "current_value": entry.get("current_value"),
            "reported": entry.get("reported"),
            "suggested_verification": list(_VERIFICATION_PROMPTS),
        }
        for entry in intelligence.get("source_fusion", [])
        if entry.get("relation") == "CONFLICTING"
    ]


def build_community_context(
    session: SimulationSession, as_of_week: int | None = None
) -> list[dict[str, Any]]:
    """Reads the OPTIONAL `context` list some seeded weeks carry inside
    their existing `SimulationEvent.source_signals` JSON blob (task §15:
    "only use existing scenario context, seeded synthetic context" — never
    invented per-request). Deliberately NOT part of `build_intelligence()`'s
    return shape: that dict is Phase 5's own frozen contract, and this
    feature must never change it — this is a Phase 9-only read over the
    exact same revealed-events window Phase 5 already uses.
    """

    template = get_template_session(session.scenario)
    if template is None:
        return []
    effective_week = session.replay_position if as_of_week is None else as_of_week
    revealed_events = template.events.filter(week_number__lte=effective_week).order_by("week_number")
    entries: list[dict[str, Any]] = []
    for event in revealed_events:
        for note in event.source_signals.get("context", []):
            entries.append({"week": event.week_number, "note": note})
    return entries


def suggested_decision(intelligence: dict[str, Any], safety: dict[str, Any]) -> str:
    """A single, deterministic, non-binding suggestion (task §21: "the
    system must never silently select the officer's decision" — this value
    is displayed as a suggestion only; `POST .../decision/` never reads or
    trusts it). Empty string while Safety is BLOCK: there is nothing to
    suggest investigating further."""

    gate_result = safety.get("gate_result")
    if gate_result == SafetyGateResult.BLOCK:
        return ""

    explanation = intelligence.get("explanation", {})
    evidence_strength = explanation.get("evidence_strength")
    conflicting = explanation.get("sources_conflicting", [])
    completeness = intelligence.get("data_quality", {}).get("completeness_pct", 100)

    if completeness < 80:
        return InvestigationDecision.REQUEST_MORE_DATA
    if conflicting:
        return (
            InvestigationDecision.VERIFY_WITH_PHC
            if "PHC" in conflicting
            else InvestigationDecision.REQUEST_MORE_DATA
        )
    if evidence_strength == "STRONG":
        return InvestigationDecision.CONDUCT_FIELD_VERIFICATION
    if evidence_strength == "WEAK":
        return InvestigationDecision.CLOSE_AS_INSUFFICIENT_EVIDENCE
    return InvestigationDecision.CONTINUE_MONITORING


# ---------------------------------------------------------------------------
# Feedback (Phase 10) — task §5/§6/§10. An evaluation layer only: nothing
# here is read by `SafetyEngine`, `MultiAgentOrchestrator`, or
# `SimulationEngine`, and nothing here can change `SimulationResult`/
# `SimulationInvestigation.decision` (task §41-§43). "Missing feedback" and
# "negative feedback" are always kept structurally distinct — `submitted:
# False` is a different value from any real choice, never coerced into
# one (task §23: "missing != not useful").
# ---------------------------------------------------------------------------
def feedback_payload(feedback: SimulationFeedback | None) -> dict[str, Any]:
    if feedback is None:
        return {
            "submitted": False,
            "usefulness": "",
            "evidence_sufficiency": "",
            "recommendation_helpful": "",
            "additional_verification_required": "",
            "comment": "",
            "officer": None,
            "updated_at": None,
        }
    return {
        "submitted": True,
        "usefulness": feedback.usefulness,
        "evidence_sufficiency": feedback.evidence_sufficiency,
        "recommendation_helpful": feedback.recommendation_helpful,
        "additional_verification_required": feedback.additional_verification_required,
        "comment": feedback.comment,
        "officer": feedback.officer.username if feedback.officer else None,
        "updated_at": feedback.updated_at,
    }


# ---------------------------------------------------------------------------
# PDF export (task §27/§28/§37) — deterministic, reportlab, no LLM.
# ---------------------------------------------------------------------------
def build_investigation_report_pdf(
    session: SimulationSession,
    investigation: SimulationInvestigation,
    intelligence: dict[str, Any],
    safety: dict[str, Any],
    feedback: SimulationFeedback | None = None,
) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], spaceAfter=4)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], spaceBefore=14, spaceAfter=6)
    body = styles["BodyText"]
    small = ParagraphStyle("Small", parent=styles["BodyText"], fontSize=8, textColor=colors.grey)

    overview = build_overview(session, investigation, intelligence, safety)
    contradictions = build_contradictions(intelligence)
    checklist = normalize_checklist(investigation.checklist, checklist_items(intelligence))
    progress = compute_progress(checklist)

    story: list[Any] = []
    story.append(Paragraph("GRAMSENTINEL", h1))
    story.append(Paragraph("Investigation Notebook", styles["Heading2"]))
    story.append(
        Paragraph(
            "SYNTHETIC SIMULATION — DEMONSTRATION ONLY — NOT REAL SURVEILLANCE DATA",
            small,
        )
    )
    story.append(Spacer(1, 0.15 * inch))

    summary_rows = [
        ["Village", overview["village_name"]],
        ["Scenario", overview["scenario_name"]],
        ["Investigation ID", str(overview["investigation_id"])],
        ["Current week", f"{overview['week']} / {overview['total_weeks']}"],
        ["Signal category", overview["primary_signal"] or "—"],
        ["Trend", overview["trend"] or "—"],
        ["Evidence strength", overview["evidence_strength"] or "—"],
        ["Safety result", overview["safety_gate_result"] or "—"],
        ["Investigation priority", overview["investigation_priority"] or "—"],
    ]
    story.append(Table(summary_rows, colWidths=[2.2 * inch, 3.8 * inch], style=_TABLE_STYLE))

    story.append(Paragraph("SIGNAL TIMELINE", h2))
    timeline = intelligence.get("timeline", [])
    if timeline:
        rows = [["Week", "Value", "Trend"]] + [
            [str(point["week"]), "—" if point["value"] is None else str(point["value"]), point["status"]]
            for point in timeline
        ]
        story.append(Table(rows, colWidths=[1.3 * inch, 1.3 * inch, 2.3 * inch], style=_TABLE_STYLE))
    else:
        story.append(Paragraph("No reporting weeks recorded yet.", body))

    story.append(Paragraph("SOURCE EVIDENCE", h2))
    source_fusion = intelligence.get("source_fusion", [])
    if source_fusion:
        rows = [["Source", "Relation", "Value", "Reason"]] + [
            [
                entry["source"],
                entry["relation"],
                "—" if entry.get("current_value") is None else str(entry["current_value"]),
                entry["reason"],
            ]
            for entry in source_fusion
        ]
        story.append(Table(rows, colWidths=[1 * inch, 1.1 * inch, 0.8 * inch, 3 * inch], style=_TABLE_STYLE))
    else:
        story.append(Paragraph("No source evidence available yet.", body))

    story.append(Paragraph("CONTRADICTIONS", h2))
    if contradictions:
        for entry in contradictions:
            story.append(Paragraph(f"<b>{entry['source']}</b> — {entry['reason']}", body))
    else:
        story.append(Paragraph("No conflicting source relationship detected.", body))

    story.append(Paragraph("DATA QUALITY", h2))
    dq = intelligence.get("data_quality", {})
    story.append(
        Paragraph(
            f"Completeness: {dq.get('completeness_pct', 0)}% over {dq.get('window_label', '—')}. "
            f"Missing: {', '.join(dq.get('missing', [])) or 'none recorded'}.",
            body,
        )
    )

    story.append(Paragraph("COMMUNITY CONTEXT", h2))
    context_entries = build_community_context(session)
    if context_entries:
        for entry in context_entries:
            story.append(Paragraph(f"Week {entry['week']}: {entry['note']} (SYNTHETIC SIMULATION CONTEXT)", body))
    else:
        story.append(Paragraph("No synthetic community context recorded for this scenario.", body))

    story.append(Paragraph("FIELD OBSERVATIONS", h2))
    if investigation.observations:
        for obs in investigation.observations:
            story.append(
                Paragraph(
                    f"Week {obs.get('week', '—')} · {obs.get('source', 'Field')}: "
                    f"{obs.get('notes', '')} (SIMULATED FIELD OBSERVATION)",
                    body,
                )
            )
    else:
        story.append(Paragraph("No simulated field observations recorded.", body))

    story.append(Paragraph("INVESTIGATION NOTES", h2))
    story.append(Paragraph(investigation.officer_notes or "No notes recorded.", body))

    story.append(Paragraph("VERIFICATION CHECKLIST", h2))
    story.append(
        Paragraph(f"{progress['checked']} / {progress['total']} completed ({progress['percent']}%)", body)
    )
    for item in checklist_items(intelligence):
        mark = "[x]" if checklist.get(item["key"]) else "[ ]"
        story.append(Paragraph(f"{mark} {item['label']}", body))

    story.append(Paragraph("OFFICER DECISION", h2))
    if investigation.decision:
        decided_by = investigation.decided_by.display_name if investigation.decided_by else "—"
        story.append(
            Paragraph(
                f"{investigation.get_decision_display()} — recorded by {decided_by} "
                f"on {investigation.decided_at.strftime('%Y-%m-%d %H:%M') if investigation.decided_at else '—'}.",
                body,
            )
        )
        if investigation.decision_reason:
            story.append(Paragraph(investigation.decision_reason, body))
    else:
        story.append(Paragraph("No decision has been recorded yet.", body))

    story.append(Paragraph("FINAL RECOMMENDATION", h2))
    story.append(Paragraph(intelligence.get("explanation", {}).get("suggested_verification", "—"), body))

    # Only included if it exists (task §37: "Only include feedback if it
    # exists") — an evaluation layer, never presented as ground truth.
    if feedback is not None:
        story.append(Paragraph("OFFICER FEEDBACK", h2))
        story.append(Paragraph("Officer assessment — not a clinical or ground-truth verdict.", small))
        fb_rows = [
            ["Signal usefulness", feedback.get_usefulness_display() if feedback.usefulness else "—"],
            [
                "Evidence sufficiency",
                feedback.get_evidence_sufficiency_display() if feedback.evidence_sufficiency else "—",
            ],
            [
                "Recommendation helpful",
                feedback.get_recommendation_helpful_display()
                if feedback.recommendation_helpful
                else "—",
            ],
            [
                "Additional verification required",
                feedback.get_additional_verification_required_display()
                if feedback.additional_verification_required
                else "—",
            ],
        ]
        story.append(Table(fb_rows, colWidths=[2.6 * inch, 3.4 * inch], style=_TABLE_STYLE))
        if feedback.comment:
            story.append(Paragraph(feedback.comment, body))

    story.append(Spacer(1, 0.3 * inch))
    story.append(
        Paragraph(
            "SYNTHETIC SIMULATION · DEMONSTRATION ONLY · NOT REAL SURVEILLANCE DATA · "
            "No real patient, pharmacy, school, or laboratory data is used.",
            small,
        )
    )

    buffer = BytesIO()
    SimpleDocTemplate(buffer, pagesize=LETTER, title="GramSentinel Investigation Notebook").build(story)
    return buffer.getvalue()


def _table_style():
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle

    return TableStyle(
        [
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
        ]
    )


_TABLE_STYLE = _table_style()
