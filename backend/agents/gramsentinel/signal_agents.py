"""Agents 1-6 — one per community source type.

Every one of them emits the same structured evidence card: source, location,
time window, baseline, current value, change, data quality, status,
explanation. That uniformity is what lets the Cluster Detection Agent and the
Safety Engine compare them mechanically instead of parsing prose.

None of these agents calls an LLM. They are baseline comparison and threshold
arithmetic.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings

from agents.base import BaseAgent
from core.constants import (
    CONTEXT_SOURCE_KINDS,
    DataQuality,
    EvidenceStatus,
    SourceKind,
)


def _thresholds() -> dict[str, float]:
    return settings.GRAMSENTINEL["ANOMALY_THRESHOLDS"]


class BaseSignalAgent(BaseAgent):
    """Shared evidence-card construction.

    Subclasses supply the source kind and the anomaly decision; everything else
    — the card shape, the missing-data handling, the quality flag — is common
    so that no source can accidentally present itself differently.
    """

    layer = "GRAMSENTINEL"
    stage = "DOMAIN_REASONING"
    source_kind: str = ""
    signal_label: str = ""
    unit: str = ""

    def summarise_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "village_code": payload.get("village_code"),
            "week_label": payload.get("week_label"),
            "is_reported": payload.get("is_reported", True),
        }

    def summarise_output(self, output: dict[str, Any]) -> str:
        card = output.get("evidence_card") or {}
        status = card.get("status", "")

        if status == EvidenceStatus.NOT_REPORTED:
            return f"{self.signal_label}: not submitted this week (recorded as missing)."
        if status == EvidenceStatus.INSUFFICIENT_DATA:
            return f"{self.signal_label}: no usable baseline to compare against."

        change = card.get("change_pct")
        current, baseline = card.get("current_value"), card.get("baseline")
        movement = (
            f"{change:+.0f}% against a baseline of {baseline:g}"
            if change is not None and baseline is not None
            else f"{current:g}" if current is not None else "no value"
        )
        verdict = {
            EvidenceStatus.ANOMALY_DETECTED: "above the expected range",
            EvidenceStatus.SUPPORTING_CONTEXT: "notable, treated as context only",
            EvidenceStatus.CORROBORATING: "corroborating evidence",
        }.get(status, "within the expected range")
        return f"{self.signal_label}: {movement} — {verdict}."

    # -- hooks ---------------------------------------------------------
    def decide(self, change_pct: float | None, payload: dict[str, Any]) -> tuple[bool, str]:
        """Return (is_anomalous, explanation)."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    def handle(self, payload: dict[str, Any], context: Any) -> dict[str, Any]:
        is_reported = bool(payload.get("is_reported", True))
        value = payload.get("value")
        baseline = payload.get("baseline")
        quality = payload.get("data_quality") or DataQuality.GOOD

        # Missing data is never coerced to zero. It is reported as absent, and
        # it contributes nothing toward corroboration.
        if not is_reported or value is None:
            return self._card(
                payload,
                value=None,
                baseline=baseline,
                change_pct=None,
                status=EvidenceStatus.NOT_REPORTED,
                quality=DataQuality.MISSING,
                is_corroborating=False,
                is_reported=False,
                explanation=(
                    f"{self.signal_label} was not submitted for this window. "
                    "Recorded as missing — absence of a report is not absence "
                    "of cases."
                ),
            )

        if baseline in (None, 0):
            return self._card(
                payload,
                value=value,
                baseline=baseline,
                change_pct=None,
                status=EvidenceStatus.INSUFFICIENT_DATA,
                quality=DataQuality.POOR,
                is_corroborating=False,
                is_reported=True,
                explanation=(
                    f"No usable baseline for {self.signal_label}; deviation "
                    "cannot be assessed."
                ),
            )

        change_pct = round((value - baseline) / baseline * 100.0, 1)
        anomalous, explanation = self.decide(change_pct, payload)

        status = (
            EvidenceStatus.ANOMALY_DETECTED if anomalous else EvidenceStatus.NORMAL
        )
        corroborating = anomalous and self.source_kind not in CONTEXT_SOURCE_KINDS

        return self._card(
            payload,
            value=value,
            baseline=baseline,
            change_pct=change_pct,
            status=status,
            quality=quality,
            is_corroborating=corroborating,
            is_reported=True,
            explanation=explanation,
        )

    def _card(
        self,
        payload: dict[str, Any],
        *,
        value: float | None,
        baseline: float | None,
        change_pct: float | None,
        status: str,
        quality: str,
        is_corroborating: bool,
        is_reported: bool,
        explanation: str,
    ) -> dict[str, Any]:
        return {
            "evidence_card": {
                "source_kind": self.source_kind,
                "source_name": payload.get("source_name", self.signal_label),
                "signal": self.signal_label,
                "category": payload.get("category"),
                "village_code": payload.get("village_code"),
                "village_name": payload.get("village_name", ""),
                "cluster": payload.get("cluster", ""),
                "week_label": payload.get("week_label"),
                "period_start": payload.get("period_start"),
                "period_end": payload.get("period_end"),
                "baseline": baseline,
                "current_value": value,
                "change_pct": change_pct,
                "unit": payload.get("unit") or self.unit,
                "data_quality": quality,
                "status": status,
                "is_corroborating": is_corroborating,
                "is_reported": is_reported,
                "explanation": explanation,
                "produced_by_agent": self.name,
            }
        }


class CHWSignalAgent(BaseSignalAgent):
    name = "CHWSignalAgent"
    display_name = "CHW Signal"
    purpose = "Compared community health worker reports against their baseline."
    source_kind = SourceKind.CHW
    signal_label = "CHW-reported cases"
    unit = "reports"

    def decide(self, change_pct, payload):
        threshold = _thresholds()["CHW"]
        if change_pct >= threshold:
            return True, (
                f"Reported cases are {change_pct:+.0f}% against this village's "
                f"own recent baseline (threshold {threshold:.0f}%)."
            )
        return False, (
            f"Reported cases are {change_pct:+.0f}% against baseline, within the "
            f"expected range (threshold {threshold:.0f}%)."
        )


class PHCSignalAgent(BaseSignalAgent):
    name = "PHCSignalAgent"
    display_name = "PHC Signal"
    purpose = "Compared primary health centre activity against its baseline."
    source_kind = SourceKind.PHC
    signal_label = "PHC encounters"
    unit = "encounters"

    def decide(self, change_pct, payload):
        threshold = _thresholds()["PHC"]
        if change_pct >= threshold:
            return True, (
                f"Facility encounters are {change_pct:+.0f}% against the rolling "
                f"baseline (threshold {threshold:.0f}%)."
            )
        return False, (
            f"Facility encounters are {change_pct:+.0f}% against the rolling "
            "baseline, within the expected range."
        )


class PharmacySignalAgent(BaseSignalAgent):
    name = "PharmacySignalAgent"
    display_name = "Pharmacy Signal"
    purpose = "Compared aggregated medicine-category demand against its baseline."
    source_kind = SourceKind.PHARMACY
    signal_label = "Medicine-category demand"
    unit = "units"

    def decide(self, change_pct, payload):
        threshold = _thresholds()["PHARMACY"]
        if change_pct >= threshold:
            return True, (
                f"Aggregated category demand is {change_pct:+.0f}% against "
                f"baseline (threshold {threshold:.0f}%). Captures people who "
                "self-medicate and never reach a facility."
            )
        return False, (
            f"Aggregated category demand is {change_pct:+.0f}% against baseline, "
            "within the expected range."
        )


class SchoolSignalAgent(BaseSignalAgent):
    name = "SchoolSignalAgent"
    display_name = "School Signal"
    purpose = "Compared school absenteeism against its typical level."
    source_kind = SourceKind.SCHOOL
    signal_label = "School absenteeism"
    unit = "%"

    def decide(self, change_pct, payload):
        threshold = _thresholds()["SCHOOL"]
        point_rise_threshold = settings.GRAMSENTINEL["SCHOOL_ABSOLUTE_POINT_RISE"]
        value = payload.get("value") or 0.0
        baseline = payload.get("baseline") or 0.0
        point_rise = value - baseline

        # Absenteeism is a percentage already, so a jump in percentage points
        # matters independently of the relative change.
        if change_pct >= threshold or point_rise >= point_rise_threshold:
            return True, (
                f"Absenteeism is {value:.0f}% against a typical {baseline:.0f}% "
                f"({point_rise:+.0f} percentage points, {change_pct:+.0f}%). "
                "Children are often affected before facility data moves."
            )
        return False, (
            f"Absenteeism is {value:.0f}% against a typical {baseline:.0f}%, "
            "within the expected range."
        )


class WeatherSignalAgent(BaseSignalAgent):
    """Environmental context — never counted as independent corroboration."""

    name = "WeatherSignalAgent"
    display_name = "Weather / Environment"
    purpose = "Checked environmental conditions that may make a pattern more plausible."
    source_kind = SourceKind.WEATHER
    signal_label = "Rainfall / environmental conditions"
    unit = "mm"

    def decide(self, change_pct, payload):
        threshold = float(payload.get("anomaly_threshold_pct", 60.0))
        if change_pct >= threshold:
            return True, (
                f"Rainfall is {change_pct:+.0f}% against the seasonal norm. "
                "Environmental context only: this can make a pattern more "
                "plausible but is not evidence of one."
            )
        return False, (
            f"Rainfall is {change_pct:+.0f}% against the seasonal norm; no "
            "notable environmental condition."
        )

    def handle(self, payload: dict[str, Any], context: Any) -> dict[str, Any]:
        result = super().handle(payload, context)
        card = result["evidence_card"]
        if card["status"] == EvidenceStatus.ANOMALY_DETECTED:
            card["status"] = EvidenceStatus.SUPPORTING_CONTEXT
        card["is_corroborating"] = False
        return result


class LabEvidenceAgent(BaseSignalAgent):
    """Aggregated confirmation counts — high specificity, never individual results."""

    name = "LabEvidenceAgent"
    display_name = "Laboratory Evidence"
    purpose = "Registered aggregated laboratory confirmations as corroborating evidence."
    source_kind = SourceKind.LAB
    signal_label = "Laboratory confirmations"
    unit = "confirmations"

    def handle(self, payload: dict[str, Any], context: Any) -> dict[str, Any]:
        is_reported = bool(payload.get("is_reported", True))
        value = payload.get("value")

        if not is_reported or value is None:
            return self._card(
                payload,
                value=None,
                baseline=payload.get("baseline"),
                change_pct=None,
                status=EvidenceStatus.NOT_REPORTED,
                quality=DataQuality.MISSING,
                is_corroborating=False,
                is_reported=False,
                explanation=(
                    "No laboratory feed for this window. Recorded as missing, "
                    "not as zero confirmations."
                ),
            )

        minimum = settings.GRAMSENTINEL["LAB_MIN_CONFIRMATIONS"]
        count = int(value)
        # A small absolute count is disproportionately informative here, so this
        # agent works on a floor rather than a percentage change.
        if count >= minimum:
            return self._card(
                payload,
                value=float(count),
                baseline=payload.get("baseline"),
                change_pct=None,
                status=EvidenceStatus.CORROBORATING,
                quality=payload.get("data_quality") or DataQuality.GOOD,
                is_corroborating=True,
                is_reported=True,
                explanation=(
                    f"{count} aggregated laboratory confirmation(s) in this "
                    "window. Aggregate counts only — never individual results."
                ),
            )
        return self._card(
            payload,
            value=float(count),
            baseline=payload.get("baseline"),
            change_pct=None,
            status=EvidenceStatus.NORMAL,
            quality=payload.get("data_quality") or DataQuality.GOOD,
            is_corroborating=False,
            is_reported=True,
            explanation="No relevant laboratory confirmations in this window.",
        )


SIGNAL_AGENTS: dict[str, type[BaseSignalAgent]] = {
    SourceKind.CHW: CHWSignalAgent,
    SourceKind.PHC: PHCSignalAgent,
    SourceKind.PHARMACY: PharmacySignalAgent,
    SourceKind.SCHOOL: SchoolSignalAgent,
    SourceKind.WEATHER: WeatherSignalAgent,
    SourceKind.LAB: LabEvidenceAgent,
}
