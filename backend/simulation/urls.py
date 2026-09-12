from django.urls import path

from .views import SimulationScenarioDetailView, SimulationScenarioListView

urlpatterns = [
    path(
        "simulation/scenarios/",
        SimulationScenarioListView.as_view(),
        name="simulation-scenario-list",
    ),
    path(
        "simulation/scenarios/<int:pk>/",
        SimulationScenarioDetailView.as_view(),
        name="simulation-scenario-detail",
    ),
]
