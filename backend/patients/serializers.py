import re

from rest_framework import serializers

from .models import Patient

#: Same convention `users.serializers.ProfileUpdateSerializer` already uses
#: for a staff member's own contact number — reused here rather than a
#: second phone-format rule, so "reasonable format, not overly restrictive"
#: means the same thing everywhere in the project.
PHONE_PATTERN = re.compile(r"[0-9+][0-9 ()+-]{5,24}")

#: Deliberately generous — these exist to catch obvious data-entry mistakes
#: (a misplaced decimal, a stray extra digit), not to encode a clinical
#: judgement about what is "normal". Covers infants through tall/heavy
#: adults.
MIN_HEIGHT_CM = 30
MAX_HEIGHT_CM = 250
MIN_WEIGHT_KG = 1
MAX_WEIGHT_KG = 300


def _validate_phone_number(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    if not PHONE_PATTERN.fullmatch(cleaned):
        raise serializers.ValidationError(
            "Enter a contact number using digits, spaces, + or -."
        )
    return cleaned


def _validate_height_cm(value):
    if value in (None, ""):
        return None
    if value <= 0:
        raise serializers.ValidationError("Height must be a positive number.")
    if not (MIN_HEIGHT_CM <= value <= MAX_HEIGHT_CM):
        raise serializers.ValidationError(
            f"Enter a height between {MIN_HEIGHT_CM} and {MAX_HEIGHT_CM} cm."
        )
    return value


def _validate_weight_kg(value):
    if value in (None, ""):
        return None
    if value <= 0:
        raise serializers.ValidationError("Weight must be a positive number.")
    if not (MIN_WEIGHT_KG <= value <= MAX_WEIGHT_KG):
        raise serializers.ValidationError(
            f"Enter a weight between {MIN_WEIGHT_KG} and {MAX_WEIGHT_KG} kg."
        )
    return value


class PatientSerializer(serializers.ModelSerializer):
    village_name = serializers.CharField(source="village.name", read_only=True)
    village_code = serializers.CharField(source="village.code", read_only=True)
    assessment_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Patient
        fields = (
            "id",
            "patient_code",
            "display_name",
            "age_years",
            "age_months",
            "sex",
            "height_cm",
            "weight_kg",
            "phone_number",
            "house_location",
            "village",
            "village_name",
            "village_code",
            "assessment_count",
            "created_at",
        )
        read_only_fields = ("id", "created_at")


class PatientCreateSerializer(serializers.ModelSerializer):
    """Patient registration, usable from inside the assessment workflow.

    `patient_code` is optional: a worker registering someone mid-assessment
    should not have to invent an identifier, so one is generated from the
    village code when it is left blank. The four patient-detail fields
    (height/weight/phone/house location) are all optional here too — a
    worker who does not have them yet can still register the patient and
    record them later via `PatientDetailUpdateSerializer`.
    """

    patient_code = serializers.CharField(required=False, allow_blank=True)
    height_cm = serializers.FloatField(required=False, allow_null=True)
    weight_kg = serializers.FloatField(required=False, allow_null=True)
    phone_number = serializers.CharField(required=False, allow_blank=True)
    house_location = serializers.CharField(
        required=False, allow_blank=True, max_length=200
    )

    class Meta:
        model = Patient
        fields = (
            "patient_code",
            "display_name",
            "age_years",
            "age_months",
            "sex",
            "height_cm",
            "weight_kg",
            "phone_number",
            "house_location",
            "village",
        )

    def validate_patient_code(self, value):
        value = (value or "").strip()
        if value and Patient.objects.filter(patient_code__iexact=value).exists():
            raise serializers.ValidationError(
                "A patient with this identifier already exists."
            )
        return value

    def validate_height_cm(self, value):
        return _validate_height_cm(value)

    def validate_weight_kg(self, value):
        return _validate_weight_kg(value)

    def validate_phone_number(self, value):
        return _validate_phone_number(value)

    def validate_house_location(self, value):
        return (value or "").strip()

    def validate(self, attrs):
        if attrs.get("age_years") is None and attrs.get("age_months") is None:
            raise serializers.ValidationError(
                {"age_years": "Provide age in years or months."}
            )
        if not (attrs.get("display_name") or "").strip():
            raise serializers.ValidationError(
                {"display_name": "Enter a name or local reference for this patient."}
            )
        return attrs

    def create(self, validated_data):
        if not validated_data.get("patient_code"):
            validated_data["patient_code"] = self._next_code(
                validated_data["village"]
            )
        return super().create(validated_data)

    @staticmethod
    def _next_code(village) -> str:
        """Sequential per-village code, e.g. KVL-P-012."""

        prefix = f"{village.code}-P-"
        existing = Patient.objects.filter(
            patient_code__startswith=prefix
        ).values_list("patient_code", flat=True)

        highest = 0
        for code in existing:
            suffix = code[len(prefix):]
            if suffix.isdigit():
                highest = max(highest, int(suffix))
        return f"{prefix}{highest + 1:03d}"


class PatientDetailUpdateSerializer(serializers.ModelSerializer):
    """`PATCH /api/patients/<id>/` — the four patient-detail fields only.

    Deliberately excludes patient_code, display_name, age, sex and village:
    this endpoint exists to let a worker correct/add a contact number or
    house location they did not have at registration, not to re-open
    identity or village assignment (those stay create-time-only, the same
    boundary `users.serializers.ProfileUpdateSerializer` draws for a staff
    member's own credentials/assignment).
    """

    class Meta:
        model = Patient
        fields = ("height_cm", "weight_kg", "phone_number", "house_location")
        extra_kwargs = {
            "height_cm": {"required": False, "allow_null": True},
            "weight_kg": {"required": False, "allow_null": True},
            "phone_number": {"required": False, "allow_blank": True},
            "house_location": {"required": False, "allow_blank": True},
        }

    def validate_height_cm(self, value):
        return _validate_height_cm(value)

    def validate_weight_kg(self, value):
        return _validate_weight_kg(value)

    def validate_phone_number(self, value):
        return _validate_phone_number(value)

    def validate_house_location(self, value):
        return (value or "").strip()
