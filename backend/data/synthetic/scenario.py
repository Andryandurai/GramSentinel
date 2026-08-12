"""The Village Cluster A demonstration scenario.

SYNTHETIC DEMONSTRATION DATA — NOT REAL PATIENT DATA.

Every number below is invented for the demonstration. No real pharmacy, school,
laboratory, PHC or government data is used, and none is claimed.

Determinism matters here more than realism-of-noise: the demo must produce the
same alert every single time it is run. So the scenario is a fixed table of
baselines and current values, not a random generator. Anomaly detection still
does real arithmetic against real baselines — but the inputs never vary.

Shape of the scenario:

  Kovilur (Village Cluster A)      -> four independent sources rising, plus a
                                      lab confirmation and heavy rainfall.
                                      Expected: PASS, HIGH severity.
  Ariyanur (Village Cluster A)     -> one source rising only.
                                      Expected: DOWNGRADE, no high-priority
                                      alert. This is the negative control that
                                      shows the corroboration rule working.
  Melur (Village Cluster B)        -> quiet, with one source not reporting.
                                      Expected: no alert; the missing source is
                                      shown as missing, never as zero.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

CLUSTER_A = "Village Cluster A"
CLUSTER_B = "Village Cluster B"

VILLAGES: list[dict[str, Any]] = [
    {
        "code": "KVL",
        "name": "Kovilur",
        "cluster": CLUSTER_A,
        "block": "Thiruvannamalai North",
        "district": "Thiruvannamalai",
        "population": 4200,
    },
    {
        "code": "ARY",
        "name": "Ariyanur",
        "cluster": CLUSTER_A,
        "block": "Thiruvannamalai North",
        "district": "Thiruvannamalai",
        "population": 2600,
    },
    {
        "code": "MLR",
        "name": "Melur",
        "cluster": CLUSTER_B,
        "block": "Thiruvannamalai South",
        "district": "Thiruvannamalai",
        "population": 3100,
    },
]

FACILITIES: list[dict[str, Any]] = [
    {"code": "PHC-KVL", "name": "Kovilur PHC", "kind": "PHC", "village": "KVL"},
    {"code": "PHR-KVL", "name": "Kovilur Medical Store", "kind": "PHARMACY", "village": "KVL"},
    {"code": "SCH-KVL", "name": "Kovilur Panchayat School", "kind": "SCHOOL", "village": "KVL"},
    {"code": "LAB-KVL", "name": "Block Laboratory (Kovilur catchment)", "kind": "LAB", "village": "KVL"},
    {"code": "PHC-ARY", "name": "Ariyanur PHC", "kind": "PHC", "village": "ARY"},
    {"code": "PHR-ARY", "name": "Ariyanur Medical Store", "kind": "PHARMACY", "village": "ARY"},
    {"code": "SCH-ARY", "name": "Ariyanur Middle School", "kind": "SCHOOL", "village": "ARY"},
    {"code": "PHC-MLR", "name": "Melur PHC", "kind": "PHC", "village": "MLR"},
    {"code": "PHR-MLR", "name": "Melur Medical Store", "kind": "PHARMACY", "village": "MLR"},
    {"code": "SCH-MLR", "name": "Melur Primary School", "kind": "SCHOOL", "village": "MLR"},
]

#: (code, name, kind, channel, village) — `channel` records how the source
#: *would* arrive in a real deployment. All are simulated here.
DATA_SOURCES: list[dict[str, Any]] = [
    # Kovilur — the cluster under demonstration
    {"code": "CHW-KVL", "name": "CHW reports — Kovilur", "kind": "CHW", "channel": "PORTAL", "village": "KVL"},
    {"code": "PHC-SIG-KVL", "name": "Kovilur PHC aggregate trends", "kind": "PHC", "channel": "API", "village": "KVL", "facility": "PHC-KVL"},
    {"code": "PHR-SIG-KVL", "name": "Kovilur pharmacy category trends", "kind": "PHARMACY", "channel": "EXPORT", "village": "KVL", "facility": "PHR-KVL"},
    {"code": "SCH-SIG-KVL", "name": "Kovilur school absenteeism", "kind": "SCHOOL", "channel": "PORTAL", "village": "KVL", "facility": "SCH-KVL"},
    {"code": "WTH-SIG-KVL", "name": "Rainfall feed — Kovilur", "kind": "WEATHER", "channel": "PUBLIC_FEED", "village": "KVL"},
    {"code": "LAB-SIG-KVL", "name": "Block laboratory confirmations", "kind": "LAB", "channel": "API", "village": "KVL", "facility": "LAB-KVL"},
    # Ariyanur — single-source control
    {"code": "CHW-ARY", "name": "CHW reports — Ariyanur", "kind": "CHW", "channel": "PORTAL", "village": "ARY"},
    {"code": "PHC-SIG-ARY", "name": "Ariyanur PHC aggregate trends", "kind": "PHC", "channel": "API", "village": "ARY", "facility": "PHC-ARY"},
    {"code": "PHR-SIG-ARY", "name": "Ariyanur pharmacy category trends", "kind": "PHARMACY", "channel": "EXPORT", "village": "ARY", "facility": "PHR-ARY"},
    {"code": "SCH-SIG-ARY", "name": "Ariyanur school absenteeism", "kind": "SCHOOL", "channel": "PORTAL", "village": "ARY", "facility": "SCH-ARY"},
    {"code": "WTH-SIG-ARY", "name": "Rainfall feed — Ariyanur", "kind": "WEATHER", "channel": "PUBLIC_FEED", "village": "ARY"},
    # Melur — quiet cluster, with a non-reporting source
    {"code": "CHW-MLR", "name": "CHW reports — Melur", "kind": "CHW", "channel": "PORTAL", "village": "MLR"},
    {"code": "PHC-SIG-MLR", "name": "Melur PHC aggregate trends", "kind": "PHC", "channel": "API", "village": "MLR", "facility": "PHC-MLR"},
    {"code": "PHR-SIG-MLR", "name": "Melur pharmacy category trends", "kind": "PHARMACY", "channel": "EXPORT", "village": "MLR", "facility": "PHR-MLR"},
    {"code": "SCH-SIG-MLR", "name": "Melur school absenteeism", "kind": "SCHOOL", "channel": "PORTAL", "village": "MLR", "facility": "SCH-MLR"},
]

#: Historical weeks that establish each source's own baseline, then the
#: demonstration week. `weeks_ago = 0` is the current week.
#:
#: Kovilur fever-related, week 0 vs the 5/19/200/6 baselines:
#:   CHW        5  -> 14   +180%   (threshold  40%) -> anomaly
#:   PHC       19  -> 31    +63%   (threshold  30%) -> anomaly
#:   PHARMACY 200  -> 310   +55%   (threshold  30%) -> anomaly
#:   SCHOOL     6% -> 14%   +8pp   (threshold +5pp) -> anomaly
#:   LAB        0  -> 1              (floor 1)      -> corroborating
#:   WEATHER  110  -> 240  +118%                    -> supporting context only
#: => 5 corroborating sources -> PASS, HIGH.
HISTORY: dict[str, list[dict[str, Any]]] = {
    "KVL": [
        {"weeks_ago": 4, "chw": 4, "phc": 18, "pharmacy": 195, "school": 6.0, "weather": 95, "lab": 0},
        {"weeks_ago": 3, "chw": 5, "phc": 20, "pharmacy": 205, "school": 5.0, "weather": 105, "lab": 0},
        {"weeks_ago": 2, "chw": 6, "phc": 19, "pharmacy": 198, "school": 7.0, "weather": 120, "lab": 0},
        {"weeks_ago": 1, "chw": 5, "phc": 19, "pharmacy": 202, "school": 6.0, "weather": 130, "lab": 0},
        {"weeks_ago": 0, "chw": 14, "phc": 31, "pharmacy": 310, "school": 14.0, "weather": 240, "lab": 1},
    ],
    # Ariyanur: only the pharmacy moves. One source cannot carry an alert.
    "ARY": [
        {"weeks_ago": 4, "chw": 3, "phc": 12, "pharmacy": 140, "school": 5.0, "weather": 95},
        {"weeks_ago": 3, "chw": 4, "phc": 13, "pharmacy": 145, "school": 5.0, "weather": 105},
        {"weeks_ago": 2, "chw": 3, "phc": 12, "pharmacy": 138, "school": 6.0, "weather": 120},
        {"weeks_ago": 1, "chw": 4, "phc": 13, "pharmacy": 142, "school": 5.0, "weather": 130},
        {"weeks_ago": 0, "chw": 4, "phc": 14, "pharmacy": 225, "school": 6.0, "weather": 150},
    ],
    # Melur: quiet, and the school did not submit this week.
    "MLR": [
        {"weeks_ago": 4, "chw": 3, "phc": 15, "pharmacy": 160, "school": 4.0},
        {"weeks_ago": 3, "chw": 4, "phc": 16, "pharmacy": 158, "school": 5.0},
        {"weeks_ago": 2, "chw": 3, "phc": 15, "pharmacy": 165, "school": 4.0},
        {"weeks_ago": 1, "chw": 4, "phc": 16, "pharmacy": 162, "school": 5.0},
        {"weeks_ago": 0, "chw": 4, "phc": 17, "pharmacy": 168, "school": None},
    ],
}

#: Synthetic patients. Names are invented; no real person is represented.
PATIENTS: list[dict[str, Any]] = [
    {"code": "KVL-P-001", "name": "Demo Patient 001", "age_years": 34, "sex": "F", "village": "KVL"},
    {"code": "KVL-P-002", "name": "Demo Patient 002", "age_years": 27, "sex": "M", "village": "KVL"},
    {"code": "KVL-P-003", "name": "Demo Patient 003", "age_years": 9, "sex": "F", "village": "KVL"},
    {"code": "KVL-P-004", "name": "Demo Patient 004", "age_years": 51, "sex": "M", "village": "KVL"},
    {"code": "KVL-P-005", "name": "Demo Patient 005", "age_years": 41, "sex": "F", "village": "KVL"},
    {"code": "KVL-P-006", "name": "Demo Patient 006", "age_years": 16, "sex": "M", "village": "KVL"},
    {"code": "KVL-P-007", "name": "Demo Patient 007", "age_years": 62, "sex": "F", "village": "KVL"},
    {"code": "KVL-P-008", "name": "Demo Patient 008", "age_years": 23, "sex": "M", "village": "KVL"},
    {"code": "ARY-P-001", "name": "Demo Patient 101", "age_years": 38, "sex": "F", "village": "ARY"},
    {"code": "ARY-P-002", "name": "Demo Patient 102", "age_years": 45, "sex": "M", "village": "ARY"},
    {"code": "MLR-P-001", "name": "Demo Patient 201", "age_years": 30, "sex": "F", "village": "MLR"},
]

#: Encounters seeded for the current week so the aggregated individual signal
#: has something to agree with. Kovilur gets seven fever-related encounters
#: against a much lower baseline, which is what makes the Cross-Level verdict
#: CONSISTENT in the demonstration.
SEED_ENCOUNTERS: list[dict[str, Any]] = [
    {"patient": "KVL-P-001", "symptoms": ["fever", "headache"], "duration_days": 3, "temperature_c": 38.4, "days_ago": 0},
    {"patient": "KVL-P-002", "symptoms": ["fever", "body_pain"], "duration_days": 2, "temperature_c": 38.1, "days_ago": 0},
    {"patient": "KVL-P-003", "symptoms": ["fever", "headache", "body_pain"], "duration_days": 4, "temperature_c": 38.8, "days_ago": 1},
    {"patient": "KVL-P-004", "symptoms": ["fever", "chills"], "duration_days": 2, "temperature_c": 38.2, "days_ago": 1},
    {"patient": "KVL-P-005", "symptoms": ["fever", "fatigue"], "duration_days": 3, "temperature_c": 37.9, "days_ago": 2},
    {"patient": "KVL-P-006", "symptoms": ["fever", "headache"], "duration_days": 2, "temperature_c": 38.3, "days_ago": 2},
    {"patient": "KVL-P-007", "symptoms": ["fever", "body_pain"], "duration_days": 5, "temperature_c": 38.6, "days_ago": 3},
    {"patient": "KVL-P-008", "symptoms": ["diarrhoea", "vomiting"], "duration_days": 2, "days_ago": 1},
    {"patient": "ARY-P-001", "symptoms": ["cough", "sore_throat"], "duration_days": 3, "days_ago": 1},
    {"patient": "MLR-P-001", "symptoms": ["headache"], "duration_days": 1, "days_ago": 2},
]

#: Prior-week aggregated RuralCare baseline per village and category, so the
#: Cross-Level agent has a baseline to compare this week's count against.
PRIOR_WEEK_ENCOUNTER_COUNTS: dict[str, dict[str, int]] = {
    "KVL": {"FEVER": 2, "DIARRHOEAL": 1, "RESPIRATORY": 1},
    "ARY": {"FEVER": 1, "RESPIRATORY": 1},
    "MLR": {"OTHER": 1},
}

#: Village A / B / C map onto the three existing villages, so all previously
#: seeded data, alerts and history stay valid. The mapping itself lives in
#: core.constants so the API and the seed cannot drift apart.
from core.constants import DEMO_VILLAGE_LABELS as VILLAGE_LABELS  # noqa: E402,F401

DEMO_USERS: list[dict[str, Any]] = [
    # --- Village A — Kovilur -------------------------------------------
    {
        "username": "worker.a",
        "password": "demo1234",
        "role": "CHW_PHC_WORKER",
        "full_name": "A. Meena (CHW, Kovilur)",
        "village": "KVL",
        "facility": "PHC-KVL",
    },
    {
        "username": "officer.a",
        "password": "demo1234",
        "role": "HEALTH_OFFICER",
        "full_name": "Dr. K. Prasad (Health Officer, Kovilur)",
        "village": "KVL",
        "district": "Thiruvannamalai",
    },
    # --- Village B — Ariyanur ------------------------------------------
    {
        "username": "worker.b",
        "password": "demo1234",
        "role": "CHW_PHC_WORKER",
        "full_name": "R. Suresh (PHC, Ariyanur)",
        "village": "ARY",
        "facility": "PHC-ARY",
    },
    {
        "username": "officer.b",
        "password": "demo1234",
        "role": "HEALTH_OFFICER",
        "full_name": "Dr. S. Lakshmi (Health Officer, Ariyanur)",
        "village": "ARY",
        "district": "Thiruvannamalai",
    },
    # --- Village C — Melur ---------------------------------------------
    {
        "username": "worker.c",
        "password": "demo1234",
        "role": "CHW_PHC_WORKER",
        "full_name": "P. Anitha (CHW, Melur)",
        "village": "MLR",
        "facility": "PHC-MLR",
    },
    {
        "username": "officer.c",
        "password": "demo1234",
        "role": "HEALTH_OFFICER",
        "full_name": "Dr. M. Rajan (Health Officer, Melur)",
        "village": "MLR",
        "district": "Thiruvannamalai",
    },
    # --- Preserved original accounts ------------------------------------
    # `worker` and `officer` are kept exactly as they were so any existing
    # bookmark, script or demo note continues to work. `officer` has no
    # village, which under the scoping rule means district-wide oversight.
    {
        "username": "worker",
        "password": "demo1234",
        "role": "CHW_PHC_WORKER",
        "full_name": "A. Meena (CHW, Kovilur)",
        "village": "KVL",
        "facility": "PHC-KVL",
    },
    {
        "username": "officer",
        "password": "demo1234",
        "role": "HEALTH_OFFICER",
        "full_name": "Dr. K. Prasad (District Health Officer)",
        "district": "Thiruvannamalai",
    },
    {
        "username": "patient",
        "password": "demo1234",
        "role": "PATIENT",
        "full_name": "Demo Patient 001",
        "village": "KVL",
        # Linked to a synthetic patient record so the portal has something to
        # show. The patient sees only this record — never another patient,
        # never community alerts, never agent reasoning.
        "linked_patient": "KVL-P-001",
    },
    {
        "username": "admin",
        "password": "demo1234",
        "role": "ADMIN",
        "full_name": "Platform Administrator",
        "is_staff": True,
        "is_superuser": True,
    },
]

#: Accounts surfaced on the login screen: three villages × (worker + officer),
#: plus the preserved patient and administrator logins.
PRIMARY_DEMO_USERNAMES = (
    "worker.a",
    "officer.a",
    "worker.b",
    "officer.b",
    "worker.c",
    "officer.c",
    "patient",
    "admin",
)

#: Additional community reports seeded per village so each officer dashboard
#: has something distinct to review. Deliberately different in shape: Village A
#: is the corroborated fever cluster, Village B is a described skin concern
#: that no other source corroborates, Village C is quiet with an injury note.
VILLAGE_REPORT_ENTRIES: dict[str, list[dict[str, Any]]] = {
    "KVL": [
        {"category": "FEVER", "case_count": 14},
        {"category": "RESPIRATORY", "case_count": 5},
        {"category": "DIARRHOEAL", "case_count": 3},
        {"category": "MOSQUITO_BORNE", "case_count": 4,
         "description": "Households reporting daytime mosquito nuisance after rainfall."},
        {"category": "DEHYDRATION", "case_count": 2},
    ],
    "ARY": [
        {"category": "SKIN", "case_count": 6,
         "description": "Unusual itchy skin lesions reported across three households "
                        "near the tank. Not seen at this level before."},
        {"category": "EYE", "case_count": 3,
         "description": "Red, watering eyes among school-age children."},
        {"category": "FEVER", "case_count": 4},
        {"category": "WATER_BORNE", "case_count": 2,
         "description": "Two households drawing from the same open well."},
    ],
    "MLR": [
        {"category": "INJURY", "case_count": 3,
         "description": "Farm-equipment injuries during harvest week."},
        {"category": "ANIMAL_BITE", "case_count": 2,
         "description": "Two stray-dog bites reported; both referred for evaluation."},
        {"category": "MATERNAL", "case_count": 1,
         "description": "One antenatal follow-up overdue."},
        {"category": "OTHER", "case_count": 2,
         "description": "Two households reporting persistent joint pain in older "
                        "adults. Unclear cause; recording for visibility."},
    ],
}


#: Six weeks of community reporting history per village.
#:
#: Six rather than three: the officer's Community Data view compares a period
#: against the one before it, so a 21-day window needs three further weeks
#: behind it to have anything to compare against. Weeks 5 and 4 are the
#: quiet baseline; weeks 2-0 are the visible 1-3 week story.
#:
#: Each village tells a different story on purpose — identical trends would
#: make the per-village dashboards impossible to tell apart:
#:
#:   Village A (Kovilur)  fever climbs steadily across the weeks
#:   Village B (Ariyanur) respiratory holds steady with one temporary spike;
#:                        a skin/eye concern emerges late
#:   Village C (Melur)    gastrointestinal rises then settles back toward normal
#:
#: `weeks_ago = 0` is the current week.
HISTORICAL_REPORTS: dict[str, list[dict[str, Any]]] = {
    "KVL": [
        {"weeks_ago": 5, "entries": {"FEVER": 4, "RESPIRATORY": 5, "DIARRHOEAL": 3, "SKIN": 1}},
        {"weeks_ago": 4, "entries": {"FEVER": 5, "RESPIRATORY": 4, "DIARRHOEAL": 2, "INJURY": 1}},
        {"weeks_ago": 3, "entries": {"FEVER": 6, "RESPIRATORY": 5, "DIARRHOEAL": 3, "CHILD_HEALTH": 2}},
        {
            "weeks_ago": 2,
            "entries": {"FEVER": 9, "RESPIRATORY": 5, "DIARRHOEAL": 3, "DEHYDRATION": 2},
            "unusual": True,
            "notes": "More households reporting fever than usual this week.",
            "descriptions": {
                "FEVER": "Fever reports rising across the eastern hamlet."
            },
        },
        {
            "weeks_ago": 1,
            "entries": {
                "FEVER": 12,
                "RESPIRATORY": 5,
                "DIARRHOEAL": 4,
                "MOSQUITO_BORNE": 3,
                "DEHYDRATION": 2,
            },
            "unusual": True,
            "notes": "Fever reports continuing to climb after the rainfall.",
            "descriptions": {
                "MOSQUITO_BORNE": "Daytime mosquito nuisance reported by several households."
            },
        },
    ],
    "ARY": [
        {"weeks_ago": 5, "entries": {"RESPIRATORY": 7, "FEVER": 3, "DIARRHOEAL": 2}},
        {
            "weeks_ago": 4,
            "entries": {"RESPIRATORY": 12, "FEVER": 4, "DIARRHOEAL": 2},
            "unusual": True,
            "notes": "Temporary rise in cough and sore throat after the dust storm.",
            "descriptions": {
                "RESPIRATORY": "Cluster of cough complaints following three dusty days."
            },
        },
        {"weeks_ago": 3, "entries": {"RESPIRATORY": 8, "FEVER": 3, "DIARRHOEAL": 3}},
        {"weeks_ago": 2, "entries": {"RESPIRATORY": 7, "FEVER": 4, "SKIN": 2}},
        {
            "weeks_ago": 1,
            "entries": {"RESPIRATORY": 7, "FEVER": 4, "SKIN": 4, "EYE": 2},
            "descriptions": {
                "SKIN": "Itchy lesions appearing in households near the tank."
            },
        },
    ],
    "MLR": [
        {"weeks_ago": 5, "entries": {"DIARRHOEAL": 3, "FEVER": 2, "INJURY": 2}},
        {
            "weeks_ago": 4,
            "entries": {"DIARRHOEAL": 8, "FEVER": 3, "WATER_BORNE": 3, "INJURY": 1},
            "unusual": True,
            "notes": "Several households reporting loose motions; shared well suspected.",
            "descriptions": {
                "WATER_BORNE": "Affected households all draw from the same open well."
            },
        },
        {
            "weeks_ago": 3,
            "entries": {"DIARRHOEAL": 11, "FEVER": 4, "WATER_BORNE": 4, "DEHYDRATION": 3},
            "unusual": True,
            "notes": "Diarrhoeal reports still rising. Well cleaning requested.",
        },
        {
            "weeks_ago": 2,
            "entries": {"DIARRHOEAL": 6, "FEVER": 3, "DEHYDRATION": 1, "INJURY": 2},
            "notes": "Fewer reports after the well was cleaned.",
        },
        {"weeks_ago": 1, "entries": {"DIARRHOEAL": 4, "FEVER": 2, "INJURY": 3}},
    ],
}

#: Historical alerts, so Alert History is not an empty page.
#:
#: `weeks_ago` places the alert in the past; `outcome` drives the Feedback row
#: and closes the alert. `status` applies only when there is no outcome yet.
#: Counts per village are kept small and uneven on purpose — a realistic
#: demonstration environment, not a stress test.
HISTORICAL_ALERTS: dict[str, list[dict[str, Any]]] = {
    "KVL": [
        {
            "weeks_ago": 4,
            "category": "RESPIRATORY",
            "severity": "MODERATE",
            "sources": 2,
            "confidence": 0.5,
            "outcome": "FALSE_ALERT",
            "notes": "Seasonal dust; no underlying pattern found on visit.",
        },
        {
            "weeks_ago": 2,
            "category": "FEVER",
            "severity": "MODERATE",
            "sources": 3,
            "confidence": 0.65,
            "outcome": "VALID_SIGNAL",
            "notes": "Field visit confirmed the rise was real and worth watching.",
        },
        {
            "weeks_ago": 1,
            "category": "FEVER",
            "severity": "HIGH",
            "sources": 4,
            "confidence": 0.8,
            "status": "UNDER_INVESTIGATION",
            "notes": "Team visiting the eastern hamlet this week.",
        },
    ],
    "ARY": [
        {
            "weeks_ago": 4,
            "category": "RESPIRATORY",
            "severity": "MODERATE",
            "sources": 2,
            "confidence": 0.55,
            "outcome": "RESOLVED",
            "notes": "Linked to the dust storm; settled without intervention.",
        },
        {
            "weeks_ago": 1,
            "category": "SKIN",
            "severity": "LOW",
            "sources": 1,
            "confidence": 0.3,
            "safety_verdict": "DOWNGRADE",
            "safety_status": "MONITOR_ONLY",
            "status": "DETECTED",
            "notes": "Single-source signal. Monitoring only.",
        },
    ],
    "MLR": [
        {
            "weeks_ago": 4,
            "category": "DIARRHOEAL",
            "severity": "MODERATE",
            "sources": 2,
            "confidence": 0.6,
            "outcome": "VALID_SIGNAL",
            "notes": "Shared water source identified as the likely common factor.",
        },
        {
            "weeks_ago": 3,
            "category": "WATER_BORNE",
            "severity": "HIGH",
            "sources": 3,
            "confidence": 0.75,
            "outcome": "VALID_SIGNAL",
            "notes": "Well cleaning arranged with the panchayat.",
        },
        {
            "weeks_ago": 2,
            "category": "DIARRHOEAL",
            "severity": "LOW",
            "sources": 1,
            "confidence": 0.25,
            "safety_verdict": "DOWNGRADE",
            "safety_status": "MONITOR_ONLY",
            "outcome": "RESOLVED",
            "notes": "Reports fell after the well was cleaned.",
        },
    ],
}


def week_start_for(reference: dt.date, weeks_ago: int) -> dt.date:
    monday = reference - dt.timedelta(days=reference.weekday())
    return monday - dt.timedelta(weeks=weeks_ago)


def week_label_for(date: dt.date) -> str:
    iso = date.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"
