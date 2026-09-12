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

Two demonstration villages only (Village A / Kovilur, Village B / Ariyanur).
A third village (Melur, "Village C") was part of an earlier iteration of this
demo and has been deliberately removed — see git history for the record of
what it looked like. Nothing here prevents the platform itself from serving
more villages; this module just no longer seeds one.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

CLUSTER_A = "Village Cluster A"

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
]

FACILITIES: list[dict[str, Any]] = [
    {"code": "PHC-KVL", "name": "Kovilur PHC", "kind": "PHC", "village": "KVL"},
    {"code": "PHR-KVL", "name": "Kovilur Medical Store", "kind": "PHARMACY", "village": "KVL"},
    {"code": "SCH-KVL", "name": "Kovilur Panchayat School", "kind": "SCHOOL", "village": "KVL"},
    {"code": "LAB-KVL", "name": "Block Laboratory (Kovilur catchment)", "kind": "LAB", "village": "KVL"},
    {"code": "PHC-ARY", "name": "Ariyanur PHC", "kind": "PHC", "village": "ARY"},
    {"code": "PHR-ARY", "name": "Ariyanur Medical Store", "kind": "PHARMACY", "village": "ARY"},
    {"code": "SCH-ARY", "name": "Ariyanur Middle School", "kind": "SCHOOL", "village": "ARY"},
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
]

#: Historical weeks that establish each source's own baseline, then the
#: demonstration week. `weeks_ago = 0` is the current week — with `today`
#: pinned to the 2026-09-13 demonstration date, weeks_ago 0..6 map exactly
#: onto 2026-W37 (Sep 7-13) back to 2026-W31 (Jul 27-Aug 2).
#:
#: Kovilur fever-related, week 0 vs the 5/19/200/6 baselines:
#:   CHW        5  -> 14   +180%   (threshold  40%) -> anomaly
#:   PHC       19  -> 31    +63%   (threshold  30%) -> anomaly
#:   PHARMACY 200  -> 310   +55%   (threshold  30%) -> anomaly
#:   SCHOOL     6% -> 14%   +8pp   (threshold +5pp) -> anomaly
#:   LAB        0  -> 1              (floor 1)      -> corroborating
#:   WEATHER  110  -> 240  +118%                    -> supporting context only
#: => 5 corroborating sources -> PASS, HIGH. Weeks 4-1 and 0 are unchanged
#: from the original scenario; weeks 6-5 only extend the baseline further
#: back and do not affect week 0's rolling baseline (which only ever looks at
#: the four weeks immediately before it).
#:
#: Kovilur week weeks_ago=2 (2026-W35) is also a deliberately planted
#: evidence-relationship scenario, run through the real six-stage pipeline by
#: `_seed_evidence_relationship_scenarios` in seed_demo.py. Verified against
#: the running system (not hand-calculated, since CHW's own rolling baseline
#: for FEVER is recomputed from HISTORICAL_REPORTS below, not from this
#: table's "chw" field): CHW and PHC both rise against their own baseline
#: (agreement), while PHARMACY and SCHOOL stay within their expected range
#: (disagreement against that pair) — a genuinely mixed agree/disagree
#: alert. The flagship week 0 alert above gives a full multi-source
#: AGREEMENT demonstration (CHW, PHC, PHARMACY and SCHOOL all rise
#: together); the ARY scenario below adds a pure single-source DISAGREEMENT
#: case in the other village.
HISTORY: dict[str, list[dict[str, Any]]] = {
    "KVL": [
        {"weeks_ago": 6, "chw": 3, "phc": 16, "pharmacy": 175, "school": 5.0, "weather": 80, "lab": 0},
        {"weeks_ago": 5, "chw": 4, "phc": 17, "pharmacy": 182, "school": 5.0, "weather": 85, "lab": 0},
        {"weeks_ago": 4, "chw": 4, "phc": 18, "pharmacy": 195, "school": 6.0, "weather": 95, "lab": 0},
        {"weeks_ago": 3, "chw": 5, "phc": 20, "pharmacy": 205, "school": 5.0, "weather": 105, "lab": 0},
        {"weeks_ago": 2, "chw": 9, "phc": 26, "pharmacy": 198, "school": 6.0, "weather": 120, "lab": 0},
        {"weeks_ago": 1, "chw": 5, "phc": 19, "pharmacy": 202, "school": 6.0, "weather": 130, "lab": 0},
        {"weeks_ago": 0, "chw": 14, "phc": 31, "pharmacy": 310, "school": 14.0, "weather": 240, "lab": 1},
    ],
    # Ariyanur: only the pharmacy moves at week 0. One source cannot carry an
    # alert. Week weeks_ago=2 (2026-W35) plants the opposite demonstration:
    # PHC alone rises while CHW, PHARMACY and SCHOOL stay flat — a clean
    # single-source-disagrees-with-everything scenario for Evidence
    # Relationships. School did not submit at weeks_ago=6 — a `None` value
    # here is recorded as `is_reported=False`, never as zero, and (being the
    # very first historical week) cannot affect any later week's rolling
    # baseline. This is what keeps the "missing data is shown as missing,
    # never as zero" rule visibly demonstrated now that the old three-village
    # scenario's single-purpose "quiet, non-reporting village" no longer
    # exists.
    "ARY": [
        {"weeks_ago": 6, "chw": 3, "phc": 11, "pharmacy": 130, "school": None, "weather": 85},
        {"weeks_ago": 5, "chw": 3, "phc": 11, "pharmacy": 133, "school": 5.0, "weather": 90},
        {"weeks_ago": 4, "chw": 3, "phc": 12, "pharmacy": 140, "school": 5.0, "weather": 95},
        {"weeks_ago": 3, "chw": 4, "phc": 13, "pharmacy": 145, "school": 5.0, "weather": 105},
        {"weeks_ago": 2, "chw": 3, "phc": 18, "pharmacy": 138, "school": 6.0, "weather": 120},
        {"weeks_ago": 1, "chw": 4, "phc": 13, "pharmacy": 142, "school": 5.0, "weather": 130},
        {"weeks_ago": 0, "chw": 4, "phc": 14, "pharmacy": 225, "school": 6.0, "weather": 150},
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
    # Registered patients under follow-up who have no encounter recorded in
    # this demonstration window. Added so Village B has several patients to
    # choose between in the follow-up list, and so the "no previous
    # assessment yet" case is visible rather than hypothetical. They contribute
    # no encounters, so every aggregate, baseline and alert is unchanged.
    {"code": "ARY-P-003", "name": "Demo Patient 103", "age_years": 52, "sex": "F", "village": "ARY"},
    {"code": "ARY-P-004", "name": "Demo Patient 104", "age_years": 19, "sex": "M", "village": "ARY"},
]

#: Follow-ups, so the worker dashboard's Pending Follow-ups card has a real
#: mixture to prioritise: overdue, due today, and upcoming at different
#: distances, plus completed history on some patients.
#:
#: `days` is an offset from the day the seed is run, so the demonstration shows
#: the same shape whenever it is run. Negative is in the past.
SEED_FOLLOWUPS: list[dict[str, Any]] = [
    # --- Village A — Kovilur -------------------------------------------
    {"patient": "KVL-P-003", "days": -3, "status": "PENDING",
     "notes": "Child with fever for four days. Recheck temperature and hydration."},
    {"patient": "KVL-P-001", "days": 0, "status": "PENDING",
     "notes": "Recheck fever and ask about mosquito exposure at home."},
    {"patient": "KVL-P-004", "days": 2, "status": "PENDING",
     "notes": "Review after fever settles; confirm fluids are being taken."},
    {"patient": "KVL-P-007", "days": 5, "status": "PENDING",
     "notes": "Older adult, fever for five days. Home visit planned."},
    {"patient": "KVL-P-008", "days": -8, "status": "COMPLETED",
     "notes": "Diarrhoea settled. Oral fluids advised; no further concern."},
    # --- Village B — Ariyanur ------------------------------------------
    {"patient": "ARY-P-002", "days": -1, "status": "PENDING",
     "notes": "Cough persisting beyond a week. Review and consider PHC referral."},
    {"patient": "ARY-P-001", "days": 1, "status": "PENDING",
     "notes": "Recheck after fever; ask about skin complaints in the household."},
    {"patient": "ARY-P-003", "days": 4, "status": "PENDING",
     "notes": "Registered for review of itchy skin lesions reported near the tank."},
    {"patient": "ARY-P-004", "days": 8, "status": "PENDING",
     "notes": "Routine review scheduled after home visit."},
    {"patient": "ARY-P-001", "days": -6, "status": "COMPLETED",
     "notes": "Reviewed at home. Recovered; no referral needed."},
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
]

#: Prior-week aggregated RuralCare baseline per village and category, so the
#: Cross-Level agent has a baseline to compare this week's count against.
PRIOR_WEEK_ENCOUNTER_COUNTS: dict[str, dict[str, int]] = {
    "KVL": {"FEVER": 2, "DIARRHOEAL": 1, "RESPIRATORY": 1},
    "ARY": {"FEVER": 1, "RESPIRATORY": 1},
}

#: Two earlier quiet weeks of encounters, so the worker dashboard's week filter
#: has more than one week to filter. `weeks_ago` counts back from the current
#: Monday and `day_offset` places the encounter inside that week, which keeps
#: every row in a definite week whatever day the demo is run.
#:
#: The per-village category counts here match PRIOR_WEEK_ENCOUNTER_COUNTS
#: exactly, and deliberately so: the aggregated RuralCare baseline is a rolling
#: average of the preceding weeks, so equal weeks leave every baseline — and
#: therefore the demonstration outcome — exactly as it was.
SEED_HISTORY_ENCOUNTERS: list[dict[str, Any]] = [
    # --- Kovilur: 2 fever-related, 1 respiratory, 1 diarrhoeal each week ---
    {"patient": "KVL-P-001", "symptoms": ["fever", "body_pain"], "duration_days": 2, "temperature_c": 38.0, "weeks_ago": 2, "day_offset": 1},
    {"patient": "KVL-P-003", "symptoms": ["fever", "headache"], "duration_days": 3, "temperature_c": 38.2, "weeks_ago": 2, "day_offset": 3},
    {"patient": "KVL-P-005", "symptoms": ["cough", "sore_throat"], "duration_days": 3, "weeks_ago": 2, "day_offset": 2},
    {"patient": "KVL-P-008", "symptoms": ["diarrhoea"], "duration_days": 1, "weeks_ago": 2, "day_offset": 4},
    {"patient": "KVL-P-002", "symptoms": ["fever", "chills"], "duration_days": 2, "temperature_c": 38.1, "weeks_ago": 1, "day_offset": 1},
    {"patient": "KVL-P-006", "symptoms": ["fever", "fatigue"], "duration_days": 2, "temperature_c": 37.9, "weeks_ago": 1, "day_offset": 3},
    {"patient": "KVL-P-007", "symptoms": ["cough"], "duration_days": 4, "weeks_ago": 1, "day_offset": 2},
    {"patient": "KVL-P-004", "symptoms": ["diarrhoea", "abdominal_pain"], "duration_days": 2, "weeks_ago": 1, "day_offset": 5},
    # --- Ariyanur: 1 fever-related, 1 respiratory each week ----------------
    {"patient": "ARY-P-001", "symptoms": ["fever"], "duration_days": 2, "temperature_c": 38.0, "weeks_ago": 2, "day_offset": 2},
    {"patient": "ARY-P-002", "symptoms": ["cough", "sore_throat"], "duration_days": 3, "weeks_ago": 2, "day_offset": 4},
    {"patient": "ARY-P-002", "symptoms": ["fever", "body_pain"], "duration_days": 2, "temperature_c": 38.3, "weeks_ago": 1, "day_offset": 2},
    {"patient": "ARY-P-001", "symptoms": ["cough"], "duration_days": 2, "weeks_ago": 1, "day_offset": 4},
]

#: Village A / B map onto the two existing villages, so all previously
#: seeded data, alerts and history stay valid. The mapping itself lives in
#: core.constants so the API and the seed cannot drift apart.
from core.constants import DEMO_VILLAGE_LABELS as VILLAGE_LABELS  # noqa: E402,F401

#: Professional profile details seeded for the demonstration staff.
#:
#: Synthetic, like everything else here: invented names, invented staff
#: numbers, invented contact numbers in the reserved 99999 range. Photographs
#: are deliberately not seeded — a fabricated photograph of a person is not
#: something a demonstration should carry, and the portal shows a neutral
#: initials avatar until someone uploads their own.
DEMO_USERS: list[dict[str, Any]] = [
    # --- Village A — Kovilur -------------------------------------------
    {
        "username": "worker.a",
        "password": "demo1234",
        "role": "CHW_PHC_WORKER",
        "full_name": "A. Meena (CHW, Kovilur)",
        "village": "KVL",
        "facility": "PHC-KVL",
        "email": "meena.chw@example.invalid",
        "phone_number": "+91 99999 10001",
        "staff_id": "CHW-KVL-014",
        "qualification": "ANM, Community Health Worker certification",
        "experience_years": 7,
    },
    {
        "username": "officer.a",
        "password": "demo1234",
        "role": "HEALTH_OFFICER",
        "full_name": "Dr. K. Prasad (Health Officer, Kovilur)",
        "village": "KVL",
        "district": "Thiruvannamalai",
        "email": "prasad.pho@example.invalid",
        "phone_number": "+91 99999 20001",
        "staff_id": "HO-KVL-002",
        "qualification": "MBBS, MD (Community Medicine)",
        "experience_years": 12,
    },
    # --- Village B — Ariyanur ------------------------------------------
    {
        "username": "worker.b",
        "password": "demo1234",
        "role": "CHW_PHC_WORKER",
        "full_name": "R. Suresh (PHC, Ariyanur)",
        "village": "ARY",
        "facility": "PHC-ARY",
        "email": "suresh.phc@example.invalid",
        "phone_number": "+91 99999 10002",
        "staff_id": "PHC-ARY-021",
        "qualification": "B.Sc Nursing, PHC staff nurse",
        "experience_years": 5,
    },
    {
        "username": "officer.b",
        "password": "demo1234",
        "role": "HEALTH_OFFICER",
        "full_name": "Dr. S. Lakshmi (Health Officer, Ariyanur)",
        "village": "ARY",
        "district": "Thiruvannamalai",
        "email": "lakshmi.pho@example.invalid",
        "phone_number": "+91 99999 20002",
        "staff_id": "HO-ARY-003",
        "qualification": "MBBS, DPH",
        "experience_years": 9,
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
        "email": "meena.chw@example.invalid",
        "phone_number": "+91 99999 10001",
        "staff_id": "CHW-KVL-014",
        "qualification": "ANM, Community Health Worker certification",
        "experience_years": 7,
    },
    {
        "username": "officer",
        "password": "demo1234",
        "role": "HEALTH_OFFICER",
        "full_name": "Dr. K. Prasad (District Health Officer)",
        "district": "Thiruvannamalai",
        "email": "prasad.dho@example.invalid",
        "phone_number": "+91 99999 20000",
        "staff_id": "DHO-TVM-001",
        "qualification": "MBBS, MD (Community Medicine)",
        "experience_years": 12,
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

#: Accounts surfaced on the login screen: two villages × (worker + officer),
#: plus the preserved patient and administrator logins.
PRIMARY_DEMO_USERNAMES = (
    "worker.a",
    "officer.a",
    "worker.b",
    "officer.b",
    "patient",
    "admin",
)

#: Additional community reports seeded per village so each officer dashboard
#: has something distinct to review. Deliberately different in shape: Village A
#: is the corroborated fever cluster, Village B is a described skin concern
#: that no other source corroborates.
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
}


#: Seven weeks of community reporting history per village — plus
#: VILLAGE_REPORT_ENTRIES below for the current week (weeks_ago=0) — covering
#: the full 2026-W31 (Jul 27) to 2026-W37 (Sep 13) demonstration window with
#: `today` pinned to 2026-09-13. Weeks 6 and 5 are the quiet baseline; weeks
#: 4-0 are the visible story, unchanged from the original five-week scenario.
#:
#: NOTE for whoever next edits HISTORY above: its own "chw" field is not read
#: by the seed command (`SOURCE_FIELD_BY_KIND` in seed_demo.py deliberately
#: excludes CHW) and is kept here only as a human-readable record of what
#: each village's CHW story looks like. Every real CHW/FEVER CommunitySignal
#: comes from HISTORICAL_REPORTS/VILLAGE_REPORT_ENTRIES below, through
#: `_seed_historical_reports` / `_seed_chw_reports` — i.e. from the same
#: "reported cases" a worker actually submitted, so it can never drift from
#: what the Worker Portal itself shows.
#:
#: Each village tells a different story on purpose — identical trends would
#: make the per-village dashboards impossible to tell apart:
#:
#:   Village A (Kovilur)  fever climbs steadily across the weeks
#:   Village B (Ariyanur) respiratory holds steady with one temporary spike;
#:                        a skin/eye concern emerges late
#:
#: `weeks_ago = 0` is the current week.
HISTORICAL_REPORTS: dict[str, list[dict[str, Any]]] = {
    "KVL": [
        {"weeks_ago": 6, "entries": {"FEVER": 3, "RESPIRATORY": 4, "DIARRHOEAL": 2}},
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
        {"weeks_ago": 6, "entries": {"RESPIRATORY": 6, "FEVER": 3, "DIARRHOEAL": 2}},
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
}

#: Historical alerts, so Alert History is not an empty page.
#:
#: `weeks_ago` places the alert in the past; `outcome` drives the Feedback row
#: and closes the alert. `status` applies only when there is no outcome yet.
#: Counts per village are kept small and uneven on purpose — a realistic
#: demonstration environment, not a stress test.
#:
#: KVL's own weeks_ago=2 (2026-W35) is deliberately NOT listed here: that
#: slot is generated for real by `_seed_evidence_relationship_scenarios` in
#: seed_demo.py (running the actual six-stage pipeline, so it has genuine
#: `AlertEvidence` for the Evidence Relationships feature), which then applies
#: this same "field visit confirmed" outcome to the real alert instead of a
#: backfilled stub.
EVIDENCE_SCENARIO_OUTCOME_KVL_W2 = {
    "outcome": "VALID_SIGNAL",
    "notes": "Field visit confirmed the rise was real and worth watching.",
}

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
}


def week_start_for(reference: dt.date, weeks_ago: int) -> dt.date:
    monday = reference - dt.timedelta(days=reference.weekday())
    return monday - dt.timedelta(weeks=weeks_ago)


def week_label_for(date: dt.date) -> str:
    iso = date.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"
