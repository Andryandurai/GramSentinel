# GramSentinel

**Rural Healthcare Intelligence & Community Early-Warning Platform**

Track 04 // Health & Well-Being · Multi-Agent Healthcare & Clinical Systems · SDG 3

> RuralCare understands the individual. GramSentinel understands the community.
> Cross-Level Intelligence connects the two. Deterministic safety protects the
> workflow. Humans make the final decision.

---

## Medical and scope disclaimer

GramSentinel is a **prototype decision-support and early-warning system**. It
does not diagnose individuals, confirm disease outbreaks, prescribe treatment,
or replace qualified healthcare professionals, epidemiologists or public-health
authorities. Every high-impact output requires human review and authorisation.

**All demonstration data is synthetic.** No real patient data exists anywhere in
this system, and no access to any real government, PHC, pharmacy, school or
laboratory system is claimed or implemented.

---

## Run it

Prerequisites: Python 3.11+, Node 18+.

```bash
# 1. Backend
python -m venv .venv
.venv\Scripts\activate            # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env

cd backend
python manage.py migrate
python manage.py seed_demo --reset   # builds the deterministic demo scenario
python manage.py runserver 8000

# 2. Frontend (second terminal)
cd frontend
npm install
npm run dev                          # http://localhost:5173
```

Or with Docker:

```bash
docker compose up --build            # frontend on :8080, API on :8000
```

### Demonstration accounts

Created by `seed_demo` and available from the login screen (expand
**Demonstration accounts** to fill the form). Password for all: `demo1234`.

Three areas, each with its own worker and officer:

| Area | Village | Worker | Health Officer |
|------|---------|--------|----------------|
| **Village A** | Kovilur | `worker.a` | `officer.a` |
| **Village B** | Ariyanur | `worker.b` | `officer.b` |
| **Village C** | Melur | `worker.c` | `officer.c` |

Plus:

| Username | Role | Scope |
|----------|------|-------|
| `patient` | Patient | Own record only |
| `admin` | Administrator | All villages + Django admin at `/admin/` |
| `worker` | CHW (original account, preserved) | Kovilur |
| `officer` | Health Officer (original account, preserved) | District-wide |

**Village scoping rule:** a user with a village assigned sees only that
village; a user with no village assigned sees the whole district. That second
clause is what keeps the original `officer` account working as it always did,
and it matches how a district health officer actually operates. Administrators
are never scoped. The rule lives in one place — [users/scoping.py](backend/users/scoping.py).

There is **no public sign-up**. A role here grants access to health data, so
accounts are provisioned by an administrator. Passwords are shown openly
because every record behind them is synthetic.

### Tests

```bash
python -m pytest          # 98 tests; the safety engine gets the most attention
```

---

## What it does

Two layers that meet at a bridge, with a deterministic gate before any human
sees anything:

```
INDIVIDUAL SIGNALS                    COMMUNITY SIGNALS
(patient encounters)                  (CHW, PHC, pharmacy, school,
        |                              weather, laboratory)
        v                                      v
  RuralCare agents (5)                GramSentinel agents (8)
        |                                      |
        +-- privacy-preserving aggregation ----+
                          |
                          v
              CROSS-LEVEL INTELLIGENCE
                          |
                          v
            DETERMINISTIC SAFETY ENGINE
              PASS / DOWNGRADE / BLOCK
                          |
                          v
              HUMAN HEALTH PROFESSIONAL
                          |
                          v
          INVESTIGATION -> FEEDBACK & MONITORING
```

### The fourteen agents

**RuralCare — individual layer (5).** `PatientListenerAgent` structures the
entry → `SymptomAnalysisAgent` maps it to the internal taxonomy →
`RiskTriageAgent` produces a level and rationale → `ReferralAgent` converts that
to a workflow suggestion → `IndividualSafetyAgent` applies the fixed red-flag
rule set. **The last agent in the chain has no model inference in it** and can
raise a triage level the model set too low. It never lowers one.

**GramSentinel — community layer (8).** `CHWSignalAgent`, `PHCSignalAgent`,
`PharmacySignalAgent`, `SchoolSignalAgent`, `WeatherSignalAgent`,
`LabEvidenceAgent` each evaluate **only their own source against that source's
own baseline** — they never see each other's conclusions before forming their
own, which is what makes later corroboration meaningful.
`VillageTrendAgent` builds the per-village picture; `ClusterDetectionAgent`
assembles a candidate pattern.

**Cross-Level (1).** `CrossLevelIntelligenceAgent` asks whether aggregated
individual evidence agrees with community evidence in the same category, place
and week. It can *contradict* as well as confirm — a flat individual layer
against elevated community sources lowers confidence rather than raising it.

Agents exchange **structured evidence records, not prose**. Every invocation is
recorded in `AgentRun` with its input summary and output, and rendered in the
UI — so "genuinely multi-agent" is checkable rather than asserted.

### The privacy boundary

Individual records never enter community surveillance. What crosses is a count:

```
Patient A -> fever
Patient B -> fever      [ INDIVIDUAL LAYER — RuralCare ]
Patient C -> fever
        |
        v
  APPROPRIATE AGGREGATION / ANONYMISATION
        |
        v
"17 fever-related encounters in week 32 in village Kovilur"
        |
        v
   GramSentinel         [ COMMUNITY LAYER — no identifiers ]
```

This is enforced three ways, not just documented:

1. **Schema** — nothing in `community/models.py` has a foreign key to a patient
   or an assessment.
2. **Code** — `community/aggregation.py` emits only a fixed whitelist of fields
   (`PERMITTED_AGGREGATE_FIELDS`) and `assert_no_identifiers()` raises if a
   future change adds anything else.
3. **Tests** — `test_privacy_and_pipeline.py` asserts the boundary using the
   real code path.

### The Deterministic Safety Engine

`backend/safety/` is ordinary Python. It imports no LLM client, consults no
model output, and has **no bypass parameter** (there is a test asserting that).
It sits structurally after all AI reasoning and returns PASS / DOWNGRADE /
BLOCK with a per-rule record.

| # | Rule | Effect if failed |
|---|------|------------------|
| R1 | A single anomalous source cannot produce a high-confidence alert | Downgrade |
| R2 | A high-impact alert needs ≥2 independent corroborating sources | Downgrade |
| R3 | Contributing signals must be geographically consistent | Downgrade |
| R4 | Contributing signals must fall in the defined time window | Downgrade |
| R5 | Poor or insufficient data quality reduces confidence | Downgrade |
| R6 | The system must never automatically declare an outbreak | **Block** |
| R7 | High-impact action requires human review | Always attached |
| R8 | Missing data is flagged, never interpreted as zero | **Block** |
| R9 | Individual red-flag combinations force escalation | **Block** (forces URGENT) |

Rule 7 has no satisfied state — it is an obligation attached to every finding
that leaves the engine. Weather is deliberately excluded from corroboration:
heavy rainfall makes a pattern more plausible, but it is not evidence of one.

**The adversarial test, which must always pass:** the model says "no significant
concern", the structured evidence shows four corroborating sources in one
cluster in one week — the engine escalates for human review. The engine
overrides the model, never the other way round.

### The six-stage pipeline

| Stage | Where |
|-------|-------|
| 1 — Data Ingestion | `integrations/ingestion.py` — validate, normalise, align timestamps, map location, deduplicate, flag missing |
| 2 — Orchestration | `agents/orchestration/orchestrator.py` — routing, shared context, handoffs |
| 3 — Domain Reasoning | RuralCare, GramSentinel and Cross-Level agents |
| 4 — Safety & Verification | `safety/engine.py` |
| 5 — Human-Facing Output | Worker triage screen; officer alert + evidence view |
| 6 — Feedback & Monitoring | Officer records Valid Signal / False Alert / Resolved |

---

## The demonstration scenario

`python manage.py seed_demo` builds a fixed scenario — the same numbers every
run, because a demo that depends on random anomaly detection can fail on stage.
The anomaly arithmetic is genuine; only the inputs are fixed.

| Village | Cluster | What happens | Expected result |
|---------|---------|--------------|-----------------|
| **Kovilur** | A | CHW +180%, PHC +63%, pharmacy +55%, school +8pp, 1 lab confirmation, heavy rainfall | **PASS · HIGH** · 5 corroborating sources |
| **Ariyanur** | A | Pharmacy rises alone | **DOWNGRADE · LOW** — one source cannot carry an alert |
| **Melur** | B | Quiet; school did not submit | **No alert** — and the school shows as *missing*, not zero |

The last two rows matter as much as the first: they are the negative controls
that show the corroboration rule and the missing-data rule actually doing
something.

### Five-minute demo

**Person 1 — CHW / PHC Worker.** Sign in as `worker` → Dashboard → New
assessment → select a patient, tick *fever* + *headache*, duration 3, temp 38.4
→ **Get AI suggestion**. Triage support appears as CONCERNING with its
reasoning, plus the five agent handoffs, each expandable to show what it
received and produced. Submit → the confirmation states that only an anonymised
count crossed into community monitoring.

*Worth showing:* tick *fever* + *neck stiffness* instead. The model says
CONCERNING; the red-flag rule set forces URGENT and says so on screen.

**Person 2 — Health Officer.** Sign in as `officer` → Dashboard shows the
Kovilur alert (HIGH, safety PASS, 5 sources) and the Ariyanur one (LOW,
DOWNGRADE, 1 source) → open the alert → **Evidence view**: six source cards
side by side, the Cross-Level verdict, all eight safety rules with pass/fail and
the reason for each, and the nine recorded agent invocations → **Mark under
investigation** → record **Valid Signal**, which is explicitly defined on screen
as *a human confirmed the alert was worth raising*, not confirmation of any
disease.

---

## Technology

| Layer | Choice | Why |
|-------|--------|-----|
| Frontend | React, TypeScript, Vite | Typed contracts between two portals |
| Styling | Tailwind CSS | Two visually distinct portals, one design system |
| Routing / State / Charts | React Router, Zustand, Recharts | Small, sufficient |
| Backend | **Django + Django REST Framework** | Strong ORM, real permissions, admin |
| Auth | SimpleJWT | Stateless tokens carrying the role claim |
| Database | SQLite → PostgreSQL (future) | Zero setup, conventional upgrade path |
| Analytics | Pandas, NumPy, scikit-learn | Baseline comparison; **no model training** |
| Agents | Custom Python modules + custom orchestration | No opaque framework in the critical path |
| Safety | Plain deterministic Python | Independent, non-overridable, unit-testable |
| Real-time | Django Channels, Daphne | Optional; the dashboard works on REST alone |
| Testing | Pytest, pytest-django | 98 tests |
| Deployment | Docker, Gunicorn, WhiteNoise | Demo-ready |

**The LLM is optional and confined.** With `LLM_API_KEY` unset the platform is
fully functional — every agent, rule and portal works, and narratives fall back
to deterministic templates. When configured, the LLM only rewrites
already-decided text into plainer language. It cannot change a triage level, a
verdict or a rule, and anything it writes is still screened by Safety Rule 6.

---

## Layout

```
backend/
  config/         settings, urls, ASGI/WSGI, error envelope
  core/           villages, facilities, shared vocabulary, seed_demo command
  users/          custom User with role, JWT, role permissions
  patients/       Patient          ]
  assessments/    encounters       ] individual layer — never reaches community
  community/      sources, reports, signals, aggregation boundary
  alerts/         alerts, evidence, safety checks, investigations, feedback
  integrations/   Integration Layer — Stage 1 ingestion
  agents/         ruralcare/ (5) · gramsentinel/ (8) · cross_level/ (1)
                  orchestration/ · llm/ (optional)
  safety/         rules.py · engine.py · red_flags.py  — no LLM imports
  data/synthetic/ the fixed demonstration scenario
  tests/          98 tests
frontend/src/     components · layouts · pages · services · store · types
docker/           backend + frontend images, nginx config
```

---

## API

Auth: `POST /api/auth/login/` · `POST /api/auth/token/refresh/` · `GET /api/auth/me/`

Worker: `GET /api/worker/dashboard/` · `GET|POST /api/patients/` ·
`GET /api/patients/{id}/` · `POST /api/assessments/preview/` ·
`GET|POST /api/assessments/` · `GET /api/assessments/{id}/trace/` ·
`GET|POST /api/followups/` · `GET|POST /api/community-reports/` ·
`GET /api/local-signals/`

Officer: `GET /api/officer/dashboard/` · `GET /api/alerts/` ·
`GET /api/alerts/{id}/` · `GET /api/alerts/{id}/evidence/` ·
`PATCH /api/alerts/{id}/status/` · `POST /api/alerts/{id}/feedback/`

Roles are enforced **server-side on every request**. Hiding a control in the
frontend is a usability measure and is never relied upon — there are tests
asserting that a worker token receives 403 from officer endpoints and vice
versa.

---

## What exists, and what does not

| Component | Prototype (demonstrated) | Not implemented |
|-----------|--------------------------|-----------------|
| Worker & Officer portals | Full workflow on synthetic data | Offline capture, native mobile, multi-language |
| 14 agents | All operating, with recorded traces | Clinically reviewed triage logic |
| Safety engine | Full rule set, per-rule results, 40+ tests | Thresholds tuned against real field data |
| Integration Layer | Present; every source simulated | Live connectors to real institutions |
| Database | SQLite | PostgreSQL with backups and monitoring |
| Data | Synthetic only | Authorised real data under formal agreements |

**Nothing in the right-hand column exists today.** No real-world integration,
partnership, authorisation or clinical validation is in place, and this project
does not imply otherwise. The triage logic has not been clinically validated.

---

## Business model

B2G / B2B SaaS sold to institutions that carry public-health responsibility —
district health departments, PHC networks, NGOs, public-health surveillance
teams. **Patient data is never sold or monetised**; there is no data-based
revenue stream anywhere in the model.

Illustrative pricing: district subscription ₹10–15 L/yr · enterprise
multi-district ₹20–30 L/yr · NGO pilot ₹3–5 L/6 months · implementation
₹2–5 L one-time · analytics & support ₹2–4 L/yr.

Illustrative Year-1 (assumes 5 district + 5 NGO contracts): ₹1.2 Cr revenue,
₹70 L operating cost, ₹50 L net. Three-year outlook: 5 → 15 → 40 districts,
₹13.8 Cr cumulative revenue, ₹6.7 Cr cumulative profit, ₹90 L initial
investment.

> **All financial figures above are illustrative projections, not results.** No
> customer, contract, pilot or revenue exists. They rest on assumptions that
> have not been validated — government procurement cycles in particular are
> frequently longer than a single year.

---

## Limitations

- Synthetic data cannot reproduce the noise, gaps and reporting behaviour of
  real field data.
- No PHC, pharmacy, laboratory, school or government system is connected.
- No clinical validation has been performed on the triage logic.
- Alert quality depends on input quality — the engine downgrades on poor data,
  but it cannot manufacture evidence that does not exist.
- Detection is not guaranteed: a pattern invisible across all connected sources
  will not be detected. The system improves the chance that a pattern *visible
  across sources* is actually seen.
- Offline operation is not implemented.
- This is not a replacement for official public-health surveillance, which has
  legal standing, epidemiological expertise and mandates this platform does not
  have and does not seek.

---

## SDG 3

SDG 3 calls for strengthened capacity for **early warning, risk reduction and
management of health risks**. GramSentinel addresses that directly: early
warning through multi-source correlation, risk reduction through earlier and
better-evidenced human investigation, and management through structured
follow-up, recorded outcomes and a feedback loop that lets the system be judged
on results rather than claims. No claim is made about mortality reduction or
clinical outcomes.
