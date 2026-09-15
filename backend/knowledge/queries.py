"""Context-specific query builders — Section 28 of the task.

Each function below builds a `question`/`application_result` pair from
ONLY already-computed, non-identifying context and calls
`rag_service.get_grounded_explanation()`. None of them accept a patient
name, phone number, house location, patient code, or raw individual
vitals/symptom-timeline text — see each function's own parameter list,
which is the actual enforcement of that boundary (there is nothing to
"forget" to strip, because the caller never has those fields to pass).

Ten conceptual RAG modules (Section 63 of the task) are covered by four
functions here — a deliberate consolidation, not a scope cut. Each module
keeps its own `KnowledgeTopic`/`query_type` tag and is independently
retrievable and independently tested; they are grouped only because, in
the actual UI, a worker or officer views them together in one panel:

    ruralcare_guidance()      <- modules 1 (clinical), 3 (triage explanation),
                                  4 (referral guidance)
    terminology_suggestion()  <- module 2 (medical terminology)
    investigation_guidance()  <- modules 5 (surveillance), 6 (freshness/
                                  evidence context), 7 (investigation),
                                  9 (what-if guidance), 10 (internal
                                  GramSentinel knowledge) — selected via
                                  `mode`, all sharing the same evidence-
                                  shaped input
    chw_knowledge()           <- module 8 (ASHA/CHW knowledge)
"""

from __future__ import annotations

from .models import KnowledgeTopic
from .rag_service import get_grounded_explanation


def ruralcare_guidance(
    *,
    triage_level: str,
    contributing_factors: list[str],
    syndrome_groups: list[str],
    referral_pathway: str,
    user=None,
) -> dict:
    """Modules 1 + 3 + 4. Input is exactly what `RiskTriageAgent` and
    `ReferralAgent` already produced (Section 5 of the RuralCare pipeline)
    — a level, a list of short factor phrases, syndrome group names, and
    the referral pathway string. No symptoms-as-typed, no vitals numbers,
    no patient identifiers of any kind."""

    application_result = (
        f"Triage level: {triage_level}. "
        f"Contributing factors: {'; '.join(contributing_factors) or 'none'}. "
        f"Syndrome pattern: {', '.join(syndrome_groups) or 'none'}. "
        f"Referral pathway: {referral_pathway}."
    )
    question = (
        "What relevant clinical and referral guidance applies to a "
        f"{triage_level.lower()} presentation with this pattern?"
    )
    return get_grounded_explanation(
        query_type="ruralcare_guidance",
        application_result=application_result,
        question=question,
        topic=[KnowledgeTopic.CLINICAL, KnowledgeTopic.REFERRAL],
        user=user,
    )


def terminology_suggestion(*, entered_text: str, user=None) -> dict:
    """Module 2. Only ever called for text the deterministic vocabulary
    (agents/ruralcare/vocabulary.py) already failed to recognise — this
    function never runs instead of that lookup, only after it, and its
    output is a *suggestion* the worker must explicitly accept (Section 16:
    "Do NOT silently convert arbitrary text into a clinical diagnosis")."""

    application_result = (
        f"The entered text '{entered_text}' did not match any recognised "
        "symptom in the application's own vocabulary."
    )
    question = f"What recognised health concept might '{entered_text}' refer to?"
    return get_grounded_explanation(
        query_type="terminology_suggestion",
        application_result=application_result,
        question=question,
        topic=KnowledgeTopic.TERMINOLOGY,
        document_type="TERMINOLOGY_REFERENCE",
        user=user,
    )


def investigation_guidance(
    *,
    category_label: str,
    corroborating_sources: list[str],
    context_sources: list[str],
    missing_sources: list[str],
    cross_level_verdict: str,
    safety_verdict: str,
    mode: str = "investigation",
    user=None,
) -> dict:
    """Modules 5 + 6 + 7 + 9 + 10. Input is exactly the aggregate evidence
    shape `AlertEvidenceView`/the Simulation Lab's evidence view already
    computes — category label, which source *kinds* corroborate/provide
    context/are missing, the cross-level verdict, the safety verdict. No
    village name, no raw signal values, no patient data of any kind
    (aggregate counts only, matching the existing community/aggregation.py
    privacy boundary this function inherits by only ever receiving
    already-aggregated inputs).

    `mode` selects the question framing and which topics are searched:
    "investigation" (default) covers surveillance/investigation/internal
    guidance; "what_if" narrows toward the same set but asks specifically
    what additional information would strengthen or weaken the signal —
    the existing What-If engine (simulation/what_if.py) remains the only
    thing that actually runs a hypothetical; this only explains what
    approved guidance says about doing so.
    """

    application_result = (
        f"Potential {category_label} signal. Corroborating sources: "
        f"{', '.join(corroborating_sources) or 'none'}. Context-only "
        f"sources: {', '.join(context_sources) or 'none'}. Sources not "
        f"reported this period: {', '.join(missing_sources) or 'none'}. "
        f"Cross-level verdict: {cross_level_verdict}. "
        f"Safety Engine verdict: {safety_verdict}."
    )
    if mode == "what_if":
        question = (
            "What relevant guidance describes what additional information "
            "would strengthen or weaken confidence in this signal?"
        )
    else:
        question = (
            "What relevant surveillance, evidence-interpretation and "
            "investigation guidance applies to this signal?"
        )

    return get_grounded_explanation(
        query_type=f"investigation_guidance:{mode}",
        application_result=application_result,
        question=question,
        topic=[
            KnowledgeTopic.SURVEILLANCE,
            KnowledgeTopic.PUBLIC_HEALTH,
            KnowledgeTopic.INVESTIGATION,
            KnowledgeTopic.GRAMSENTINEL_INTERNAL,
        ],
        user=user,
    )


def chw_knowledge(*, worker_question: str, user=None) -> dict:
    """Module 8. Free-text educational Q&A for a frontline worker — the
    ONLY function in this file that takes a free-text question directly
    from a user, and it is scoped to a single fixed topic
    (KnowledgeTopic.CHW_ASHA) the worker cannot change, so this cannot
    become a general-purpose unrestricted knowledge endpoint (Section 45:
    "no client-controlled source authority")."""

    return get_grounded_explanation(
        query_type="chw_knowledge",
        application_result="(Educational reference — no application result to explain.)",
        question=worker_question,
        topic=KnowledgeTopic.CHW_ASHA,
        user=user,
    )
