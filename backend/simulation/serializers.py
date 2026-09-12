"""Read-only serialization for Phase 2.

Follows the existing project's serializer convention (see
`alerts.serializers.AlertListSerializer`, `community.serializers.
CommunitySignalSerializer`): a `*_display` companion field for every
TextChoices field, and separate `village_code`/`village_name` fields rather
than a single flattened "village" string — the Phase 2 task's own §32
explicitly allows following the existing convention over its own literal
example when the two differ, so that is what this does.
"""

from rest_framework import serializers

from .models import SimulationScenario


class SimulationScenarioSerializer(serializers.ModelSerializer):
    scenario_type_display = serializers.CharField(
        source="get_scenario_type_display", read_only=True
    )
    village_code = serializers.CharField(source="village.code", read_only=True)
    village_name = serializers.CharField(source="village.name", read_only=True)

    class Meta:
        model = SimulationScenario
        fields = (
            "id",
            "name",
            "scenario_type",
            "scenario_type_display",
            "description",
            "village_code",
            "village_name",
            "is_active",
            "version",
        )
        read_only_fields = fields
