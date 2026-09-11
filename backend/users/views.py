from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from core.constants import MEDICAL_DISCLAIMER, village_label
from core.models import Village

from .models import User
from .permissions import IsHealthOfficer, IsWorkerOrOfficer
from .photos import ACCEPTED_LABEL, MAX_PHOTO_BYTES, MAX_PHOTO_MB_LABEL
from .scoping import scoped_village_id
from .serializers import (
    GramSentinelTokenSerializer,
    ProfileUpdateSerializer,
    StaffProfileSerializer,
    UserSerializer,
)

#: Roles that have a professional profile. Patients are deliberately excluded:
#: the patient portal is a personal health record, not a staff directory.
STAFF_ROLES = (User.Role.CHW_PHC_WORKER, User.Role.HEALTH_OFFICER)

PHOTO_LIMITS = {
    "max_bytes": MAX_PHOTO_BYTES,
    "max_size_label": MAX_PHOTO_MB_LABEL,
    "accepted_label": ACCEPTED_LABEL,
    "accepted_types": ["image/png", "image/jpeg", "image/webp"],
}

PROFILE_NOTE = (
    "Professional profile information. Your username, password and assigned "
    "area are managed by your administrator and are not changed here."
)


class LoginView(TokenObtainPairView):
    """POST /api/auth/login/ -> {access, refresh, user}."""

    serializer_class = GramSentinelTokenSerializer
    permission_classes = ()

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK:
            response.data["disclaimer"] = MEDICAL_DISCLAIMER
        return response


class MeView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        return Response(
            {
                "user": UserSerializer(request.user).data,
                "disclaimer": MEDICAL_DISCLAIMER,
            }
        )


class MyProfileView(APIView):
    """A member of staff's own professional profile.

        GET   /api/profile/     read it
        PATCH /api/profile/     update the fields they own

    Authentication is untouched by this endpoint: it cannot change a username,
    a password, a role or a village assignment.
    """

    permission_classes = (IsWorkerOrOfficer,)

    def get(self, request):
        return Response(self._payload(request.user))

    def patch(self, request):
        serializer = ProfileUpdateSerializer(
            request.user, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {
                **self._payload(request.user),
                "saved": True,
                "message": "Your profile has been updated.",
            }
        )

    @staticmethod
    def _payload(user) -> dict:
        return {
            "profile": StaffProfileSerializer(user).data,
            "photo_limits": PHOTO_LIMITS,
            "note": PROFILE_NOTE,
            "editable_fields": list(ProfileUpdateSerializer.Meta.fields),
        }


class StaffProfileListView(APIView):
    """The staff directory, scoped exactly as everything else is.

        Health officer  -> the workers and officers of their own village.
                           An officer with no village assigned supervises the
                           whole district and sees all of it, which is the same
                           rule `users.scoping` applies everywhere.
        Administrator   -> every village, filterable with ?village=CODE.

    Village isolation is applied to the queryset before anything is serialised,
    so a Village B officer cannot reach a Village A worker's profile here or
    anywhere downstream of here.
    """

    permission_classes = (IsHealthOfficer,)

    def get(self, request):
        staff = User.objects.filter(
            role__in=STAFF_ROLES, is_active=True
        ).select_related("village", "facility")

        village_id = scoped_village_id(request.user)
        if village_id is not None:
            staff = staff.filter(village_id=village_id)

        requested = (request.query_params.get("village") or "").strip()
        notice = ""
        if requested and requested.lower() != "all":
            village = Village.objects.filter(code__iexact=requested).first()
            if village is None:
                notice = "That village could not be found, so all permitted areas are shown."
            else:
                staff = staff.filter(village_id=village.id)

        role = (request.query_params.get("role") or "").strip().upper()
        if role in {User.Role.CHW_PHC_WORKER, User.Role.HEALTH_OFFICER}:
            staff = staff.filter(role=role)

        rows = StaffProfileSerializer(
            staff.order_by("village__name", "role", "full_name", "username"),
            many=True,
        ).data

        return Response(
            {
                "scope": {
                    "is_district_wide": village_id is None,
                    "village_code": (
                        request.user.village.code if request.user.village else None
                    ),
                    "village_name": (
                        request.user.village.name if request.user.village else None
                    ),
                    "notice": notice,
                },
                "villages": self._villages(village_id),
                "profiles": rows,
                "groups": self._grouped(rows),
                "counts": {
                    "workers": sum(
                        1 for r in rows if r["role"] == User.Role.CHW_PHC_WORKER
                    ),
                    "officers": sum(
                        1 for r in rows if r["role"] == User.Role.HEALTH_OFFICER
                    ),
                    "total": len(rows),
                },
                "is_empty": not rows,
                "empty_message": "No staff profiles are available for this area.",
                "note": (
                    "Professional profile information for the staff assigned to "
                    "your area."
                ),
            }
        )

    @staticmethod
    def _villages(village_id: int | None) -> list[dict]:
        queryset = Village.objects.all().order_by("code")
        if village_id is not None:
            queryset = queryset.filter(id=village_id)
        return [
            {
                "code": v.code,
                "name": v.name,
                "label": village_label(v.code, v.name),
                "cluster": v.cluster,
            }
            for v in queryset
        ]

    @staticmethod
    def _grouped(rows: list[dict]) -> list[dict]:
        """One entry per village, so 'who works where' is answerable at a glance."""

        groups: dict[str, dict] = {}
        for row in rows:
            code = row.get("village_code") or ""
            bucket = groups.setdefault(
                code,
                {
                    "village_code": code,
                    "village_name": row.get("village_name") or "Not assigned",
                    "village_label": row.get("village_label") or "Not assigned",
                    "workers": [],
                    "officers": [],
                },
            )
            if row["role"] == User.Role.CHW_PHC_WORKER:
                bucket["workers"].append(row)
            else:
                bucket["officers"].append(row)
        return sorted(groups.values(), key=lambda g: g["village_label"])


class StaffProfileDetailView(APIView):
    """One colleague's profile, subject to the same village scoping.

    A profile outside the caller's permitted area is reported as not found
    rather than forbidden, so the endpoint does not confirm that an account in
    another village exists.
    """

    permission_classes = (IsHealthOfficer,)

    def get(self, request, pk: int):
        staff = User.objects.filter(
            pk=pk, role__in=STAFF_ROLES, is_active=True
        ).select_related("village", "facility")

        village_id = scoped_village_id(request.user)
        if village_id is not None:
            staff = staff.filter(village_id=village_id)

        member = staff.first()
        if member is None:
            return Response(
                {"detail": "That staff profile is not available for your area."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response({"profile": StaffProfileSerializer(member).data})
