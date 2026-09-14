"""Phase 2 scenario endpoints (read-only) + Phase 3 session endpoints
(start/advance) + Phase 6 safety endpoint + Phase 7 replay/what-if
endpoints.

Phase 3 boundary, upheld structurally: no agent, LLM, or Safety Engine call
anywhere in the scenario/session views — `SimulationEngine` (`.services`)
is the only thing those views call, and it touches simulation tables only.
`SimulationSessionSafetyView` (Phase 6) is the one exception, and it calls
`simulation.safety.SafetyEngine` — itself LLM-free, see that package's own
docstring — never the real Safety Engine and never an LLM.

Phase 7 adds two more: `SimulationSessionReplayView` (read-only, never
calls the orchestrator or SafetyEngine — see `simulation.replay`) and
`SimulationSessionWhatIfView` (the one endpoint in this file that DOES run
the real pipeline and SafetyEngine again, deliberately, against
hypothetical inputs only — see `simulation.what_if`, which guarantees the
original session/event/signal rows are never touched).
"""

from __future__ import annotations

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from users.permissions import IsHealthOfficer
from users.scoping import scope_queryset

from .intelligence import SimulationIntelligenceSerializer, with_safety
from .investigation import (
    append_activity,
    build_community_context,
    build_contradictions,
    build_investigation_report_pdf,
    build_overview,
    checklist_items,
    compute_progress,
    feedback_payload,
    normalize_checklist,
    suggested_decision,
)
from .models import (
    InvestigationStatus,
    SafetyGateResult,
    SimulationFeedback,
    SimulationInvestigation,
    SimulationScenario,
    SimulationSession,
)
from .permissions import IsScenarioInOfficerVillage, SessionBelongsToOfficerVillage
from .replay import build_replay_state
from .safety import SafetyEngine
from .serializers import (
    InvestigationDecisionInputSerializer,
    InvestigationFeedbackInputSerializer,
    InvestigationObservationInputSerializer,
    InvestigationUpdateSerializer,
    SimulationScenarioSerializer,
    SimulationSessionStartSerializer,
    WhatIfInputSerializer,
)
from .services import (
    SimulationEngine,
    SimulationVillageMismatch,
    officer_may_access_village,
)
from .what_if import WhatIfEngine


class SimulationScenarioListView(generics.ListAPIView):
    """GET /api/simulation/scenarios/ — active scenarios for the officer's
    own village only, filtered at the queryset level before serialization
    (Phase 2 task §26). A district-wide officer sees every village's active
    scenarios, matching the same rule `users.scoping` applies everywhere
    else in the codebase.
    """

    permission_classes = (IsHealthOfficer,)
    serializer_class = SimulationScenarioSerializer

    def get_queryset(self):
        queryset = SimulationScenario.objects.filter(
            is_active=True
        ).select_related("village")
        return scope_queryset(queryset, self.request.user)


class SimulationScenarioDetailView(generics.RetrieveAPIView):
    """GET /api/simulation/scenarios/<pk>/ — deliberately NOT pre-filtered by
    village in `get_queryset`, so that `IsScenarioInOfficerVillage` is the
    thing that rejects a cross-village id, returning 403 rather than 404 —
    the object-level enforcement the Phase 2 task explicitly asks for
    (§25/§35), exercised by a real HTTP request rather than only a unit test.
    """

    permission_classes = (IsHealthOfficer, IsScenarioInOfficerVillage)
    serializer_class = SimulationScenarioSerializer
    queryset = SimulationScenario.objects.filter(is_active=True).select_related(
        "village"
    )


class SimulationSessionStartView(APIView):
    """POST /api/simulation/sessions/ — starts a new, officer-owned session
    for one scenario and returns week 1.

    A plain `APIView`, not `generics.CreateAPIView`: the scenario comes from
    the request body (`scenario_id`), not from a URL id, so there is no
    single queryset for a generic view's `get_object()` to scope — the
    object permission is instead invoked explicitly against the *scenario*
    fetched from that id, exactly the way DRF expects an object permission
    to be exercised outside of `retrieve`/`update`.
    """

    permission_classes = (IsHealthOfficer, IsScenarioInOfficerVillage)

    def post(self, request):
        serializer = SimulationSessionStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        scenario = generics.get_object_or_404(
            SimulationScenario.objects.filter(is_active=True).select_related(
                "village"
            ),
            pk=serializer.validated_data["scenario_id"],
        )
        # Object-level check #1 (DRF permission) — explicit 403 on mismatch,
        # not a silent 404, matching Phase 2's own scenario-detail pattern.
        self.check_object_permissions(request, scenario)

        # Object-level check #2 (service layer) happens again inside
        # SimulationEngine.start() itself — defense in depth, not a
        # duplicate accident.
        state = SimulationEngine.start(scenario, request.user)
        return Response(state, status=status.HTTP_201_CREATED)


class SimulationSessionAdvanceView(APIView):
    """POST /api/simulation/sessions/<id>/advance/ — moves an existing
    session to its next seeded week.

    Deliberately fetches the session from an UNFILTERED queryset (any
    session by id, not pre-scoped to the caller's village) so that a
    cross-village id produces the explicit 403 the Phase 3 task requires,
    rather than the 404-to-avoid-confirming-existence idiom used elsewhere
    in this codebase for operational alerts.
    """

    permission_classes = (IsHealthOfficer, SessionBelongsToOfficerVillage)

    def post(self, request, pk: int):
        session = generics.get_object_or_404(
            SimulationSession.objects.select_related("scenario", "village"),
            pk=pk,
        )
        # Object-level check #1 (DRF permission).
        self.check_object_permissions(request, session)

        # Object-level check #2 (service layer) — see SimulationEngine.advance().
        state = SimulationEngine.advance(session, request.user)
        return Response(state, status=status.HTTP_200_OK)


class SimulationSessionIntelligenceView(APIView):
    """GET /api/simulation/sessions/<id>/intelligence/ — Phase 5's single
    aggregated read of a session's Signal Timeline / Evidence Constellation
    / Source Fusion / Data Quality Lens / Why-Am-I-Seeing-This data.

    Same two-layer village check as `SimulationSessionAdvanceView` (object
    permission here, plus an explicit re-check below) — this is a read
    endpoint, not a mutation, but "read-only" is not a reason to relax
    authorization (task §25): a cross-village id must still 403, never
    return partial or full data.

    `suggested_next_step` (added alongside this endpoint's response,
    additive — the frozen 5-key `intelligence` shape and Phase 6's own
    `safety` addition are both untouched) is the exact same Phase 9/10
    `simulation.investigation.suggested_decision()` the Investigation
    Notebook already computes — reused verbatim here so the right-panel
    high-signal alert can show an evidence-aware recommendation without
    the officer first opening the notebook, and without a second
    recommendation algorithm existing anywhere.
    """

    permission_classes = (IsHealthOfficer, SessionBelongsToOfficerVillage)

    def get(self, request, pk: int):
        session = generics.get_object_or_404(
            SimulationSession.objects.select_related("scenario", "village"),
            pk=pk,
        )
        # Object-level check #1 (DRF permission).
        self.check_object_permissions(request, session)

        # Object-level check #2 (service layer), independent of the above —
        # same rule `SimulationEngine.start()`/`advance()` already apply, and
        # the same exception (-> 403 via DRF's default handling, then the
        # project's usual envelope) so a cross-village id behaves identically
        # whether it hits this endpoint or advance().
        if not officer_may_access_village(session.village_id, request.user):
            raise SimulationVillageMismatch()

        intelligence = SimulationIntelligenceSerializer(session).data
        safety_result = SafetyEngine.evaluate_latest(session, request.user)
        payload = with_safety(intelligence, safety_result)
        payload["suggested_next_step"] = suggested_decision(intelligence, safety_result)
        return Response(payload, status=status.HTTP_200_OK)


class SimulationSessionSafetyView(APIView):
    """GET /api/simulation/sessions/<id>/safety/ — the Phase 6 Safety Gate
    on its own, for a caller that wants only the checklist/gate/evidence
    result without the rest of the Intelligence View (task §12). Computes
    fresh on every call via `SafetyEngine.evaluate_latest()` — the exact
    same "compute on read" convention `SimulationSessionIntelligenceView`
    already uses for `build_intelligence` — so this can never drift from
    what `.../intelligence/`'s embedded `safety` key reports for the same
    session. Read-only: nothing here writes a `SimulationSafetyCheck` or
    `SimulationResult` row — those are only ever persisted once, during
    `advance()` (see `simulation.services._persist_agent_runs`).

    Identical two-layer village protection to every other session
    endpoint (task §13): object-level `SessionBelongsToOfficerVillage`,
    plus an explicit `officer_may_access_village` re-check, plus — a third,
    intentionally redundant time — `SafetyEngine`'s own Rule 1
    (`village_scope_verified`), which runs as part of `evaluate_latest()`
    below regardless of the two checks above.
    """

    permission_classes = (IsHealthOfficer, SessionBelongsToOfficerVillage)

    def get(self, request, pk: int):
        session = generics.get_object_or_404(
            SimulationSession.objects.select_related("scenario", "village"),
            pk=pk,
        )
        # Object-level check #1 (DRF permission).
        self.check_object_permissions(request, session)

        # Object-level check #2 (service layer).
        if not officer_may_access_village(session.village_id, request.user):
            raise SimulationVillageMismatch()

        # Object-level check #3 — the Safety Engine's own Rule 1, evaluated
        # unconditionally as part of the normal rule sequence, not as a
        # special case bolted on here.
        payload = SafetyEngine.evaluate_latest(session, request.user)
        return Response(payload, status=status.HTTP_200_OK)


class SimulationSessionReplayView(APIView):
    """GET /api/simulation/sessions/<id>/replay/?week=N — Phase 7 Signal
    Replay. Read-only re-display of an already-computed week: no agent
    output, LLM call, or Safety Engine evaluation happens here — see
    `simulation.replay.build_replay_state`'s own module docstring for the
    exact reasoning. `week` is optional; omitting it shows the latest
    computed week (`session.replay_position`), the same default
    `.../intelligence/` and `.../safety/` already use.

    Same two-layer village protection as every other session endpoint
    (task §31/§49): object-level `SessionBelongsToOfficerVillage`, plus an
    explicit `officer_may_access_village` re-check — a cross-village id
    never reaches `build_replay_state` at all, so it can never leak so
    much as a bounds error about another village's session.
    """

    permission_classes = (IsHealthOfficer, SessionBelongsToOfficerVillage)

    def get(self, request, pk: int):
        session = generics.get_object_or_404(
            SimulationSession.objects.select_related("scenario", "village"),
            pk=pk,
        )
        # Object-level check #1 (DRF permission).
        self.check_object_permissions(request, session)

        # Object-level check #2 (service layer).
        if not officer_may_access_village(session.village_id, request.user):
            raise SimulationVillageMismatch()

        week_param = request.query_params.get("week")
        week = None
        if week_param is not None:
            try:
                week = int(week_param)
            except (TypeError, ValueError):
                return Response(
                    {
                        "error": True,
                        "detail": "week must be a whole number.",
                        "status_code": status.HTTP_400_BAD_REQUEST,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        payload = build_replay_state(session, week=week)
        return Response(payload, status=status.HTTP_200_OK)


class SimulationSessionWhatIfView(APIView):
    """POST /api/simulation/sessions/<id>/what-if/ — Phase 7 What-If
    Simulation. Runs the REAL Phase 4 `MultiAgentOrchestrator` and Phase 6
    `SafetyEngine` against hypothetical, session-scoped synthetic overrides
    for the session's current week — see `simulation.what_if.WhatIfEngine`
    for exactly how the original session/event/signals are left untouched
    (task §11/§18).

    Same two-layer village protection as every mutating-looking session
    endpoint, even though nothing here is actually persisted to the real
    session: What-If is, per task §49, "a privileged simulation
    operation" and gets the same scrutiny as `advance()`.
    """

    permission_classes = (IsHealthOfficer, SessionBelongsToOfficerVillage)

    def post(self, request, pk: int):
        session = generics.get_object_or_404(
            SimulationSession.objects.select_related("scenario", "village"),
            pk=pk,
        )
        # Object-level check #1 (DRF permission).
        self.check_object_permissions(request, session)

        # Object-level check #2 (service layer) — same rule as every other
        # session endpoint, checked again independently here.
        if not officer_may_access_village(session.village_id, request.user):
            raise SimulationVillageMismatch()

        serializer = WhatIfInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Object-level check #3 — WhatIfEngine re-derives and re-verifies
        # the officer's village against this exact session before running
        # anything, independent of the two checks above.
        result = WhatIfEngine.run(session, request.user, serializer.validated_data["overrides"])
        return Response(result, status=status.HTTP_200_OK)


#: This particular UI ("Counterfactual Investigation" — structured
#: strengthen/weaken options rather than raw What-If value entry) is a
#: deliberate product-scoping decision for Village A only, not a technical
#: restriction: the underlying pipeline is identical for every village.
#: Kept local to this view rather than in `core.constants` because nothing
#: else needs it — the plain existing What-If endpoint above remains
#: available to every village, unrestricted, exactly as before.
COUNTERFACTUAL_VILLAGE_CODE = "KVL"


class SimulationCounterfactualView(APIView):
    """POST /api/simulation/sessions/<id>/counterfactual/ — Counterfactual
    Investigation. A thin, Village-A-only wrapper around the exact same
    `WhatIfEngine.run()` the plain What-If endpoint above calls — no second
    orchestrator, correlation, evidence, or safety implementation exists
    here. The only thing this view adds beyond `SimulationSessionWhatIfView`
    is the village gate; the computation, isolation guarantee (rollback),
    and village/officer re-verification are entirely `WhatIfEngine`'s own.
    """

    permission_classes = (IsHealthOfficer, SessionBelongsToOfficerVillage)

    def post(self, request, pk: int):
        session = generics.get_object_or_404(
            SimulationSession.objects.select_related("scenario", "village"),
            pk=pk,
        )
        # Object-level check #1 (DRF permission).
        self.check_object_permissions(request, session)

        # Object-level check #2 (service layer) — same rule as every other
        # session endpoint, checked again independently here.
        if not officer_may_access_village(session.village_id, request.user):
            raise SimulationVillageMismatch()

        # Object-level check #3 — the feature-specific village gate. Checked
        # against the session's own village, never the caller-supplied
        # officer, so a district-wide officer cannot reach it for a
        # non-Village-A session either.
        if session.village.code != COUNTERFACTUAL_VILLAGE_CODE:
            return Response(
                {
                    "error": True,
                    "detail": (
                        "Counterfactual Investigation is currently available for "
                        "Village A only."
                    ),
                    "status_code": status.HTTP_403_FORBIDDEN,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = WhatIfInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Object-level check #4 — WhatIfEngine re-derives and re-verifies
        # the officer's village against this exact session before running
        # anything, independent of the checks above.
        result = WhatIfEngine.run(session, request.user, serializer.validated_data["overrides"])
        return Response(result, status=status.HTTP_200_OK)


def _investigation_payload(session: SimulationSession, investigation: SimulationInvestigation, officer) -> dict:
    """The ONE Phase 9 read — deliberately does not re-embed the full
    `.../intelligence/` or `.../safety/` payloads (task §38: "do not
    duplicate existing intelligence payload unnecessarily"); the frontend
    already has (or fetches) those via the existing endpoints/store. Only
    genuinely new investigation-specific data is returned here."""

    intelligence = SimulationIntelligenceSerializer(session).data
    safety = SafetyEngine.evaluate_latest(session, officer)

    items = checklist_items(intelligence)
    checklist = normalize_checklist(investigation.checklist, items)
    progress = compute_progress(checklist)

    return {
        "overview": build_overview(session, investigation, intelligence, safety),
        "checklist": {"items": items, "values": checklist, "progress": progress},
        "contradictions": build_contradictions(intelligence),
        "community_context": build_community_context(session),
        "observations": investigation.observations,
        "notes": investigation.officer_notes,
        "decision": {
            "value": investigation.decision,
            "value_display": investigation.get_decision_display() if investigation.decision else "",
            "reason": investigation.decision_reason,
            "decided_by": investigation.decided_by.username if investigation.decided_by else None,
            "decided_at": investigation.decided_at,
        },
        "suggested_decision": suggested_decision(intelligence, safety),
        "activity_history": investigation.activity_history,
        "status": investigation.status,
        "status_display": investigation.get_status_display(),
    }


class SimulationInvestigationView(APIView):
    """GET/PATCH /api/simulation/sessions/<id>/investigation/ — Phase 9's
    investigation workspace. GET is get-or-create: opening the
    Investigation Notebook (the "Investigate Signal" action) is what
    creates the session's one investigation row, immediately at
    `IN_PROGRESS` — there is no separate "create" call (task §50: one row
    per session, no redundant models, enforced at the DB level by
    `unique_simulation_investigation_per_session`). PATCH updates notes
    and/or checklist (both optional — `InvestigationUpdateSerializer`).

    Same two-layer village protection as every other session endpoint.
    Safety BLOCK does NOT prevent opening/viewing the notebook — the
    officer must still be able to see *why* it is blocked; only
    `SimulationInvestigationDecisionView` enforces the hard block (task
    §22: "the officer must NOT be allowed to finalize escalation through
    the normal workflow" — a decision-time restriction, not a view-time
    one).
    """

    permission_classes = (IsHealthOfficer, SessionBelongsToOfficerVillage)

    def _authorized_session(self, request, pk: int) -> SimulationSession:
        session = generics.get_object_or_404(
            SimulationSession.objects.select_related("scenario", "village"), pk=pk
        )
        self.check_object_permissions(request, session)
        if not officer_may_access_village(session.village_id, request.user):
            raise SimulationVillageMismatch()
        return session

    def get(self, request, pk: int):
        session = self._authorized_session(request, pk)
        investigation, created = SimulationInvestigation.objects.get_or_create(
            session=session,
            defaults={"village": session.village, "status": InvestigationStatus.IN_PROGRESS},
        )
        if created:
            append_activity(investigation, "investigation_started", request.user)
            investigation.save()
        return Response(
            _investigation_payload(session, investigation, request.user), status=status.HTTP_200_OK
        )

    def patch(self, request, pk: int):
        session = self._authorized_session(request, pk)
        investigation = generics.get_object_or_404(SimulationInvestigation, session=session)

        serializer = InvestigationUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if "notes" in data:
            investigation.officer_notes = data["notes"]
            append_activity(investigation, "notes_updated", request.user)

        if "checklist" in data:
            intelligence = SimulationIntelligenceSerializer(session).data
            items = checklist_items(intelligence)
            merged = {**(investigation.checklist or {}), **data["checklist"]}
            investigation.checklist = normalize_checklist(merged, items)
            append_activity(investigation, "checklist_updated", request.user)

            progress = compute_progress(investigation.checklist)
            if progress["total"] and progress["checked"] == progress["total"]:
                if investigation.status == InvestigationStatus.IN_PROGRESS:
                    investigation.status = InvestigationStatus.READY_FOR_DECISION

        investigation.save()
        return Response(
            _investigation_payload(session, investigation, request.user), status=status.HTTP_200_OK
        )


class SimulationInvestigationDecisionView(APIView):
    """POST /api/simulation/sessions/<id>/investigation/decision/ —
    records the officer's final human decision (task §20/§21/§41).
    Attribution is always `request.user`, never a client-supplied officer
    id — `InvestigationDecisionInputSerializer` has no id field to accept
    one. Safety BLOCK rejects with 403 (task §22), re-checked fresh here
    via `SafetyEngine.evaluate_latest()` rather than trusted from
    anything stale the frontend might be holding.
    """

    permission_classes = (IsHealthOfficer, SessionBelongsToOfficerVillage)

    def post(self, request, pk: int):
        session = generics.get_object_or_404(
            SimulationSession.objects.select_related("scenario", "village"), pk=pk
        )
        self.check_object_permissions(request, session)
        if not officer_may_access_village(session.village_id, request.user):
            raise SimulationVillageMismatch()

        investigation = generics.get_object_or_404(SimulationInvestigation, session=session)

        serializer = InvestigationDecisionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        safety = SafetyEngine.evaluate_latest(session, request.user)
        if safety["gate_result"] == SafetyGateResult.BLOCK:
            return Response(
                {
                    "error": True,
                    "detail": (
                        "This investigation cannot be finalized while the Safety Gate "
                        "result is BLOCK. Resolve the blocking condition first."
                    ),
                    "status_code": status.HTTP_403_FORBIDDEN,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        investigation.decision = serializer.validated_data["decision"]
        investigation.decision_reason = serializer.validated_data.get("reason", "")
        investigation.decided_by = request.user
        investigation.decided_at = timezone.now()
        investigation.status = InvestigationStatus.DECISION_RECORDED
        append_activity(investigation, "decision_recorded", request.user)
        investigation.save()

        return Response(
            _investigation_payload(session, investigation, request.user), status=status.HTTP_200_OK
        )


class SimulationInvestigationObservationView(APIView):
    """POST /api/simulation/sessions/<id>/investigation/observations/ —
    appends one simulated field observation (task §16). Never attached to
    a real patient or operational record: `InvestigationObservationInputSerializer`
    has no field capable of referencing one, structurally."""

    permission_classes = (IsHealthOfficer, SessionBelongsToOfficerVillage)

    def post(self, request, pk: int):
        session = generics.get_object_or_404(
            SimulationSession.objects.select_related("scenario", "village"), pk=pk
        )
        self.check_object_permissions(request, session)
        if not officer_may_access_village(session.village_id, request.user):
            raise SimulationVillageMismatch()

        investigation = generics.get_object_or_404(SimulationInvestigation, session=session)

        serializer = InvestigationObservationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        observations = list(investigation.observations or [])
        next_id = max((entry.get("id", 0) for entry in observations), default=0) + 1
        observations.append(
            {
                "id": next_id,
                "week": data["week"],
                "source": data["source"],
                "category": data.get("category", ""),
                "notes": data["notes"],
                "created_at": timezone.now().isoformat(),
            }
        )
        investigation.observations = observations
        append_activity(investigation, "observation_added", request.user)
        investigation.save()

        return Response(
            _investigation_payload(session, investigation, request.user), status=status.HTTP_201_CREATED
        )


class SimulationInvestigationReportView(APIView):
    """GET /api/simulation/sessions/<id>/investigation/report/ — the
    Investigation Report PDF (task §27/§28). Read-only in every sense
    that matters: the only mutation is an audit entry recording that the
    report was exported, never a state/decision change."""

    permission_classes = (IsHealthOfficer, SessionBelongsToOfficerVillage)

    def get(self, request, pk: int):
        session = generics.get_object_or_404(
            SimulationSession.objects.select_related("scenario", "village"), pk=pk
        )
        self.check_object_permissions(request, session)
        if not officer_may_access_village(session.village_id, request.user):
            raise SimulationVillageMismatch()

        investigation = generics.get_object_or_404(SimulationInvestigation, session=session)
        feedback = SimulationFeedback.objects.filter(investigation=investigation).first()

        intelligence = SimulationIntelligenceSerializer(session).data
        safety = SafetyEngine.evaluate_latest(session, request.user)

        append_activity(investigation, "report_exported", request.user)
        investigation.save(update_fields=["activity_history", "updated_at"])

        pdf_bytes = build_investigation_report_pdf(session, investigation, intelligence, safety, feedback)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="gramsentinel-investigation-session-{session.id}.pdf"'
        )
        return response


class SimulationInvestigationFeedbackView(APIView):
    """GET/PATCH /api/simulation/sessions/<id>/investigation/feedback/ —
    Phase 10's officer-experience feedback (task §5/§7/§9/§10). One row
    per investigation, enforced at the DB level
    (`unique_simulation_feedback_per_investigation`) — PATCH always
    updates the same row rather than creating a new one (task §8).

    Attribution is always `request.user` (task §9/§35: "never accept
    officer_id from frontend") — `InvestigationFeedbackInputSerializer`
    has no id field to accept one, and the officer on the row is
    overwritten to the current caller on every save regardless. Same
    two-layer village protection as every other session endpoint.

    This view NEVER touches `SimulationResult`, `SimulationSafetyCheck`,
    or `SimulationInvestigation.decision`/`officer_notes`/`checklist` —
    feedback is recorded and read back, nothing else (task §41-§43).
    """

    permission_classes = (IsHealthOfficer, SessionBelongsToOfficerVillage)

    def _authorized_investigation(self, request, pk: int) -> tuple[SimulationSession, SimulationInvestigation]:
        session = generics.get_object_or_404(
            SimulationSession.objects.select_related("scenario", "village"), pk=pk
        )
        self.check_object_permissions(request, session)
        if not officer_may_access_village(session.village_id, request.user):
            raise SimulationVillageMismatch()
        investigation = generics.get_object_or_404(SimulationInvestigation, session=session)
        return session, investigation

    def get(self, request, pk: int):
        _session, investigation = self._authorized_investigation(request, pk)
        feedback = SimulationFeedback.objects.filter(investigation=investigation).first()
        return Response(feedback_payload(feedback), status=status.HTTP_200_OK)

    def patch(self, request, pk: int):
        session, investigation = self._authorized_investigation(request, pk)

        serializer = InvestigationFeedbackInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        feedback, created = SimulationFeedback.objects.get_or_create(
            investigation=investigation,
            defaults={"session": session, "village": session.village, "officer": request.user},
        )
        for field, value in serializer.validated_data.items():
            setattr(feedback, field, value)
        # Never trust a stale/different officer on an update — always the
        # authenticated caller (task §36: "do not silently change
        # authorship").
        feedback.officer = request.user
        feedback.save()

        append_activity(
            investigation, "feedback_submitted" if created else "feedback_updated", request.user
        )
        investigation.save(update_fields=["activity_history", "updated_at"])

        return Response(feedback_payload(feedback), status=status.HTTP_200_OK)
