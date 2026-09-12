from django.contrib import admin

from .models import (
    SimulationAgentRun,
    SimulationEvent,
    SimulationInvestigation,
    SimulationResult,
    SimulationSafetyCheck,
    SimulationScenario,
    SimulationSession,
    SimulationSourceSignal,
)


class SimulationEventInline(admin.TabularInline):
    model = SimulationEvent
    extra = 0


@admin.register(SimulationScenario)
class SimulationScenarioAdmin(admin.ModelAdmin):
    list_display = ("name", "scenario_type", "village", "version", "is_active")
    list_filter = ("scenario_type", "village", "is_active")


@admin.register(SimulationSession)
class SimulationSessionAdmin(admin.ModelAdmin):
    list_display = ("scenario", "village", "health_officer", "status", "created_at")
    list_filter = ("status", "village")
    inlines = (SimulationEventInline,)


@admin.register(SimulationSourceSignal)
class SimulationSourceSignalAdmin(admin.ModelAdmin):
    list_display = ("event", "source_type", "value", "reported")
    list_filter = ("source_type", "reported")


admin.site.register(
    [
        SimulationEvent,
        SimulationAgentRun,
        SimulationSafetyCheck,
        SimulationResult,
        SimulationInvestigation,
    ]
)
