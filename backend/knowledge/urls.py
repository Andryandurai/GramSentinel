from django.urls import path

from .views import (
    ChwKnowledgeView,
    InvestigationGuidanceView,
    KnowledgeDocumentDetailView,
    RuralCareGuidanceView,
    TerminologySuggestionView,
)

urlpatterns = [
    path("rag/ruralcare/", RuralCareGuidanceView.as_view(), name="rag-ruralcare"),
    path("rag/terminology/", TerminologySuggestionView.as_view(), name="rag-terminology"),
    path("rag/investigation/", InvestigationGuidanceView.as_view(), name="rag-investigation"),
    path("rag/chw/", ChwKnowledgeView.as_view(), name="rag-chw"),
    path("rag/sources/<int:pk>/", KnowledgeDocumentDetailView.as_view(), name="rag-source-detail"),
]
