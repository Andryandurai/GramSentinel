from django.urls import path

from .views import (
    OfficerPregnancyListView,
    OfficerPregnancySummaryView,
    OfficerRequestFollowUpView,
    PregnancyProfileDetailView,
    PregnancyProfileListCreateView,
    PregnancyQuestionsView,
    PregnancyVisitCreateView,
    WorkerPregnancySummaryView,
)

urlpatterns = [
    path("pregnancy/questions/<int:visit_number>/", PregnancyQuestionsView.as_view(), name="pregnancy-questions"),
    path("pregnancy/profiles/", PregnancyProfileListCreateView.as_view(), name="pregnancy-profile-list"),
    path("pregnancy/profiles/<int:pk>/", PregnancyProfileDetailView.as_view(), name="pregnancy-profile-detail"),
    path("pregnancy/profiles/<int:pk>/visits/", PregnancyVisitCreateView.as_view(), name="pregnancy-visit-create"),
    path("pregnancy/worker/summary/", WorkerPregnancySummaryView.as_view(), name="pregnancy-worker-summary"),
    path("pregnancy/officer/summary/", OfficerPregnancySummaryView.as_view(), name="pregnancy-officer-summary"),
    path("pregnancy/officer/list/", OfficerPregnancyListView.as_view(), name="pregnancy-officer-list"),
    path(
        "pregnancy/officer/profiles/<int:pk>/request-followup/",
        OfficerRequestFollowUpView.as_view(),
        name="pregnancy-officer-request-followup",
    ),
]
