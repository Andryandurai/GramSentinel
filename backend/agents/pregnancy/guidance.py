"""Pregnancy Guidance Agent — Phase 9/10 AI assistance, now language-aware
(task §19/§34: "AI-generated user-facing responses must also support the
selected language").

Same architecture as `agents.ruralcare.triage.RiskTriageAgent`: every fact
the guidance references (follow-up status, warning signs, next check-up,
PICME status) is already decided deterministically by `pregnancy.rules`
before this agent runs. The LLM, when configured, only rewrites the
already-decided narrative into plainer language — it cannot change
`follow_up_status`, add or remove a warning sign, or invent a check-up date.
This holds regardless of `language`: the structured fields below are
byte-identical across en/ta/hi requests for the same input (task §42's own
explicit test) — only `visit_summary`/`suggested_action`/`picme_follow_up`
(free-text narrative) vary by language.

Reuses `agents.llm.get_llm_client()` (the same optional, always-falls-back
LLM client every other agent uses) and the platform's shared banned-term
list, extended with pregnancy-specific terms this agent must never emit
(task §10/§11/§37: no diagnosis, no prescription, no autonomous high-risk
declaration). The banned-term guard only runs against the English LLM
output pattern-matching; a non-English LLM completion that fails to
translate the banned concept away is still caught because the guard checks
the raw text for the literal English medical terms an LLM would use even
when replying in Tamil/Hindi (clinical loanwords are commonly left
untranslated) — and regardless, on any guard failure the deterministic,
already-correctly-localized template is used instead, never a raw
unscreened LLM string.
"""

from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from agents.llm import LLMUnavailable, get_llm_client
from core.constants import PROHIBITED_OUTPUT_TERMS

from pregnancy.questionnaire import VISIT_LABELS
from pregnancy.rules import (
    ANC_4PLUS_TARGET_NOT_YET_REACHED,
    FOLLOW_UP_OVERDUE,
    LOW_VISIT_COMPLETION_FOR_STAGE,
    MISSING_NEXT_CHECKUP,
    MISSING_PICME,
    URGENT_CLINICAL_REVIEW,
)

#: Allowed values only — validated again at the serializer layer
#: (`pregnancy.serializers.VisitInputSerializer`). Never accepts an
#: arbitrary client-supplied string (task §34: "do not allow the client to
#: inject arbitrary AI system instructions through this field").
SUPPORTED_LANGUAGES = ("en", "ta", "hi")
DEFAULT_LANGUAGE = "en"

#: Extends the platform-wide banned-term list (Section 41 / Safety R6) with
#: pregnancy-specific terms this agent must never emit — named complications,
#: prescriptions, or an autonomous risk declaration (task §10/§11/§37).
PREGNANCY_BANNED_TERMS = PROHIBITED_OUTPUT_TERMS + (
    "preeclampsia",
    "eclampsia",
    "miscarriage",
    "prescribe",
    "prescription",
    "dosage",
    "high-risk pregnancy",
    "high risk pregnancy",
    "diagnosis",
)

#: One short, controlled instruction per language (task §19: "do not
#: blindly send the entire UI translation dictionary to the LLM. Use a
#: small controlled instruction").
_LLM_LANGUAGE_INSTRUCTION: dict[str, str] = {
    "en": "Respond in English.",
    "ta": "Respond in Tamil. Keep medical terminology clear and understandable.",
    "hi": "Respond in Hindi. Keep medical terminology clear and understandable.",
}

_LLM_SYSTEM_PROMPT_BASE = (
    "You rewrite an already-decided pregnancy follow-up summary into two "
    "plain sentences for a rural health worker. You must not name, suggest "
    "or imply any pregnancy complication or diagnosis. You must not "
    "prescribe medication or a dosage. You must not change the follow-up "
    "status or warning-sign list you are given. You must not use the words "
    "'diagnosis', 'confirmed', 'preeclampsia', 'eclampsia', 'miscarriage', "
    "'prescribe', or 'high-risk' (or their equivalents in the requested "
    "language). Describe only what was reported and what follow-up was "
    "suggested."
)

_URGENT_TEXT: dict[str, str] = {
    "en": (
        "Prompt evaluation by a qualified healthcare professional is required "
        "for the reported warning sign(s). Do not wait for the next scheduled "
        "visit."
    ),
    "ta": (
        "தெரிவிக்கப்பட்ட எச்சரிக்கை அறிகுறி(கள)ுக்கு தகுதியான சுகாதார நிபுணரால் "
        "உடனடி பரிசோதனை தேவை. அடுத்த திட்டமிடப்பட்ட வருகைக்காகக் காத்திருக்க வேண்டாம்."
    ),
    "hi": (
        "बताए गए चेतावनी संकेत(संकेतों) के लिए किसी योग्य स्वास्थ्य विशेषज्ञ द्वारा "
        "तुरंत जांच आवश्यक है। अगली निर्धारित मुलाकात का इंतजार न करें।"
    ),
}

_VISIT_ROUTINE_TEXT: dict[int, dict[str, str]] = {
    1: {
        "en": (
            "Continue routine antenatal care. Confirm iron and folic acid "
            "supplementation has started and schedule the next ANC visit."
        ),
        "ta": (
            "வழக்கமான கருத்தரிப்பு காலப் பராமரிப்பைத் தொடரவும். இரும்புச்சத்து மற்றும் "
            "ஃபோலிக் அமில மாத்திரைகள் தொடங்கப்பட்டதை உறுதிசெய்து, அடுத்த ANC வருகையைத் "
            "திட்டமிடவும்."
        ),
        "hi": (
            "नियमित प्रसवपूर्व देखभाल जारी रखें। आयरन और फोलिक एसिड की गोलियां शुरू "
            "हो चुकी हैं यह सुनिश्चित करें, और अगली ANC मुलाकात तय करें।"
        ),
    },
    2: {
        "en": (
            "Continue scheduled antenatal follow-up. Confirm the next ANC visit "
            "and continue prescribed supplements."
        ),
        "ta": (
            "திட்டமிடப்பட்ட கருத்தரிப்பு காலப் பின்தொடர்தலைத் தொடரவும். அடுத்த ANC "
            "வருகையை உறுதிசெய்து, பரிந்துரைக்கப்பட்ட சத்துணவு மாத்திரைகளைத் தொடரவும்."
        ),
        "hi": (
            "निर्धारित प्रसवपूर्व फॉलो-अप जारी रखें। अगली ANC मुलाकात सुनिश्चित करें और "
            "निर्धारित पूरक (सप्लीमेंट) जारी रखें।"
        ),
    },
    3: {
        "en": (
            "Continue monitoring fetal movement and routine antenatal care. "
            "Confirm the next check-up and delivery plan."
        ),
        "ta": (
            "கருவின் அசைவைக் கண்காணிப்பதையும் வழக்கமான கருத்தரிப்பு காலப் "
            "பராமரிப்பையும் தொடரவும். அடுத்த பரிசோதனை மற்றும் பிரசவத் திட்டத்தை "
            "உறுதிசெய்யவும்."
        ),
        "hi": (
            "भ्रूण की हलचल की निगरानी और नियमित प्रसवपूर्व देखभाल जारी रखें। अगली जांच "
            "और प्रसव योजना की पुष्टि करें।"
        ),
    },
    4: {
        "en": (
            "Confirm delivery preparation: hospital selection, emergency "
            "transport, and required documents. Continue monitoring for labour "
            "signs."
        ),
        "ta": (
            "பிரசவத் தயார்நிலையை உறுதிசெய்யவும்: மருத்துவமனைத் தேர்வு, அவசர "
            "போக்குவரத்து, தேவையான ஆவணங்கள். பிரசவ அறிகுறிகளுக்காகக் கண்காணிப்பைத் "
            "தொடரவும்."
        ),
        "hi": (
            "प्रसव की तैयारी सुनिश्चित करें: अस्पताल का चयन, आपातकालीन परिवहन, और "
            "आवश्यक दस्तावेज़। प्रसव के संकेतों की निगरानी जारी रखें।"
        ),
    },
}

_OVERDUE_ADDENDUM: dict[str, str] = {
    "en": "The scheduled check-up date has passed.",
    "ta": "திட்டமிடப்பட்ட பரிசோதனை தேதி கடந்துவிட்டது.",
    "hi": "निर्धारित जांच की तारीख निकल चुकी है।",
}

#: `pregnancy.questionnaire.VISIT_LABELS` stays English-only (it is also
#: used server-side for logging/admin contexts where a stable English label
#: is preferable) — this local mapping is only for the narrative text a
#: worker actually reads in their selected language.
_VISIT_LABEL_TRANSLATIONS: dict[int, dict[str, str]] = {
    1: {"en": "Visit 1 - First Pregnancy Visit", "ta": "வருகை 1 - முதல் கர்ப்ப வருகை", "hi": "यात्रा 1 - पहली गर्भावस्था मुलाकात"},
    2: {"en": "Visit 2 - Follow-up ANC Visit", "ta": "வருகை 2 - தொடர் ANC வருகை", "hi": "यात्रा 2 - फॉलो-अप ANC मुलाकात"},
    3: {"en": "Visit 3 - Baby Movement / Risk Check", "ta": "வருகை 3 - குழந்தையின் அசைவு / ஆபத்து சோதனை", "hi": "यात्रा 3 - शिशु हलचल / जोखिम जांच"},
    4: {"en": "Visit 4 - Delivery Preparation", "ta": "வருகை 4 - பிரசவத் தயார்நிலை", "hi": "यात्रा 4 - प्रसव की तैयारी"},
}


def _visit_label(visit_number: int, language: str) -> str:
    labels = _VISIT_LABEL_TRANSLATIONS.get(visit_number, _VISIT_LABEL_TRANSLATIONS[1])
    return labels[language]


_COVERAGE_ADDENDUM: dict[str, str] = {
    "en": "Fewer visits than the monitoring target have been completed so far.",
    "ta": "இதுவரை கண்காணிப்பு இலக்கை விட குறைவான வருகைகள் நிறைவடைந்துள்ளன.",
    "hi": "अब तक निगरानी लक्ष्य से कम मुलाकातें पूरी हुई हैं।",
}

_SUGGESTED_ACTION: dict[str, dict[str, str]] = {
    "reschedule": {
        "en": "Reschedule the missed check-up as soon as possible.",
        "ta": "தவறவிட்ட பரிசோதனையை விரைவில் மீண்டும் திட்டமிடவும்.",
        "hi": "छूटी हुई जांच को जल्द से जल्द पुनर्निर्धारित करें।",
    },
    "record_checkup": {
        "en": "Record a next check-up date before ending this visit.",
        "ta": "இந்த வருகையை முடிக்கும் முன் அடுத்த பரிசோதனை தேதியைப் பதிவு செய்யவும்.",
        "hi": "इस मुलाकात को समाप्त करने से पहले अगली जांच की तारीख दर्ज करें।",
    },
    "routine": {
        "en": "Continue routine antenatal follow-up as scheduled.",
        "ta": "திட்டமிட்டபடி வழக்கமான கருத்தரிப்பு காலப் பின்தொடர்தலைத் தொடரவும்.",
        "hi": "निर्धारित अनुसार नियमित प्रसवपूर्व फॉलो-अप जारी रखें।",
    },
}

_PICME_FOLLOW_UP: dict[str, dict[str, str]] = {
    "recorded": {
        "en": "PICME/RCH ID recorded.",
        "ta": "PICME/RCH ID பதிவு செய்யப்பட்டது.",
        "hi": "PICME/RCH ID दर्ज किया गया।",
    },
    "missing": {
        "en": (
            "Enter the PICME/RCH ID once provided through the appropriate "
            "government registration process."
        ),
        "ta": (
            "பொருத்தமான அரசாங்கப் பதிவு முறையின் மூலம் வழங்கப்பட்டதும் PICME/RCH ID "
            "ஐ உள்ளிடவும்."
        ),
        "hi": (
            "उपयुक्त सरकारी पंजीकरण प्रक्रिया के माध्यम से मिलने पर PICME/RCH ID दर्ज "
            "करें।"
        ),
    },
}


def _language_or_default(language: str | None) -> str:
    if language in SUPPORTED_LANGUAGES:
        return language
    return DEFAULT_LANGUAGE


class PregnancyGuidanceAgent(BaseAgent):
    name = "PregnancyGuidanceAgent"
    display_name = "Pregnancy Follow-up Guidance"
    purpose = "Produced advisory follow-up guidance for a recorded pregnancy visit."
    layer = "RURALCARE"
    stage = "DOMAIN_REASONING"

    def summarise_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "visit_number": payload.get("visit_number"),
            "warning_sign_count": len(payload.get("warning_signs") or []),
            "rule_count": len(payload.get("rule_flags") or []),
            "language": _language_or_default(payload.get("language")),
        }

    def summarise_output(self, output: dict[str, Any]) -> str:
        return f"Follow-up status: {output.get('follow_up_status', 'UNKNOWN')}."

    def handle(self, payload: dict[str, Any], context: Any) -> dict[str, Any]:
        visit_number: int = int(payload["visit_number"])
        warning_signs: list[str] = payload.get("warning_signs") or []
        rule_flags: list[dict[str, Any]] = payload.get("rule_flags") or []
        next_checkup_date = payload.get("next_checkup_date")
        picme_status = payload.get("picme_rch_status")
        completed_visit_count = payload.get("completed_visit_count", 0)
        language = _language_or_default(payload.get("language"))

        rule_names = {f["rule"] for f in rule_flags}
        requires_human_review = True  # Always true — task §11/§37, never conditional.

        # Structured fields below are derived purely from `rule_names`/
        # `warning_signs`/dates — identical for every language (task §42).
        if URGENT_CLINICAL_REVIEW in rule_names:
            follow_up_status = "URGENT_REVIEW_REQUIRED"
        elif FOLLOW_UP_OVERDUE in rule_names:
            follow_up_status = "OVERDUE"
        elif MISSING_NEXT_CHECKUP in rule_names:
            follow_up_status = "NEXT_CHECKUP_NOT_RECORDED"
        else:
            follow_up_status = "DUE" if next_checkup_date else "SCHEDULED"

        deterministic_summary = self._deterministic_summary(
            visit_number, warning_signs, rule_names, language
        )
        suggested_action = self._suggested_action(warning_signs, rule_names, language)

        summary, used_llm = self._maybe_polish(
            deterministic_summary, visit_number, warning_signs, rule_flags, language
        )

        if picme_status == "AVAILABLE":
            picme_follow_up = _PICME_FOLLOW_UP["recorded"][language]
        elif MISSING_PICME in rule_names:
            picme_follow_up = _PICME_FOLLOW_UP["missing"][language]
        else:
            picme_follow_up = ""

        missing_information = [
            f["label"] for f in rule_flags if f["rule"] in {MISSING_NEXT_CHECKUP, MISSING_PICME}
        ]

        return {
            "visit_summary": summary,
            "deterministic_summary": deterministic_summary,
            "follow_up_status": follow_up_status,
            "next_checkup": next_checkup_date,
            "warning_signs": warning_signs,
            "suggested_action": suggested_action,
            "picme_follow_up": picme_follow_up,
            "missing_information": missing_information,
            "requires_human_review": requires_human_review,
            "completed_visit_count": completed_visit_count,
            "language": language,
            "_used_llm": used_llm,
        }

    @staticmethod
    def _deterministic_summary(
        visit_number: int, warning_signs: list[str], rule_names: set[str], language: str
    ) -> str:
        visit_label = _visit_label(visit_number, language)
        if warning_signs:
            return f"{visit_label}: {len(warning_signs)}. {_URGENT_TEXT[language]}"

        if FOLLOW_UP_OVERDUE in rule_names:
            return f"{visit_label}. {_OVERDUE_ADDENDUM[language]}"

        routine = _VISIT_ROUTINE_TEXT.get(visit_number, _VISIT_ROUTINE_TEXT[1])[language]
        extra = ""
        if ANC_4PLUS_TARGET_NOT_YET_REACHED in rule_names or LOW_VISIT_COMPLETION_FOR_STAGE in rule_names:
            extra = f" {_COVERAGE_ADDENDUM[language]}"
        return f"{visit_label}. {routine}{extra}"

    @staticmethod
    def _suggested_action(warning_signs: list[str], rule_names: set[str], language: str) -> str:
        if warning_signs:
            return _URGENT_TEXT[language]
        if FOLLOW_UP_OVERDUE in rule_names:
            return _SUGGESTED_ACTION["reschedule"][language]
        if MISSING_NEXT_CHECKUP in rule_names:
            return _SUGGESTED_ACTION["record_checkup"][language]
        return _SUGGESTED_ACTION["routine"][language]

    def _maybe_polish(
        self,
        deterministic: str,
        visit_number: int,
        warning_signs: list[str],
        rule_flags: list[dict[str, Any]],
        language: str,
    ) -> tuple[str, bool]:
        """Ask the LLM for plainer wording, in the requested language; keep
        the (already correctly-localized) template on any failure or
        banned-term violation — identical guard shape to
        `RiskTriageAgent._maybe_polish`."""

        client = get_llm_client()
        if not client.available:
            return deterministic, False
        try:
            system_prompt = f"{_LLM_SYSTEM_PROMPT_BASE} {_LLM_LANGUAGE_INSTRUCTION[language]}"
            text = client.summarise(
                system_prompt,
                (
                    f"Visit: {VISIT_LABELS.get(visit_number, visit_number)}\n"
                    f"Warning signs reported (fixed, do not change): "
                    f"{', '.join(warning_signs) or 'none'}\n"
                    f"Follow-up flags: {', '.join(f['rule'] for f in rule_flags) or 'none'}\n"
                    f"Current wording: {deterministic}"
                ),
                max_tokens=200,
            )
            lowered = text.lower()
            if any(bad in lowered for bad in PREGNANCY_BANNED_TERMS):
                return deterministic, False
            return text, True
        except LLMUnavailable:
            return deterministic, False
