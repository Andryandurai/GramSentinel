"""Phase 2 — read-only scenario endpoints only.

No `POST /sessions/`, no advance/execution endpoint, no agent/LLM/safety
call anywhere in this file — those belong to later phases (Phase 2 task
§24/§33). Both views below are read-only (`generics.ListAPIView` /
`RetrieveAPIView`).
"""

from __future__ import annotations

from rest_framework import generics

from users.permissions import IsHealthOfficer
from users.scoping import scope_queryset

from .models import SimulationScenario
from .permissions import IsScenarioInOfficerVillage
from .serializers import SimulationScenarioSerializer


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
