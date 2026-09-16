"""Pregnancy Visit Questions — a fixed, controlled question set.

Inspired by the Pregnancy and Infant Cohort Monitoring and Evaluation (PICME)
concept used in Tamil Nadu, but this is a prototype questionnaire for this
project only, not a transcription of an official government form. It is not
directly integrated with the Government of Tamil Nadu PICME system.

Every question shown to a Health Worker comes from this module. Nothing in
the pregnancy views, serializers, or AI guidance agent invents a new
question — this is the single source of truth, mirroring how
`fieldops.models.ChecklistItemTemplate` is the one place an inspection
item's wording lives.

`warning_sign=True` marks the questions this project treats as pregnancy
warning signs (task's own list: vaginal bleeding, severe abdominal pain,
severe headache/blurred vision, reduced/stopped fetal movement, fluid
leakage, difficulty breathing, fever/fits/chills, severe vomiting/unable to
drink water, swelling face/hands/feet, and active labour signs at Visit 4).
A YES answer to any of these is what the deterministic rules layer
(`pregnancy.rules`) escalates — never a judgement the AI guidance agent
makes on its own.
"""

from __future__ import annotations

from typing import Any


class QuestionType:
    YES_NO = "YES_NO"
    DATE = "DATE"


VISIT_1 = 1
VISIT_2 = 2
VISIT_3 = 3
VISIT_4 = 4

VISIT_LABELS: dict[int, str] = {
    VISIT_1: "Visit 1 - First Pregnancy Visit",
    VISIT_2: "Visit 2 - Follow-up ANC Visit",
    VISIT_3: "Visit 3 - Baby Movement / Risk Check",
    VISIT_4: "Visit 4 - Delivery Preparation",
}

#: The four-visit minimum this project tracks as a monitoring target, per
#: the Government of Tamil Nadu's own "4 or more ANC check-ups" pregnancy
#: coverage indicator — a monitoring target, not a substitute for
#: individualized clinical scheduling (task §7/§17).
TARGET_VISIT_COUNT = 4

VISIT_QUESTIONS: dict[int, list[dict[str, Any]]] = {
    VISIT_1: [
        {"key": "lmp_date", "text": "When was your last menstrual period (LMP)?", "type": QuestionType.DATE, "warning_sign": False},
        {"key": "first_pregnancy", "text": "Is this your first pregnancy?", "type": QuestionType.YES_NO, "warning_sign": False},
        {"key": "previous_complications", "text": "Have you had any previous pregnancy complications?", "type": QuestionType.YES_NO, "warning_sign": False},
        {"key": "vaginal_bleeding", "text": "Are you having vaginal bleeding?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "severe_abdominal_pain", "text": "Do you have severe abdominal pain?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "severe_vomiting", "text": "Are you having severe vomiting or unable to drink water?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "fever_chills", "text": "Do you have fever or chills?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "severe_headache_vision", "text": "Do you have severe headache or blurred vision?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "existing_health_problems", "text": "Do you have any existing health problems or take regular medicines?", "type": QuestionType.YES_NO, "warning_sign": False},
        {"key": "iron_folic_started", "text": "Have you started taking iron and folic acid tablets?", "type": QuestionType.YES_NO, "warning_sign": False},
    ],
    VISIT_2: [
        {"key": "vaginal_bleeding", "text": "Are you having vaginal bleeding?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "abdominal_pain_cramps", "text": "Do you have abdominal pain or stomach cramps?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "severe_headache_vision", "text": "Are you having severe headache or blurred vision?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "swelling_face_hands_feet", "text": "Do you have swelling in your face, hands, or feet?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "fever_chills_burning_urination", "text": "Do you have fever, chills, or burning while urinating?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "breathing_difficulty_chest_pain", "text": "Are you having difficulty breathing or chest pain?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "iron_folic_regular", "text": "Are you taking iron and folic acid tablets regularly?", "type": QuestionType.YES_NO, "warning_sign": False},
        {"key": "eating_drinking_adequate", "text": "Are you eating properly and drinking enough water?", "type": QuestionType.YES_NO, "warning_sign": False},
        {"key": "attended_scheduled_anc", "text": "Have you attended the scheduled antenatal check-up?", "type": QuestionType.YES_NO, "warning_sign": False},
        {"key": "difficulty_accessing_services", "text": "Are you facing any difficulty accessing pregnancy-related services?", "type": QuestionType.YES_NO, "warning_sign": False},
    ],
    VISIT_3: [
        {"key": "movement_started", "text": "Have you started feeling the baby's movement?", "type": QuestionType.YES_NO, "warning_sign": False},
        {"key": "movement_reduced_stopped", "text": "Has the baby's movement reduced or stopped?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "vaginal_bleeding", "text": "Are you having vaginal bleeding?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "fluid_leaking", "text": "Is fluid leaking from the vagina?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "severe_abdominal_pain", "text": "Do you have severe abdominal pain?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "severe_headache_vision", "text": "Are you having severe headache or vision problems?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "fever_weakness", "text": "Do you have fever or unusual weakness?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "breathing_difficulty", "text": "Are you having difficulty breathing?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "supplements_regular", "text": "Are you taking your prescribed supplements regularly?", "type": QuestionType.YES_NO, "warning_sign": False},
        {"key": "delivery_hospital_concerns", "text": "Do you have any concerns about delivery or hospital access?", "type": QuestionType.YES_NO, "warning_sign": False},
    ],
    VISIT_4: [
        {"key": "labour_pain_contractions", "text": "Are you having labour pain or regular contractions?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "vaginal_bleeding", "text": "Is there any vaginal bleeding?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "fluid_leaking", "text": "Is fluid leaking from the vagina?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "movement_reduced_stopped", "text": "Has the baby's movement reduced or stopped?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "severe_abdominal_pain", "text": "Do you have severe abdominal pain?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "severe_headache_vision", "text": "Do you have severe headache or blurred vision?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "fever_fits_breathing", "text": "Do you have fever, fits, or difficulty breathing?", "type": QuestionType.YES_NO, "warning_sign": True},
        {"key": "hospital_selected", "text": "Have you selected the hospital for delivery?", "type": QuestionType.YES_NO, "warning_sign": False},
        {"key": "transport_available", "text": "Is transport available for emergency delivery?", "type": QuestionType.YES_NO, "warning_sign": False},
        {"key": "documents_ready", "text": "Do you have all required documents and scheme records?", "type": QuestionType.YES_NO, "warning_sign": False},
    ],
}


def questions_for_visit(visit_number: int) -> list[dict[str, Any]]:
    return VISIT_QUESTIONS.get(int(visit_number), [])


def warning_sign_keys(visit_number: int) -> set[str]:
    return {q["key"] for q in questions_for_visit(visit_number) if q["warning_sign"]}


def valid_question_keys(visit_number: int) -> set[str]:
    return {q["key"] for q in questions_for_visit(visit_number)}
