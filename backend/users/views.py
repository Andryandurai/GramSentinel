from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from core.constants import MEDICAL_DISCLAIMER

from .serializers import GramSentinelTokenSerializer, UserSerializer


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
