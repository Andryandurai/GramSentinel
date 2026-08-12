from django.contrib import admin

from .models import AgentRun, Alert, AlertEvidence, Feedback, Investigation, SafetyCheck


class AlertEvidenceInline(admin.TabularInline):
    model = AlertEvidence
    extra = 0


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "cluster",
        "week_label",
        "severity",
        "safety_verdict",
        "status",
        "corroborating_source_count",
    )
    list_filter = ("severity", "status", "safety_verdict", "category")
    inlines = (AlertEvidenceInline,)


@admin.register(SafetyCheck)
class SafetyCheckAdmin(admin.ModelAdmin):
    list_display = ("scope", "verdict", "status", "village", "week_label", "created_at")
    list_filter = ("scope", "verdict")


@admin.register(AgentRun)
class AgentRunAdmin(admin.ModelAdmin):
    list_display = ("agent_name", "stage", "status", "village", "week_label", "duration_ms")
    list_filter = ("stage", "agent_layer", "status")


admin.site.register([Investigation, Feedback])
admin.site.site_header = "GramSentinel administration"
admin.site.site_title = "GramSentinel"
