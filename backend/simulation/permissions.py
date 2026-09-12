"""Simulation permissions — reusing the existing role/village pattern.

`IsHealthOfficer` (`users.permissions`) already gates entry by role; it is
reused here unmodified rather than duplicated. `IsScenarioInOfficerVillage`
is the one genuinely new permission this phase adds, and it does exactly one
thing: compare `scenario.village_id` against the authenticated officer's own
village id, resolved server-side via `users.scoping.scoped_village_id` —
never from anything the client supplies (Phase 2 task §25/§42).

A district-wide officer (no village — e.g. the original `officer` demo
account) is treated exactly as `users.scoping` already treats one everywhere
else in the codebase: unrestricted, not "denied". This is the same rule, not
a new one.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from users.scoping import scoped_village_id


class IsScenarioInOfficerVillage(BasePermission):
    """Object-level guard for a single `SimulationScenario`.

    Deliberately returns HTTP 403 (not 404) on a cross-village attempt, per
    the Phase 2 task's explicit instruction (§25/§35) — this is a documented
    departure from the "404 to avoid confirming existence" idiom the rest of
    the app uses for alerts (`alerts.views.AlertDetailView`), because the
    task specifies 403 for this permission class specifically.
    """

    message = "This simulation scenario is not available for your village."

    def has_object_permission(self, request, view, obj) -> bool:
        village_id = scoped_village_id(request.user)
        if village_id is None:
            return True
        return obj.village_id == village_id
