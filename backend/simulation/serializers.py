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

from .models import (
    FeedbackEvidenceSufficiency,
    FeedbackUsefulness,
    FeedbackYesNo,
    FeedbackYesPartiallyNo,
    InvestigationDecision,
    SimulationScenario,
)


class SimulationSessionStartSerializer(serializers.Serializer):
    """Input-only validation for `POST /simulation/sessions/` — mirrors the
    plain `serializers.Serializer` convention already used for other
    custom-shaped, non-CRUD actions in this codebase (e.g.
    `alerts.serializers.FeedbackInputSerializer`). The response itself is a
    plain dict built by `SimulationEngine`, not a `ModelSerializer` output —
    matching how other aggregated/computed views in this project (e.g.
    `OfficerDashboardView`) already return hand-built response bodies.
    """

    scenario_id = serializers.IntegerField()


class WhatIfInputSerializer(serializers.Serializer):
    """Input-only validation for `POST /simulation/sessions/<id>/what-if/`
    (Phase 7 task §24/§25). Structural validation only: every override
    value must be `null` (meaning "hypothetically not reported") or a
    non-negative number — non-numeric values and negative counts are
    rejected here, before `simulation.what_if.WhatIfEngine` ever runs.
    Which *keys* are acceptable (only source types this session's current
    week actually has) is a business rule, not a structural one, and is
    checked in `WhatIfEngine` itself, the only place that knows what a
    session's real sources are — this serializer would have to guess.
    """

    overrides = serializers.DictField(
        child=serializers.FloatField(min_value=0, allow_null=True),
        allow_empty=False,
    )


class InvestigationUpdateSerializer(serializers.Serializer):
    """Input-only validation for `PATCH .../investigation/` (Phase 9 task
    §17/§18/§40) — both fields optional (a partial update). `notes` has a
    generous but real length cap rather than unlimited free text.
    `checklist` values are validated as booleans structurally here; WHICH
    keys are acceptable for this session is a business rule checked in
    `simulation.investigation.normalize_checklist` (it would have to know
    the session's actual sources, which this serializer cannot)."""

    notes = serializers.CharField(required=False, allow_blank=True, max_length=20000)
    checklist = serializers.DictField(child=serializers.BooleanField(), required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide at least one of notes or checklist.")
        return attrs


class InvestigationDecisionInputSerializer(serializers.Serializer):
    """Input-only validation for `POST .../investigation/decision/` (task
    §20/§21). `decision` is restricted to Phase 9's own vocabulary
    (`InvestigationDecision`) — an unrecognised value is rejected here,
    before it ever reaches the view. Safety-gate enforcement (BLOCK
    prevents recording at all) is a business rule checked in the view,
    which is the only place that knows the session's current safety
    result."""

    decision = serializers.ChoiceField(choices=InvestigationDecision.choices)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=4000)


class InvestigationObservationInputSerializer(serializers.Serializer):
    """Input-only validation for `POST .../investigation/observations/`
    (task §16) — a simulated field observation, never attached to a real
    patient or operational village record (enforced structurally: this
    serializer has no patient/village/officer id field to accept one)."""

    week = serializers.IntegerField(min_value=1)
    source = serializers.CharField(max_length=64)
    category = serializers.CharField(required=False, allow_blank=True, max_length=64)
    notes = serializers.CharField(max_length=4000)


class InvestigationFeedbackInputSerializer(serializers.Serializer):
    """Input-only validation for `PATCH .../investigation/feedback/`
    (Phase 10 task §5/§7/§9). Every field optional (a partial update, like
    `InvestigationUpdateSerializer`), but at least one must be present.
    Each choice field is restricted to Phase 10's own officer-experience
    vocabulary — never the `InvestigationDecision` or operational
    `Feedback.Outcome` vocabularies, a deliberately different question."""

    usefulness = serializers.ChoiceField(choices=FeedbackUsefulness.choices, required=False)
    evidence_sufficiency = serializers.ChoiceField(
        choices=FeedbackEvidenceSufficiency.choices, required=False
    )
    recommendation_helpful = serializers.ChoiceField(
        choices=FeedbackYesPartiallyNo.choices, required=False
    )
    additional_verification_required = serializers.ChoiceField(
        choices=FeedbackYesNo.choices, required=False
    )
    comment = serializers.CharField(required=False, allow_blank=True, max_length=4000)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide at least one feedback field.")
        return attrs


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
