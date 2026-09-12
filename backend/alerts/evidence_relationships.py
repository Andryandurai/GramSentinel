"""Source agreement / disagreement — read-only analysis of existing evidence.

No new data model. Every relationship is derived purely from `AlertEvidence`
rows already persisted by the community pipeline (`alerts/services.py`): the
same `category`, `status`, `change_pct`, `baseline` and `current_value` fields
the Evidence View already renders card-by-card. This module just states the
relationships between those cards explicitly instead of leaving an officer to
notice them by eye.

Comparability, grounded in the existing implementation (not invented):

  - Two cards are "directly comparable" only when both share the ALERT'S OWN
    category and both have a determinable direction (ANOMALY_DETECTED or
    NORMAL — the only two statuses `BaseSignalAgent.handle()` can produce once
    a baseline exists). Every corroborating source kind (CHW, PHC, PHARMACY,
    SCHOOL) is tagged with the alert's own category by `build_agent_payloads`,
    so this is the natural, already-existing basis for "same phenomenon".
  - WEATHER is always tagged category=ENVIRONMENT and LAB is always tagged
    category=LAB_CONFIRMATION (see `integrations/ingestion.py`), never the
    alert's own category in the current implementation — so neither is
    directly comparable to the category-specific sources. This mirrors the
    codebase's own `CONTEXT_SOURCE_KINDS` / `CORROBORATING_SOURCE_KINDS` split
    for WEATHER, and is a genuine limitation (not a design choice made here)
    for LAB: this implementation does not tie a lab confirmation count to the
    specific reported category.
  - A card with status NOT_REPORTED or INSUFFICIENT_DATA has no usable
    direction, so it is never compared either.

Relationship classification, relative to a single "anchor" card (the most
anomalous directly-comparable source, i.e. what most likely drove the alert):
AGREE when another comparable source shows the same direction, DISAGREE when
it shows a different one. This keeps the diagram a small hub-and-spoke
(N-1 edges for N comparable sources) rather than an all-pairs mesh, per the
"clean, not unnecessarily complicated" requirement.
"""

from __future__ import annotations

from typing import Any

from core.constants import EvidenceStatus, SourceKind

#: Statuses with a determinable "did this go up or not" direction. Anything
#: else (NOT_REPORTED, INSUFFICIENT_DATA, or the context-only
#: SUPPORTING_CONTEXT / non-category CORROBORATING statuses that only WEATHER
#: and LAB can produce) is handled as "not directly comparable" instead.
_DIRECTIONAL_STATUSES = {EvidenceStatus.ANOMALY_DETECTED, EvidenceStatus.NORMAL}

AGREE = "AGREE"
DISAGREE = "DISAGREE"
NOT_COMPARABLE = "NOT_COMPARABLE"

_NOT_COMPARABLE_REASONS = {
    SourceKind.WEATHER: (
        "Weather/rainfall is recorded as environmental context in this "
        "implementation, not as a signal for a specific reported category, so "
        "it is not compared for agreement or disagreement."
    ),
    SourceKind.LAB: (
        "Laboratory evidence in this implementation is a generic confirmation "
        "count for the window, not tied to the specific reported category, so "
        "it is not compared for agreement or disagreement."
    ),
    SourceKind.RURALCARE_AGGREGATE: (
        "This is the anonymised RuralCare count for the same population the "
        "CHW source already reports from, so it is checked for agreement by "
        "the Cross-Level agent separately rather than compared here."
    ),
}


def _reason_not_comparable(card, alert_category: str) -> str:
    if card.status == EvidenceStatus.NOT_REPORTED:
        return f"{card.source_name} did not submit data for this window, so no comparison is possible."
    if card.status == EvidenceStatus.INSUFFICIENT_DATA:
        return f"{card.source_name} has no usable baseline for this window, so no comparison is possible."
    specific = _NOT_COMPARABLE_REASONS.get(card.source_kind)
    if specific:
        return specific
    return (
        f"{card.source_name} is recorded under a different category "
        f"({card.category}) than this alert's {alert_category}, so the two "
        "are not measuring the same thing."
    )


def _movement_phrase(card) -> str:
    if card.change_pct is None:
        return f"{card.current_value if card.current_value is not None else '—'} {card.unit}".strip()
    return (
        f"moved from {card.baseline:g} to {card.current_value:g} {card.unit} "
        f"({card.change_pct:+.0f}%)"
    ).strip()


def _pair_reason(anchor, other) -> str:
    return (
        f"{anchor.source_name} {_movement_phrase(anchor)}, while "
        f"{other.source_name} {_movement_phrase(other)}."
    )


#: Generic, non-fabricated possible explanations for a disagreement. Kept
#: general on purpose — the data does not support pointing at one specific
#: cause, so none is invented (see request Part 1.7 / 1.6).
DISAGREEMENT_INVESTIGATION_NOTE = (
    "Sources disagree — investigate why. Possible explanations include "
    "different reporting periods, different populations covered, different "
    "reporting volumes, delayed reporting, source-specific measurement "
    "differences, or data quality issues. This does not mean either source is "
    "wrong."
)


def build_evidence_relationships(alert, evidence: list) -> dict[str, Any]:
    """Classify every evidence card for one alert as AGREE / DISAGREE /
    NOT_COMPARABLE relative to the source that most likely drove the alert.

    Returns a dict with `edges` (anchor vs. each other comparable source),
    `context` (sources that cannot be directly compared, with why), and a
    small summary count. Pure read of already-persisted `AlertEvidence` rows
    — no database write, no new model.
    """

    comparable = [
        card
        for card in evidence
        if card.category == alert.category and card.status in _DIRECTIONAL_STATUSES
    ]
    context_only = [card for card in evidence if card not in comparable]

    context = [
        {
            "source_kind": card.source_kind,
            "source_kind_display": card.get_source_kind_display(),
            "source_name": card.source_name,
            "status": card.status,
            "status_display": card.get_status_display(),
            "relationship": NOT_COMPARABLE,
            "relationship_label": "Not directly comparable",
            "reason": _reason_not_comparable(card, alert.category),
        }
        for card in context_only
    ]

    if len(comparable) < 2:
        return {
            "anchor": (
                {
                    "source_kind": comparable[0].source_kind,
                    "source_kind_display": comparable[0].get_source_kind_display(),
                }
                if comparable
                else None
            ),
            "edges": [],
            "context": context,
            "summary": {
                "agree_count": 0,
                "disagree_count": 0,
                "not_comparable_count": len(context),
                "has_disagreement": False,
            },
        }

    # The source that most likely drove the alert: the anomalous, directly
    # comparable card with the largest rise. Everything else is read relative
    # to it, which is what keeps the diagram a small hub-and-spoke rather than
    # comparing every source against every other.
    anomalous = [c for c in comparable if c.status == EvidenceStatus.ANOMALY_DETECTED]
    anchor = max(
        anomalous or comparable,
        key=lambda c: (c.change_pct if c.change_pct is not None else float("-inf")),
    )

    edges = []
    for card in comparable:
        if card.id == anchor.id:
            continue
        agrees = card.status == anchor.status
        relationship = AGREE if agrees else DISAGREE
        if agrees:
            statement = (
                f"{anchor.get_source_kind_display()} "
                f"and {card.get_source_kind_display()} both show "
                f"{'a rise' if anchor.status == EvidenceStatus.ANOMALY_DETECTED else 'no notable change'} "
                f"in reported {card.get_category_display().lower()}."
            )
        else:
            statement = (
                f"{anchor.get_source_kind_display()} shows "
                f"{'a rise' if anchor.status == EvidenceStatus.ANOMALY_DETECTED else 'no notable change'} "
                f"while {card.get_source_kind_display()} shows "
                f"{'a rise' if card.status == EvidenceStatus.ANOMALY_DETECTED else 'no notable change'} "
                f"in reported {card.get_category_display().lower()}. The directions do not match."
            )
        edges.append(
            {
                "source_a": anchor.get_source_kind_display(),
                "source_a_kind": anchor.source_kind,
                "what_a_reported": anchor.explanation,
                "source_b": card.get_source_kind_display(),
                "source_b_kind": card.source_kind,
                "what_b_reported": card.explanation,
                "relationship": relationship,
                "relationship_label": "Agrees" if agrees else "Disagrees",
                "statement": statement,
                "reason": _pair_reason(anchor, card),
                "investigate": None if agrees else DISAGREEMENT_INVESTIGATION_NOTE,
            }
        )

    agree_count = sum(1 for e in edges if e["relationship"] == AGREE)
    disagree_count = sum(1 for e in edges if e["relationship"] == DISAGREE)

    return {
        "anchor": {
            "source_kind": anchor.source_kind,
            "source_kind_display": anchor.get_source_kind_display(),
        },
        "edges": edges,
        "context": context,
        "summary": {
            "agree_count": agree_count,
            "disagree_count": disagree_count,
            "not_comparable_count": len(context),
            "has_disagreement": disagree_count > 0,
        },
    }
