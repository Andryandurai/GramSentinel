"""Village scoping, in one place so every view applies the same rule.

The rule, stated once:

    A user with a village assigned sees only that village.
    A user with no village assigned sees everything they are otherwise
    permitted to see.

That second clause is deliberate and load-bearing for backwards compatibility:
the original `officer` demonstration account has no village and supervises the
whole district. Scoping officers by village would have silently emptied that
account's dashboard, so instead an unassigned village means district-wide —
which is also how a real district health officer actually works.

Administrators are never scoped.
"""

from __future__ import annotations

from django.db.models import QuerySet


def scoped_village_id(user) -> int | None:
    """The village a user is confined to, or None for unrestricted access."""

    if user is None or not user.is_authenticated:
        return None
    if getattr(user, "is_platform_admin", False):
        return None
    return user.village_id


def scope_queryset(
    queryset: QuerySet, user, field: str = "village_id"
) -> QuerySet:
    """Confine a queryset to the user's village, if they have one."""

    village_id = scoped_village_id(user)
    if village_id is None:
        return queryset
    return queryset.filter(**{field: village_id})


def visible_village_codes(user) -> list[str] | None:
    """Village codes a user may see, or None meaning 'all of them'."""

    village_id = scoped_village_id(user)
    if village_id is None:
        return None
    village = getattr(user, "village", None)
    return [village.code] if village else []
