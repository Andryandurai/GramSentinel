"""Server-side role enforcement.

Every API view opts into exactly one of these. Hiding a button in the frontend
is a usability measure, not a security measure (Section 37).
"""

from rest_framework.permissions import BasePermission

from .models import User


class IsWorker(BasePermission):
    message = "This endpoint is restricted to CHW / PHC workers."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (user.role == User.Role.CHW_PHC_WORKER or user.is_platform_admin)
        )


class IsHealthOfficer(BasePermission):
    message = "This endpoint is restricted to health officers."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (user.role == User.Role.HEALTH_OFFICER or user.is_platform_admin)
        )


class IsPatient(BasePermission):
    message = "This endpoint is restricted to patients."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated and user.role == User.Role.PATIENT
        )


class IsPlatformAdmin(BasePermission):
    """Platform-level administrator.

    Reuses the existing `is_platform_admin` property (ADMIN role or superuser)
    rather than introducing a second notion of admin. Administrators are the
    only role permitted to compare villages; worker and officer scoping is
    untouched by this.
    """

    message = "This endpoint is restricted to platform administrators."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_platform_admin)


class IsWorkerOrOfficer(BasePermission):
    message = "This endpoint is restricted to health workers and officers."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (
                user.role in {User.Role.CHW_PHC_WORKER, User.Role.HEALTH_OFFICER}
                or user.is_platform_admin
            )
        )
