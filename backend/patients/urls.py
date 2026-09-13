from django.urls import path

from .views import PatientDetailView, PatientListCreateView

urlpatterns = [
    path("patients/", PatientListCreateView.as_view(), name="patient-list"),
    path("patients/<int:pk>/", PatientDetailView.as_view(), name="patient-detail"),
]
