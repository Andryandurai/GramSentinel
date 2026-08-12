from django.urls import path

from .views import PatientDetailView, PatientListCreateView, PatientPortalView

urlpatterns = [
    path("patients/", PatientListCreateView.as_view(), name="patient-list"),
    path("patients/<int:pk>/", PatientDetailView.as_view(), name="patient-detail"),
    # Patient portal — resolves the record from the token, never from a URL id.
    path("patient/me/", PatientPortalView.as_view(), name="patient-portal"),
]
