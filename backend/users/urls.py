from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    LoginView,
    MeView,
    MyProfileView,
    StaffProfileDetailView,
    StaffProfileListView,
)

urlpatterns = [
    path("login/", LoginView.as_view(), name="auth-login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("me/", MeView.as_view(), name="auth-me"),
    # Professional profiles. Mounted under the same /api/auth/ prefix as the
    # rest of the user endpoints rather than inventing a second user API.
    path("profile/", MyProfileView.as_view(), name="my-profile"),
    path("staff-profiles/", StaffProfileListView.as_view(), name="staff-profile-list"),
    path(
        "staff-profiles/<int:pk>/",
        StaffProfileDetailView.as_view(),
        name="staff-profile-detail",
    ),
]
