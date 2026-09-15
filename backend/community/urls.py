from django.urls import path

from .views import (
    CommunityReportListCreateView,
    DataSourceListView,
    LocalSignalReportCreateView,
    LocalSignalsView,
    ReportCategoryListView,
    SourceOperationalContextCancelView,
    SourceOperationalContextDetailView,
    SourceOperationalContextListCreateView,
)

urlpatterns = [
    path(
        "community-reports/",
        CommunityReportListCreateView.as_view(),
        name="community-report-list",
    ),
    path(
        "report-categories/",
        ReportCategoryListView.as_view(),
        name="report-category-list",
    ),
    path("local-signals/", LocalSignalsView.as_view(), name="local-signals"),
    path(
        "local-signal-reports/",
        LocalSignalReportCreateView.as_view(),
        name="local-signal-report-create",
    ),
    path("data-sources/", DataSourceListView.as_view(), name="data-source-list"),
    path(
        "source-contexts/",
        SourceOperationalContextListCreateView.as_view(),
        name="source-context-list",
    ),
    path(
        "source-contexts/<int:pk>/",
        SourceOperationalContextDetailView.as_view(),
        name="source-context-detail",
    ),
    path(
        "source-contexts/<int:pk>/cancel/",
        SourceOperationalContextCancelView.as_view(),
        name="source-context-cancel",
    ),
]
