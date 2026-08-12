from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from rest_framework import serializers

from .models import User


class UserSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    village_name = serializers.CharField(source="village.name", default=None, read_only=True)
    village_code = serializers.CharField(source="village.code", default=None, read_only=True)
    village_cluster = serializers.CharField(
        source="village.cluster", default=None, read_only=True
    )
    facility_name = serializers.CharField(
        source="facility.name", default=None, read_only=True
    )

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "role",
            "display_name",
            "full_name",
            "email",
            "district",
            "village",
            "village_name",
            "village_code",
            "village_cluster",
            "facility",
            "facility_name",
        )
        read_only_fields = fields


class GramSentinelTokenSerializer(TokenObtainPairSerializer):
    """Adds the role claim to the JWT and returns the user profile on login."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role
        token["display_name"] = user.display_name
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user).data
        return data
