"""Seed data — not application code. Department names and the checklist
item wording below are prototype, configurable content suitable for this
demonstration; they are not transcribed from an official government
standard (see fieldops/models.py's own module docstring for the same
disclaimer). Idempotent: `get_or_create` means re-running this migration
history (e.g. in a fresh test database) never creates duplicates.
"""

from django.db import migrations

DEPARTMENTS = [
    "Panchayat",
    "Water & Sanitation",
    "Health Department",
    "School / Education",
    "PHC",
    "Other",
]

CHECKLIST_ITEMS = {
    "DRINKING_WATER_SANITATION": [
        "Drinking water source condition",
        "Water storage hygiene",
        "Sanitation facilities",
        "Drainage condition",
        "Wastewater management",
        "General cleanliness",
    ],
    "SCHOOL_ANGANWADI": [
        "Availability of safe drinking water",
        "Toilet facility functioning and clean",
        "Handwashing facility available",
        "Classroom / premises cleanliness",
        "Mid-day meal / nutrition hygiene",
        "First-aid availability",
    ],
    "PUBLIC_PLACE_HYGIENE": [
        "Waste bins available and maintained",
        "Public toilet cleanliness (if present)",
        "Stagnant water / mosquito breeding check",
        "General cleanliness of the area",
        "Public health awareness signage condition",
    ],
    "WASTE_MANAGEMENT": [
        "Household waste segregation practice",
        "Waste collection frequency and adequacy",
        "Disposal site condition",
        "Drainage blockage caused by waste",
        "Community awareness on waste disposal",
    ],
}


def seed(apps, schema_editor):
    Department = apps.get_model("fieldops", "Department")
    for name in DEPARTMENTS:
        Department.objects.get_or_create(name=name)

    ChecklistItemTemplate = apps.get_model("fieldops", "ChecklistItemTemplate")
    for category, items in CHECKLIST_ITEMS.items():
        for order, text in enumerate(items):
            ChecklistItemTemplate.objects.get_or_create(
                category=category, text=text, defaults={"order": order}
            )


def unseed(apps, schema_editor):
    Department = apps.get_model("fieldops", "Department")
    Department.objects.filter(name__in=DEPARTMENTS).delete()
    ChecklistItemTemplate = apps.get_model("fieldops", "ChecklistItemTemplate")
    for category, items in CHECKLIST_ITEMS.items():
        ChecklistItemTemplate.objects.filter(category=category, text__in=items).delete()


class Migration(migrations.Migration):
    dependencies = [("fieldops", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
