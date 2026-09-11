import re

from django.utils import timezone
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from rest_framework import serializers

from core.constants import village_label

from .models import User
from .photos import PhotoError, validate_photo


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


class StaffProfileSerializer(serializers.ModelSerializer):
    """A worker's or officer's professional profile, as others may read it.

    Professional information only: name, role, assigned area, how to reach
    them at work and their qualification. No password, no permission flags and
    no account internals — viewing a colleague's profile must never become a
    way to learn something about the account itself.
    """

    display_name = serializers.CharField(read_only=True)
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    village_name = serializers.CharField(
        source="village.name", default=None, read_only=True
    )
    village_code = serializers.CharField(
        source="village.code", default=None, read_only=True
    )
    village_cluster = serializers.CharField(
        source="village.cluster", default=None, read_only=True
    )
    village_label = serializers.SerializerMethodField()
    facility_name = serializers.CharField(
        source="facility.name", default=None, read_only=True
    )
    photo_url = serializers.CharField(source="photo", read_only=True)
    has_photo = serializers.BooleanField(read_only=True)
    initials = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "role",
            "role_label",
            "display_name",
            "full_name",
            "email",
            "phone_number",
            "staff_id",
            "qualification",
            "experience_years",
            "district",
            "village",
            "village_name",
            "village_code",
            "village_cluster",
            "village_label",
            "facility",
            "facility_name",
            "photo_url",
            "has_photo",
            "initials",
            "profile_updated_at",
        )
        read_only_fields = fields

    def get_village_label(self, obj) -> str:
        """'Village A' where the demonstration mapping has one, else the name."""

        if obj.village_id is None or obj.village is None:
            return ""
        return village_label(obj.village.code, obj.village.name)


class ProfileUpdateSerializer(serializers.ModelSerializer):
    """What a member of staff may change about their own profile.

    Deliberately excludes username, password, role, village and facility:
    credentials and assignments are administered, not self-selected, and the
    brief for this feature was a profile update — not an account change.
    """

    photo = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, trim_whitespace=False
    )

    class Meta:
        model = User
        fields = (
            "full_name",
            "email",
            "phone_number",
            "staff_id",
            "qualification",
            "experience_years",
            "photo",
        )
        extra_kwargs = {
            "full_name": {"required": False, "allow_blank": True},
            "email": {"required": False, "allow_blank": True},
            "phone_number": {"required": False, "allow_blank": True},
            "staff_id": {"required": False, "allow_blank": True},
            "qualification": {"required": False, "allow_blank": True},
            "experience_years": {"required": False, "allow_null": True},
        }

    def validate_full_name(self, value: str) -> str:
        return (value or "").strip()

    def validate_phone_number(self, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            return ""
        if not re.fullmatch(r"[0-9+][0-9 ()+-]{5,24}", cleaned):
            raise serializers.ValidationError(
                "Enter a contact number using digits, spaces, + or -."
            )
        return cleaned

    def validate_experience_years(self, value):
        if value in (None, ""):
            return None
        try:
            years = int(value)
        except (TypeError, ValueError):
            raise serializers.ValidationError("Enter years of experience as a number.")
        if years < 0 or years > 60:
            raise serializers.ValidationError(
                "Enter years of experience between 0 and 60."
            )
        return years

    def validate_photo(self, value):
        try:
            return validate_photo(value)
        except PhotoError as exc:
            raise serializers.ValidationError(str(exc))

    def update(self, instance, validated_data):
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.profile_updated_at = timezone.now()
        instance.save(
            update_fields=[*validated_data.keys(), "profile_updated_at"]
        )
        return instance


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
