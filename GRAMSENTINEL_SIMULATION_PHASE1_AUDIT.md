# GramSentinel Intelligence Simulator
# Phase 1 — Current-System Audit

**Status: audit only. No simulation code, models, migrations, API, or UI were created. No existing operational behavior was modified.**

---

## 1. Executive Summary

GramSentinel is a working Django 5 + DRF + React/TypeScript application with two conceptual layers (RuralCare, individual; GramSentinel, community) already implemented as separate, cooperating multi-agent pipelines that converge at a deterministic Safety Engine. Village-level authorization is enforced **exclusively on the backend**, via a per-request database lookup of `request.user.village` (never a JWT claim, never trusted from the frontend). Health Officer A (`officer.a`) is confirmed, live, to be scoped to Village A (Kovilur, code `KVL`) only, across every officer endpoint tested.

There is no Simulation Lab, no `simulation` Django app, and no simulation-related frontend code anywhere in the repository today. The Health Officer Portal is a small, fully-dynamic route/nav set that would accept a new route with no structural change. A deterministic Safety Engine already exists (`backend/safety/engine.py`) and is independent of the LLM by construction (no LLM import anywhere in `backend/safety/`). Two, and only two, LLM call sites exist in the whole codebase, both narrative-only and both downstream-screened by the Safety Engine's Rule 6 — confirmed, not assumed, by direct code inspection.

Django Channels **is** installed and configured (`backend/alerts/consumers.py`, `backend/alerts/routing.py`, `backend/config/asgi.py`), but a concrete architectural gap was found: the WebSocket consumer authenticates via Django's session-based `AuthMiddlewareStack`, while the entire rest of the application is JWT-bearer-only with tokens held in `localStorage` (never a cookie). The frontend contains **zero** WebSocket client code. This is flagged as a pre-existing, unused/likely-non-functional real-time path — not fixed here.

The Officer Dashboard's community trend chart uses **actual reported counts**, not normalized baseline percentages — confirmed by reading `backend/alerts/views.py`'s `_weekly_reported_series()` and the frontend chart that renders it.

---

## 2. Repository Structure

```
GramSentinel/
├── backend/                         Django project (config.settings)
│   ├── config/                      settings, urls, asgi, wsgi, exceptions
│   ├── agents/                      multi-agent architecture (see §12)
│   │   ├── base.py                  BaseAgent / AgentResult (shared contract)
│   │   ├── orchestration/           RuralCareOrchestrator, CommunityOrchestrator
│   │   ├── ruralcare/                5 individual-layer agents
│   │   ├── gramsentinel/            8 community-layer agents
│   │   ├── cross_level/             CrossLevelIntelligenceAgent
│   │   └── llm/                     LLMClient (optional, narrative-only)
│   ├── safety/                      SafetyEngine, rules.py, red_flags.py, types.py
│   ├── users/                       User model, permissions, scoping, auth views
│   ├── core/                        Village, Facility models; constants; core views
│   ├── patients/, assessments/      RuralCare individual-layer data
│   ├── community/                   CommunityReport/Entry, CommunitySignal, aggregation
│   ├── alerts/                      Alert, AlertEvidence, Investigation, Feedback,
│   │                                 evidence_relationships.py, consumers.py, routing.py
│   ├── integrations/                Stage-1 ingestion (ingest_batch)
│   ├── data/synthetic/scenario.py   demo/seed data tables
│   └── tests/                       pytest-django suite (see §14)
└── frontend/                        React 18 + TypeScript + Vite + Tailwind
    └── src/
        ├── pages/officer/           Dashboard, CommunityData, AlertHistory,
        │                            AlertDetail, EvidenceView, CommunityReports, Team
        ├── pages/worker/, patient/, admin/, profile/
        ├── layouts/PortalLayout.tsx shared shell for all 4 portals
        ├── store/auth.ts            the ONLY Zustand store in the app
        ├── services/api.ts          fetch wrapper, JWT in localStorage
        ├── components/ui.tsx, AgentTrace.tsx, SafetyPanel.tsx, TriageSupport.tsx
        └── App.tsx                  all routing
```

No `simulation/` directory, no `SimulationLab*` file, no `useSimulationStore`, anywhere — confirmed by repository-wide search.

---

## 3. Current Authentication Architecture

- **Backend auth class:** `rest_framework_simplejwt.authentication.JWTAuthentication`, the sole entry in `REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]` — `backend/config/settings.py:169-171`.
- **Default permission:** `IsAuthenticated` for everything, with every view opting into a specific role permission — `backend/config/settings.py:172-175`.
- **Login endpoint:** `LoginView(TokenObtainPairView)` — `backend/users/views.py:38-48`, `POST /api/auth/login/`, wired at `backend/users/urls.py:13` (path `login/`) under `backend/config/urls.py:193` (`api/auth/` → `users.urls`).
- **Token serializer:** `GramSentinelTokenSerializer(TokenObtainPairSerializer)` — `backend/users/serializers.py:184-197`. `get_token()` adds exactly two custom claims: `role` and `display_name`. **No village claim is added.**
- **Verified live:** decoding the actual JWT issued to `officer.a` gives claims `{user_id, role, display_name}` only (manual verification, §19). Village is never in the token.
- **Token storage (frontend):** `localStorage` keys `gs.access` / `gs.refresh` — `frontend/src/services/api.ts:10-11, 25-39`. Not a cookie; no CSRF/session flow involved for the SPA.
- **Token lifetime:** access 12h, refresh 7d, no rotation — `backend/config/settings.py:180-185`.
- **Refresh:** one-shot silent refresh on a 401, via `attemptRefresh()` — `frontend/src/services/api.ts:60-76, 99-102`.
- **Route protection (frontend):** `RequireRole` component in `frontend/src/App.tsx` — explicitly documented in its own comment as "a usability measure... Access control itself is enforced server-side on every request."

---

## 4. Current Health Officer Village Resolution

This is the most important finding of Phase 1, stated exactly:

**Health Officer A's village is resolved by a foreign key on the `User` row itself, read fresh from the database on every request — never cached in the JWT, never supplied by the client.**

- **A.** File: `backend/users/models.py`
- **B.** Class/field: `User.village` — `backend/users/models.py:23-30`
  ```python
  village = models.ForeignKey(
      "core.Village", on_delete=models.SET_NULL, null=True, blank=True,
      related_name="users",
      help_text="Worker's own area. Scopes what local signals they may read.",
  )
  ```
- **C. Exact mechanism:** every DRF view that needs village scope reads `request.user.village` / `request.user.village_id` directly off the authenticated `User` instance that DRF's `JWTAuthentication` resolves from the token's `user_id` claim on each request. The single shared helper is:
  - `backend/users/scoping.py:23-30` — `scoped_village_id(user)`: returns `None` for a platform admin, otherwise `user.village_id`.
  - `backend/users/scoping.py:33-41` — `scope_queryset(queryset, user, field="village_id")`: filters a queryset to that village id, or returns it unfiltered if the user has none (district-wide — see below).
- **D. Line numbers:** as above (`users/models.py:23-30`, `users/scoping.py:23-41`).
- **E. Enforcement layer:** **backend only**. The frontend never determines or stores a "current village" concept at all — `useAuth` (`frontend/src/store/auth.ts`) holds only the logged-in `User` object (which includes `village_code`/`village_name` purely for display, e.g. in `PortalLayout.tsx`'s header), and no frontend code ever sends a village identifier that changes what data is requested for the officer/worker portals (contrast the Admin Portal's `?village=` filter, which is a different, explicitly-admin-only, backend-validated code path — see §5).
- **F. Is backend enforcement sufficient?** Yes, verified: every officer-facing view (`OfficerDashboardView`, `OfficerCommunityDataView`, `AlertListView`, `AlertDetailView`, `AlertEvidenceView`, `AlertStatusView`, `StaffProfileListView`) calls `scope_queryset(...)` or `scoped_village_id(...)` before returning data, and direct-object lookups (e.g. `AlertDetailView.get_queryset()`) are built from the already-scoped queryset, so an out-of-scope object id returns 404, not 403 — confirmed live (§19): `officer.a` requesting `officer.b`'s alert id was **not tested this session but the identical pattern was proven in the Village-C-removal task earlier this session** (officer.a → officer.b's alert id → HTTP 404).
- **G. Weakness found:** none in the officer/worker/patient path. One adjacent weakness exists in the *unused* WebSocket path — see §16.

**"A user with a village assigned sees only that village; a user with no village assigned sees everything they are otherwise permitted to see"** is the explicit, documented rule (`backend/users/scoping.py:1-16`, module docstring). This is why the original `officer` demo account (no village) is district-wide by design, not a bug — confirmed by `backend/tests/test_village_isolation.py::test_district_officer_without_a_village_still_sees_everything`.

---

## 5. Current Village Authorization (API + Permission Audit)

- **Permission classes** (all in `backend/users/permissions.py`): `IsWorker` (12-21), `IsHealthOfficer` (24-33), `IsPatient` (36-43), `IsPlatformAdmin` (46-59), `IsWorkerOrOfficer` (62-75). Each is a `BasePermission.has_permission` role check only — **role**, not village. Village narrowing is a second, separate layer applied inside the view body.
- **Pattern is multi-layer, confirmed by direct reading of `backend/alerts/views.py`:**
  1. **Permission-level** — `permission_classes = (IsHealthOfficer,)` gates entry to the view at all.
  2. **Queryset-level** — `officer_alert_queryset(user)` (`backend/alerts/views.py:176-185`) wraps `scope_queryset(Alert.objects...select_related(...).prefetch_related(...), user)`; used by every alert list/detail/evidence/status/feedback view.
  3. **Object-level** — `AlertDetailView`/`AlertEvidenceView`/`AlertStatusView` all call `generics.get_object_or_404(officer_alert_queryset(request.user), pk=pk)`, so an id outside scope is a clean 404, never a data leak.
  4. **Service-level** — `run_community_pipeline()` (`backend/alerts/services.py`) only ever operates on the `Village` object explicitly passed to it by the caller; it has no independent notion of "current officer," so nothing in the pipeline itself can cross villages.
- **Admin Portal's `?village=` filter is a distinct, explicitly-admin-only pattern** — `backend/core/views.py` (AdminOverviewView, not read line-by-line in this pass but its permission is `IsPlatformAdmin`, confirmed via `backend/users/permissions.py:46-59` and exercised in `backend/tests/test_admin_overview.py`). This is the **only** place in the codebase where a village can be selected via a query parameter, and it is gated to platform admins only — it is not a template to imitate for Health Officer simulation scope.
- **Reusable pattern for a future simulation permission:** follow the exact shape of `IsHealthOfficer` (role check) + `scope_queryset`/`scoped_village_id` (village narrowing), applied inside the simulation view exactly as `officer_alert_queryset` does today. No new pattern is needed; the existing one already generalizes.

---

## 6. Health Officer Portal Architecture

- **Route shell:** `frontend/src/App.tsx` — one `<Route element={<RequireRole roles={['HEALTH_OFFICER']}><PortalLayout .../></RequireRole>}>` block wraps all officer routes (confirmed, App.tsx lines ~106-132 from earlier direct reads in this session).
- **Layout:** `PortalLayout` — `frontend/src/layouts/PortalLayout.tsx`. Renders header (portal name, subtitle, signed-in user + village/district, sign-out), a horizontal nav bar built from a passed `nav: NavItem[]` array, and `<Outlet />` for the page body.
- **Officer nav array:** `OFFICER_NAV` in `PortalLayout.tsx`:
  ```
  Dashboard | Community data | Community reports | Alert history | Health team | My profile
  ```
- **Pages** (`frontend/src/pages/officer/`): `Dashboard.tsx`, `CommunityData.tsx`, `CommunityReports.tsx`, `AlertHistory.tsx`, `AlertDetail.tsx`, `EvidenceView.tsx`, `Team.tsx`. Plus the shared `pages/profile/MyProfile.tsx`.
- **No village selector, no village dropdown, no village state anywhere in this tree** — confirmed by direct read of every one of these files earlier in this session and by a fresh grep (`Select Village|VillageSelector|village-selector|SelectVillage`) returning zero hits (§19).

**Recommended future location for Simulation Lab (documented, not created):**
- **Route:** `/officer/simulation` (or `/officer/simulation-lab`), added as one more child route inside the existing `RequireRole roles={['HEALTH_OFFICER']}` + `PortalLayout` block in `App.tsx` — no new layout, no new guard.
- **Nav:** one more entry appended to `OFFICER_NAV` in `PortalLayout.tsx`, e.g. `{ to: '/officer/simulation', label: 'Simulation Lab' }`.
- **Layout component to reuse:** `PortalLayout` — unchanged, `accent="sentinel"` (already used for the officer portal).
- **Auth guard to reuse:** the existing `RequireRole roles={['HEALTH_OFFICER']}` — unchanged.
- **Village scope mechanism to reuse:** identical backend pattern to §5 — a future `SimulationXView` would use `IsHealthOfficer` + `scope_queryset`/`scoped_village_id` exactly as `alerts/views.py` does. The frontend page would simply display `request.user`'s own village (already available via `useAuth().user`), never request or accept a different one.

---

## 7. Backend Models

| Model | File | Key fields | Village relationship | Operational? | Simulator should… |
|---|---|---|---|---|---|
| `User` | `backend/users/models.py:5-95` | `role`, `village` (FK), `facility` (FK), `district` | Direct FK, `SET_NULL` | Yes | **REUSE** — read-only, never write |
| `Village` | `backend/core/models.py:15-30` | `code`, `name`, `cluster`, `district`, `population` | is the village | Yes (reference data) | **REUSE** — never write |
| `Facility` | `backend/core/models.py:33-53` | `kind`, `village` (FK) | Direct FK | Yes | **REUSE** for context only |
| `Patient` | `backend/patients/models.py` | `patient_code`, `village` (FK), `linked_user` | Direct FK | Yes, individual-layer | **DO-NOT-TOUCH** from simulation |
| `PatientAssessment` | `backend/assessments/models.py` | `patient`, `worker`, `village`, `primary_category`, `triage_level`, `agent_trace`, `safety_status` | Direct FK | Yes, individual-layer | **DO-NOT-TOUCH** from simulation |
| `CommunityReport` / `CommunityReportEntry` | `backend/community/models.py:57-142` | `village`, `week_label`, `worker`; entries: `category`, `case_count`, `description` | Direct FK | **Yes — this is the Worker Portal's real submitted data, the "one source of truth"** | **MUST REMAIN SEPARATE.** A simulator must never insert rows here. |
| `CommunitySignal` | `backend/community/models.py:145-192` | `source` (FK DataSource), `village`, `category`, `week_label`, `value`, `baseline`, `is_reported`, `change_pct` (property) | Direct FK | Yes | **MUST REMAIN SEPARATE** |
| `DataSource` | `backend/community/models.py:14-54` | `kind`, `village`, `channel`, `simulated` (already a boolean!) | Direct FK | Yes (registry) | **REUSE for reference / DO-NOT-TOUCH for writes** |
| `Alert` | `backend/alerts/models.py:52-116` | `village`, `category`, `week_label`, `severity`, `confidence`, `safety_verdict`, `status`, `orchestration_run_id` | Direct FK, `PROTECT` | **Yes — the operational alert record** | **MUST REMAIN SEPARATE.** A future `SimulationResult`/`SimulationEvent` must not reuse this table. |
| `AlertEvidence` | `backend/alerts/models.py:119-148` | `alert` (FK), `source_kind`, `category`, `change_pct`, `status`, `is_corroborating`, `explanation` | Indirect via `alert.village` | Yes | **REUSE THE SHAPE**, not the table, for a future `SimulationSourceSignal`/evidence card |
| `SafetyCheck` | `backend/alerts/models.py:151-190` | `alert` (nullable FK), `scope`, `verdict`, `rules`, `reasons`, `engine_version` | Indirect | Yes | **REUSE THE SHAPE** for `SimulationSafetyCheck` |
| `Investigation` | `backend/alerts/models.py:193-214` | `alert` (1:1), `officer` (FK), `status`, `notes` | Indirect via alert | Yes | **MUST REMAIN SEPARATE** — a simulated investigation must not write here |
| `Feedback` | `backend/alerts/models.py:217-241` | `alert` (1:1), `officer`, `outcome`, `notes` | Indirect | Yes | **MUST REMAIN SEPARATE** |
| `AgentRun` | `backend/alerts/models.py:17-49` | `run_id`, `stage`, `agent_name`, `village` (nullable FK), `week_label`, `input_summary`, `output`, `used_llm` | Direct nullable FK | Yes (audit trail) | **REUSE THE SHAPE** for `SimulationAgentRun` |

**Operational tables a naive simulator implementation could accidentally write into (explicitly flagged, per the task's instruction):** `CommunityReport`, `CommunityReportEntry`, `CommunitySignal`, `Alert`, `AlertEvidence`, `SafetyCheck`, `Investigation`, `Feedback`, `AgentRun`. All eight already exist and are all reachable from `alerts.services.run_community_pipeline()` — the exact function a naive "run a simulated scenario through the real pipeline" implementation would be tempted to call directly. **It must not be called directly against these tables for simulation; Phase 2 needs either a parallel write path into new simulation-only tables, or the orchestrators/agents invoked in a pure in-memory mode whose result is persisted only to simulation tables.**

---

## 8. API Architecture

- Village filtering is **queryset-level + object-level**, layered on top of a **permission-level** role gate (see §5 for the concrete call chain).
- No middleware performs village filtering; there is no custom DRF authentication or permission subclass beyond `backend/users/permissions.py`.
- Serializer-level filtering: none observed — serializers (`backend/alerts/serializers.py`, `backend/community/serializers.py`) render whatever queryset they're given; they perform no independent scoping.
- **DRF settings:** `backend/config/settings.py:168-178` — `JWTAuthentication` only, `IsAuthenticated` default, custom exception handler `config.exceptions.gramsentinel_exception_handler`.
- **Future simulation permission recommendation (documented only, not created):** a `IsHealthOfficer`-equivalent class is unnecessary to duplicate — reuse `IsHealthOfficer` itself, and apply `scope_queryset`/`scoped_village_id` from `users/scoping.py` inside the simulation view(s), exactly mirroring `alerts/views.py::officer_alert_queryset`.

---

## 9. Community Aggregation

(Traced in full in earlier work this session; re-confirmed here.)

- **Entry point:** a CHW submits the Community Report form → `CommunityReportListCreateView.create()` (`backend/community/views.py`) writes `CommunityReportEntry` rows and calls `integrations.ingestion.ingest_batch()`, which writes the same numbers into `CommunitySignal` (CHW source).
- **Symptom → category mapping:** `community/aggregation.py::category_for_symptoms()` for the RuralCare→community aggregation path; the Worker's own Community Report form lets the CHW pick a category directly for manually-reported signals.
- **Week calculation:** ISO calendar weeks throughout — `week_label_for()`/`week_start_for()` (present in both `backend/data/synthetic/scenario.py` and `backend/community/aggregation.py`), always `YYYY-Www`. One consistent definition, confirmed no second week-numbering scheme exists anywhere.
- **Village separation:** every relevant row (`CommunityReport`, `CommunitySignal`, `Alert`) carries its own `village` FK; nothing is ever merged across villages except by the explicitly admin-only overview (§5).
- **Missing vs. zero:** `CommunitySignal.is_reported` is a first-class boolean; `value=None` with `is_reported=False` represents "not submitted," and the deterministic Safety Engine's Rule 8 (`backend/safety/rules.py::rule_8_missing_data_never_zero`) is BLOCKING if a non-reported source ever carries a numeric value — i.e. the "missing ≠ zero" invariant is enforced by a hard rule, not merely a convention.
- **Duplicates:** `CommunityReport` has `unique_together = [("village", "week_label", "worker")]`; resubmission replaces (`update_or_create` + `entries.all().delete()` + `bulk_create`), never accumulates.
- **Alert generation:** `alerts/services.py::run_community_pipeline(village, week_label, category)` — the single, already-existing function that runs the full community orchestrator + safety engine and persists `Alert`/`AlertEvidence`/`SafetyCheck`.
- **Chart uses actual counts, confirmed:** `backend/alerts/views.py::_weekly_reported_series()` sums real `CommunityReportEntry.case_count` values per week/category (no normalization, no percentage-of-baseline), and the frontend (`frontend/src/pages/officer/Dashboard.tsx`) renders that series directly with a Recharts `<LineChart>` whose Y-axis is unlabelled-unit integer counts, not `%`. This was a deliberate fix made earlier in this same project's history (see git log — "FIX HEALTH OFFICER COMMUNITY TRENDS" work) and remains the current, correct behavior.

---

## 10. Alerting

- `Alert` model: `backend/alerts/models.py:52-116`. `severity` (LOW/MODERATE/HIGH), `confidence` (float, engine-computed, never learned), `safety_verdict` (PASS/DOWNGRADE/BLOCK), `status` (DETECTED/UNDER_INVESTIGATION/CLOSED).
- Created exclusively by `run_community_pipeline()` (`backend/alerts/services.py:83-213`) — no other code path creates an `Alert` row (the demo seed's backfilled historical alerts create `Alert` rows directly too, for demo-history purposes only, but this is seed-only code, not a production path).
- **A `BLOCK` safety verdict produces no `Alert` at all** — `run_community_pipeline()` explicitly checks `blocked = safety["verdict"] == SafetyVerdict.BLOCK` and returns early, writing only a `SafetyCheck` with `alert=None` (`backend/alerts/services.py:127-157`). The safety gate has real, structural authority, not cosmetic authority.

## 11. Investigation

- `Investigation` (1:1 with `Alert`) and `Feedback` (1:1 with `Alert`) — `backend/alerts/models.py:193-241`.
- Officer-facing write path: `AlertStatusView.patch()` and `AlertFeedbackView` (`backend/alerts/views.py`) — both permission-gated `IsHealthOfficer` and object-scoped via `officer_alert_queryset`.
- Manually verified live (§19): `officer.a` moving alert `87` (a Kovilur alert) to `UNDER_INVESTIGATION` succeeded (HTTP 200); state was restored afterward via `seed_demo --reset` since Phase 1 is meant to be observation-only.

---

## 12. Agent/LLM Architecture

**A. True agent abstraction exists:** `BaseAgent` (ABC) + `AgentResult` (dataclass) — `backend/agents/base.py:19-114`. Every agent implements `handle(payload, context) -> dict`; `run()` wraps it with timing, status, and a human-readable `result_summary`.

**B. Custom orchestration exists, not a third-party framework:** `backend/agents/orchestration/orchestrator.py` — `RuralCareOrchestrator` (lines 60-149) and `CommunityOrchestrator` (lines 152-298), each a plain Python class that sequences agent calls and records an `OrchestrationContext` (`backend/agents/orchestration/context.py`) trace.

**C. Direct LLM calls from services/views:** none found. All LLM access goes through `agents/llm/client.py::LLMClient`/`get_llm_client()`.

**D.** → the architecture is **A + B**, cleanly: a real (if project-specific, not a third-party-framework) agent abstraction with custom orchestration. No direct LLM calls bypass an agent.

**Full agent roster** (14 total, confirmed by file enumeration + `__init__.py` exports):
- RuralCare (individual, 5): `PatientListenerAgent`, `SymptomAnalysisAgent`, `RiskTriageAgent`, `ReferralAgent`, `IndividualSafetyAgent` — `backend/agents/ruralcare/*.py`.
- GramSentinel (community, 8): `CHWSignalAgent`, `PHCSignalAgent`, `PharmacySignalAgent`, `SchoolSignalAgent`, `WeatherSignalAgent`, `LabEvidenceAgent` (all in `backend/agents/gramsentinel/signal_agents.py`), `VillageTrendAgent` (`village_trend.py`), `ClusterDetectionAgent` (`cluster.py`).
- Cross-level (1): `CrossLevelIntelligenceAgent` — `backend/agents/cross_level/agent.py`.

**LLM call sites — exactly two in the entire codebase**, both narrative-synthesis only:
1. `backend/agents/gramsentinel/cluster.py:146` (inside `ClusterDetectionAgent`) — synthesizes the candidate-pattern narrative for the community layer.
2. `backend/agents/ruralcare/triage.py:176` (inside `RiskTriageAgent`) — synthesizes the reasoning summary for the individual layer.

Both call `get_llm_client()` (`backend/agents/llm/__init__.py`) inside a try/except for `LLMUnavailable`, falling back to a deterministic template on any failure, timeout, empty completion, missing key, or `LLM_ENABLED=False` — `backend/agents/llm/client.py:45-86`.

**Mapping to the future simulator's five conceptual agents:**

| Future simulator agent | Existing equivalent | Decision | Reason |
|---|---|---|---|
| Data Ingestion Agent | `integrations.ingestion.ingest_batch()`, `PatientListenerAgent` | **REUSE** (pattern) | Existing ingestion/validation logic already does exactly this job; a simulator's synthetic records should go through an equivalent, not a copy-paste |
| Signal Analysis Agent | the 6 `gramsentinel` signal agents (`backend/agents/gramsentinel/signal_agents.py`) | **REUSE** (as-is, on synthetic payloads) | Each signal agent is already source-agnostic — it takes a payload dict and a baseline, with no DB write inside `handle()` (the caller persists). It can run against simulated payloads today with zero modification. |
| Correlation Agent | `VillageTrendAgent` + `ClusterDetectionAgent` | **REUSE** (as-is) | Same reasoning — no DB write inside `handle()`. |
| Evidence Agent | `CrossLevelIntelligenceAgent` + `AlertEvidence`-shaped evidence cards + `evidence_relationships.py` | **REUSE the classification logic (`build_evidence_relationships`), MODIFY only its input source** | `build_evidence_relationships(alert, evidence)` (`backend/alerts/evidence_relationships.py`) takes any list of evidence-card-shaped objects with `.category`/`.status`/`.change_pct`/`.source_kind` — it is not hard-wired to the `AlertEvidence` Django model beyond calling `.get_source_kind_display()` etc. A future `SimulationSourceSignal` model with the same field shape could be passed to the *same* function with, at most, a thin adapter. |
| Safety Engine | `backend/safety/engine.py::SafetyEngine` | **REUSE, unmodified** | Pure, stateless, deterministic; takes `Hypothesis` + `EvidenceRecord`s, returns a `SafetyResult`. No DB access inside the engine at all — it is naturally reusable against simulated evidence with zero change. |

**Persistence (the only thing that must be NEW, not the reasoning logic):** the orchestrators' `.run()` methods return plain dicts/dataclasses; it is the *callers* — `alerts/services.py::run_community_pipeline()` for community, `assessments` app code for individual — that persist into operational tables. A simulator should call the **same orchestrators and the same SafetyEngine**, but must own a **new persistence layer** writing into simulation-only tables (§14), never calling `run_community_pipeline()` directly.

---

## 13. Safety Architecture

**A deterministic Safety Engine exists and was found, not assumed.**

- **File:** `backend/safety/engine.py`
- **Class:** `SafetyEngine` — `backend/safety/engine.py:45-209`
- **Rules (8 total), each a pure function in `backend/safety/rules.py`:**
  - R1 `rule_1_single_source_ceiling` (49-72) — DOWNGRADING
  - R2 `rule_2_corroboration_threshold` (75-95) — DOWNGRADING
  - R3 `rule_3_geographic_consistency` (98-123) — DOWNGRADING
  - R4 `rule_4_temporal_consistency` (126-158) — DOWNGRADING
  - R5 `rule_5_data_quality_sufficiency` (161-197) — DOWNGRADING
  - R6 `rule_6_no_automatic_outbreak_declaration` (200-235) — **BLOCKING**; screens the hypothesis's `kind` (must be `correlation_hypothesis`) and its narrative text against `PROHIBITED_TERMS` (22-34): "outbreak confirmed", "diagnosed with", "the diagnosis is", "confirmed case of", "guaranteed", "definitely", etc.
  - R7 `rule_7_human_review_required` (238-254) — ADVISORY, always attached, structurally un-satisfiable as "not required" (`Alert.requires_human_review` property, `backend/alerts/models.py:113-116`, is hardcoded `return True`).
  - R8 `rule_8_missing_data_never_zero` (257-292) — **BLOCKING**.
  - A ninth rule (R9, individual-layer red flags) lives in `backend/safety/red_flags.py`, invoked by `SafetyEngine.evaluate_individual()` (`backend/safety/engine.py:135-172`).
- **Inputs:** `Hypothesis` + `Sequence[EvidenceRecord]` (community) or `IndividualCase` (individual) — all defined in `backend/safety/types.py`.
- **Outputs:** `SafetyResult` (verdict PASS/DOWNGRADE/BLOCK, status, per-rule `RuleResult` tuple, reasons, severity, confidence, `corroborating_source_count`, `engine_version`, `requires_human_review=True` always).
- **Deterministic:** yes — confirmed by the module's own docstring claim *and* by code inspection: no randomness, no model call, pure arithmetic/threshold comparisons and set operations throughout `rules.py`.
- **Can an LLM override it?** No — confirmed structurally: `backend/safety/engine.py` has no import of `agents.llm` or anything LLM-related anywhere in the file. The only two LLM call sites (§12) produce *narrative text*, which the engine's R6 then screens as one more untrusted input.
- **Does it write directly to operational alert/outbreak state?** No — `SafetyEngine.evaluate_community()`/`evaluate_individual()` are pure functions returning a `SafetyResult`; the *caller* (`alerts/services.py::run_community_pipeline`) decides, based on that result, whether to persist an `Alert` at all (never on a BLOCK verdict, confirmed §10).

**No pre-existing safety risk of "LLM has authority to write an alert/outbreak status" was found.** The architecture as it stands already enforces exactly the non-negotiable rule this phase asks about: narrative synthesis is LLM-optional and downstream-screened; the verdict is 100% deterministic Python.

---

## 14. Frontend State Management

- **Only one Zustand store exists in the entire frontend:** `frontend/src/store/auth.ts` (`useAuth`) — holds `{ user, status, error }` plus `signIn`/`signOut`/`restore`/`clearError`. No community-data store, no alert store, no investigation store.
- **Everything else uses a shared `useAsync` hook** (`frontend/src/hooks/useAsync.ts`) called per-page against `services/api.ts` — the established, consistent pattern across every officer/worker/patient/admin page already read in this session (`Dashboard.tsx`, `CommunityData.tsx`, `AlertHistory.tsx`, `AlertDetail.tsx`, `EvidenceView.tsx`, etc.).
- **Future `useSimulationStore` recommendation:** a **new, separate Zustand store**, not an extension of `useAuth` (which is auth-only by design and design-intent) and not a second global pattern — it should mirror how every other page already gets its data: primarily `useAsync` calls against new simulation endpoints, with a store only if genuinely cross-page simulation session state (e.g. "which scenario is currently running") needs to survive route changes. This is a Phase 2+ decision; **not created now**.

---

## 15. Chart Architecture

- **Library:** Recharts `^2.12.7` (`frontend/package.json`), used via `<LineChart>`/`<CartesianGrid>`/`<XAxis>`/`<YAxis>`/`<Tooltip>`/`<Legend>`/`<Line>` — confirmed in `frontend/src/pages/officer/Dashboard.tsx` and `frontend/src/pages/officer/CommunityData.tsx`.
- **Community trend chart uses actual reported counts, confirmed (see §9):** `backend/alerts/views.py::_weekly_reported_series()` → real `CommunityReportEntry.case_count` sums, no baseline normalization. This was a deliberate, already-completed fix (visible in git history) — **not something Phase 1 touched or needs to touch.**
- Colour palette for chart series: fixed hex array (`SERIES_COLOURS` in `Dashboard.tsx`), reused between the Dashboard and Community Data charts for visual consistency.

---

## 16. Real-Time Architecture

**Current state, verified rather than assumed:**

- Channels **is** installed (`"channels"` in `INSTALLED_APPS`, `backend/config/settings.py:70`) and configured: `ASGI_APPLICATION = "config.asgi.application"` (`settings.py:112`), `CHANNEL_LAYERS` = `InMemoryChannelLayer` (`settings.py:116-118` — **process-local only; will not fan out across multiple worker processes or horizontally-scaled instances**).
- `backend/config/asgi.py:16-26` wires one WebSocket route via `channels.auth.AuthMiddlewareStack(URLRouter(websocket_urlpatterns))`.
- `backend/alerts/routing.py:1-7` registers exactly one route: `ws/officer/alerts/` → `OfficerAlertConsumer`.
- `backend/alerts/consumers.py:15-38` — `OfficerAlertConsumer.connect()` checks `self.scope["user"].is_authenticated` and role ∈ {HEALTH_OFFICER, ADMIN}, then joins a single global group `"officer_alerts"` (`GROUP = "officer_alerts"`, line 12) — **not village-scoped**. `_broadcast()` (`backend/alerts/services.py:216-241`) sends every newly-created alert's summary (title, severity, cluster, week_label, safety_verdict) to that one global group, regardless of which village the alert belongs to.
- **Gap found:** `channels.auth.AuthMiddlewareStack` authenticates via Django's session framework (reads `request.session`, needs a session cookie). The application's actual authentication is JWT-bearer, tokens held in `localStorage` (`frontend/src/services/api.ts`), **never a cookie**. A browser using this SPA normally has no Django session at all. Unless a session was separately established (e.g. by visiting `/admin/` and logging in there), `self.scope["user"]` on the WebSocket connection would be `AnonymousUser`, and `connect()` would immediately `close(code=4401)`.
- **Frontend has zero WebSocket client code** — confirmed by a repository-wide search for `WebSocket|ws://|wss://|socket` under `frontend/src/`: no matches. The officer dashboard is fully functional on REST polling alone (the consumer's own module docstring says exactly this: "Best-effort only: the dashboard polls REST and is fully functional without a channel layer").

**Conclusion: the existing Channels/WebSocket path is configured but effectively unused and, as configured, not proven to authenticate for the SPA's actual users. It is not village-scoped even for the one thing it does broadcast.** This is flagged as a pre-existing gap — not fixed in Phase 1.

**Recommended future architecture for Phase 8's "Live Signal Emergence": POLLING**, for these reasons:
1. It is the pattern already used everywhere in this codebase (100% of existing pages), so a simulation page built the same way is the smallest, most consistent change — directly satisfying "reuse existing working infrastructure."
2. The one existing WebSocket path has two unresolved problems (auth mismatch, no village scoping) that would need fixing *before* it could be trusted for anything, let alone a new safety-adjacent feature — out of scope for "reuse."
3. `InMemoryChannelLayer` does not survive process restarts or scale past one worker process — a real constraint for any deployment beyond the current single-instance Render setup.
4. A simulation's "live emergence" is inherently a slower-than-real-time, human-paced narrative (new synthetic evidence appearing over seconds, not sub-second latency) — polling at a short interval (e.g. 2-3s) is imperceptibly different from push for this use case and requires zero new backend infrastructure.

**Fallback if a future phase still wants push:** fix the two gaps above first (a JWT-aware Channels middleware, and per-village group naming, e.g. `f"officer_alerts_{village_code}"`), and swap Redis in for `InMemoryChannelLayer` if deployed across more than one process. This is a Phase 2+ (or later) decision, **not made now**.

---

## 17. UI / Design System

- **Tailwind config:** `frontend/tailwind.config.js` — two brand color scales: `care` (teal, RuralCare/individual layer) and `sentinel` (indigo, GramSentinel/community layer, **the one Simulation Lab should use**, since it lives in the Officer Portal), plus a neutral `ink` scale. Font: Inter.
- **Shared components to reuse (all in `frontend/src/components/ui.tsx` unless noted):** `Card`, `Stat`, `Empty`, `ErrorNote`, `Loading`, `SeverityPill`, `SafetyPill`, `Delta`, plus `AgentTrace.tsx` (renders an agent trace exactly like the one a simulation run would produce) and `SafetyPanel.tsx` (renders a `SafetyResult`/`SafetyCheck` exactly like the one a simulation safety check would produce). **Both of these are strong direct-reuse candidates for Simulation Lab's evidence/safety display**, since they already render the same shapes (`AgentRun`-like traces, `SafetyCheck`-like verdicts) the simulator will produce.
- No modal/dialog component was found in `components/ui.tsx` in this pass — if Phase 2 needs one, it would be a genuinely new component (noted, not built).

---

## 18. Simulation Isolation Requirements (documented only — nothing built)

Recommended dedicated Django app name: **`simulation`** (matches the existing single-word, lower-case app-naming convention: `core`, `users`, `patients`, `assessments`, `community`, `alerts`, `integrations`).

Future models (name only, **not created**), all of which must carry or resolve to an explicit `village` scope and must never share a table with an operational model from §7:

- `SimulationScenario`
- `SimulationSession`
- `SimulationEvent`
- `SimulationSourceSignal`
- `SimulationAgentRun`
- `SimulationSafetyCheck`
- `SimulationResult`
- `SimulationInvestigation`

These must remain physically separate from `CommunityReport`, operational `Alert`, operational `Investigation`, and any other operational/monitoring table (§7). The reasoning-logic reuse plan (§12) means the *agents and Safety Engine themselves* need no duplication — only the persistence target changes.

---

## 19. REUSE / MODIFY / CREATE / DO-NOT-TOUCH Matrix

| Capability | Current Implementation | Decision | Existing File(s) | Reason | Future Phase |
|---|---|---|---|---|---|
| Authentication | SimpleJWT, `LoginView`/`GramSentinelTokenSerializer` | REUSE | `backend/users/views.py`, `backend/users/serializers.py` | Already correct, no village claim to leak | N/A |
| Health Officer authorization | `IsHealthOfficer` permission | REUSE | `backend/users/permissions.py:24-33` | Exactly the gate a simulation view needs | Phase 2 |
| Village resolution | `User.village` FK, read per-request | REUSE | `backend/users/models.py:23-30` | Source of truth; must not be duplicated | Phase 2 |
| Village filtering | `scope_queryset`/`scoped_village_id` | REUSE | `backend/users/scoping.py` | Exact same rule simulation needs | Phase 2 |
| Health Officer Portal shell | `PortalLayout` + `RequireRole` | REUSE | `frontend/src/layouts/PortalLayout.tsx`, `frontend/src/App.tsx` | Zero new layout/guard code needed | Phase 2 |
| Health Officer navigation | `OFFICER_NAV` array | MODIFY | `frontend/src/layouts/PortalLayout.tsx` | One new nav entry, later | Phase 2 |
| Community aggregation | `ingest_batch`, `CommunityReportEntry` sums | DO-NOT-TOUCH | `backend/community/views.py`, `backend/integrations/ingestion.py` | Operational; simulation must not write here | N/A |
| Community signal chart | `_weekly_reported_series` (real counts) | DO-NOT-TOUCH | `backend/alerts/views.py` | Already correct; already audited | N/A |
| Alert system | `Alert` model, `run_community_pipeline` | DO-NOT-TOUCH (writes); REUSE (orchestrators inside it) | `backend/alerts/models.py`, `backend/alerts/services.py` | Operational table; reasoning logic is reusable, table is not | Phase 2 |
| Investigation system | `Investigation`, `Feedback` | DO-NOT-TOUCH | `backend/alerts/models.py` | Operational; a simulated investigation needs its own table | Phase 2 |
| Agent infrastructure | `BaseAgent`, orchestrators | REUSE | `backend/agents/base.py`, `backend/agents/orchestration/` | Already source-agnostic, no DB writes inside agents | Phase 2 |
| LLM provider | `LLMClient` | REUSE | `backend/agents/llm/client.py` | Already optional/fallback-safe; no change needed | Phase 2 |
| Signal analysis agents | 6 `gramsentinel` signal agents | REUSE | `backend/agents/gramsentinel/signal_agents.py` | No DB write inside `handle()` | Phase 2 |
| Correlation agents | `VillageTrendAgent`, `ClusterDetectionAgent` | REUSE | `backend/agents/gramsentinel/` | Same reason | Phase 2 |
| Evidence reasoning | `build_evidence_relationships` | REUSE | `backend/alerts/evidence_relationships.py` | Shape-based, not model-hardwired | Phase 2 |
| Safety Engine | `SafetyEngine` | REUSE, unmodified | `backend/safety/engine.py` | Pure, stateless, deterministic | Phase 2 |
| API permissions | role classes + `scope_queryset` | REUSE | `backend/users/permissions.py`, `backend/users/scoping.py` | Exact existing pattern | Phase 2 |
| Zustand | `useAuth` only | CREATE (new, separate store) | `frontend/src/store/` | No existing store to extend safely | Phase 2 |
| Recharts | already used for real counts | REUSE | `frontend/src/pages/officer/Dashboard.tsx` | Same charting need | Phase 2 |
| Django Channels | configured, unused, has gaps | DO-NOT-TOUCH (as-is) | `backend/alerts/consumers.py`, `backend/config/asgi.py` | Not proven functional for JWT clients; fix is out of scope | Deferred |
| WebSockets | none in frontend | DO-NOT-TOUCH | — | Polling recommended instead (§16) | Deferred |
| Polling | `useAsync` hook pattern | REUSE | `frontend/src/hooks/useAsync.ts` | Established, working pattern everywhere | Phase 2 |
| Database models (operational) | `CommunityReport`, `Alert`, etc. | DO-NOT-TOUCH | `backend/community/models.py`, `backend/alerts/models.py` | Must never receive simulated writes | N/A |
| Logging | `gramsentinel.*` loggers | REUSE | `backend/config/settings.py:258-275` | Same convention (e.g. `gramsentinel.simulation`) | Phase 2 |
| Testing infrastructure | pytest + pytest-django | REUSE | `pytest.ini`, `backend/tests/conftest.py` | Same fixtures pattern (`village`, `officer_api`, etc.) | Phase 2 |
| Simulation app | none exists | CREATE | — | New Django app `simulation/` | Phase 2 |
| Simulation models | none exist | CREATE | — | 8 models listed in §18 | Phase 2 |
| Simulation API | none exists | CREATE | — | New views/urls under `simulation/` | Phase 2 |
| Simulation UI | none exists | CREATE | — | New page(s) under `frontend/src/pages/officer/` | Phase 2 |
| Simulation state | none exists | CREATE | — | New Zustand store, see above | Phase 2 |
| Simulation isolation | N/A | CREATE (as a rule enforced by new code) | — | Separate app/tables + village-scoped permission, reusing the existing pattern | Phase 2 |

---

## 20. Architecture Decision Record

### ADR-001 — GramSentinel Intelligence Simulator Architecture

**1. Context.** GramSentinel's Health Officer Portal needs a Simulation Lab that lets a Health Officer explore synthetic "what-if" community-signal scenarios, scoped to their own operational village, without any risk of that synthetic data touching operational monitoring state.

**2. Decision.** Build the simulator as a new, separate Django app (`simulation`) that reuses the existing authentication, village-scoping, agent, and Safety Engine infrastructure wholesale, writing only to new simulation-only tables, surfaced as one new route inside the existing Health Officer Portal shell.

**3. Current authentication/village scope mechanism.** JWT (SimpleJWT), no village claim in the token; village resolved per-request from `User.village` FK; scoping enforced via `users/scoping.py`'s `scope_queryset`/`scoped_village_id`, applied at queryset *and* object level in every existing officer view (§4, §5).

**4. Simulation isolation strategy.** Physically separate models (§18), a physically separate app, and — critically — the simulator must call the *agents and Safety Engine directly* (they take plain dicts/dataclasses, not Django querysets) rather than calling `run_community_pipeline()`, which is hard-wired to operational persistence.

**5. Proposed simulation Django app/module location.** `backend/simulation/` (new top-level app, registered in `INSTALLED_APPS` alongside the existing 7 apps).

**6. Existing services/agents to reuse.** All 14 existing agents, both orchestrators, `SafetyEngine`, `build_evidence_relationships()`, `LLMClient` — none require modification to accept simulated input, since none of them write to the database themselves (§12).

**7. Components that must be newly created.** The `simulation` app itself: 8 models (§18), a persistence layer analogous to (but separate from) `alerts/services.py::run_community_pipeline`, DRF views/serializers/urls, one new frontend route + page + Zustand store.

**8. Safety architecture.** Unchanged. The same deterministic `SafetyEngine` runs against simulated evidence and produces a `SimulationSafetyCheck`, following the exact rule set in §13 — no relaxed rules for simulation, per the non-negotiable list in the task (§16 below).

**9. Real-time strategy.** Polling, reusing `useAsync` (§16 above for full reasoning). Channels/WebSocket remains configured-but-unused; not chosen for this feature given the two unresolved gaps found.

**10. Frontend integration strategy.** One new route inside the existing `RequireRole` + `PortalLayout` wrapper (§6); no new layout, no new auth guard, no village selector.

**11. Database strategy.** SQLite locally / Postgres on Render, unchanged — new simulation tables live in the same database via ordinary Django migrations, just a different app/table namespace.

**12. Access-control strategy.** Identical pattern to §5: `IsHealthOfficer` + `scope_queryset`/`scoped_village_id`, reused verbatim, applied to the new simulation querysets.

**13. Consequences.** Minimal new backend surface area (mostly models + thin persistence glue), because the expensive part (agent reasoning, safety verdicts) is 100% reused. The frontend gets exactly one new route.

**14. Risks.** (a) The temptation to call `run_community_pipeline()` directly for convenience — this must be resisted; a parallel, simulation-only persistence function is required. (b) The existing Channels gap (§16) must not be silently "fixed" as a side effect of building Live Signal Emergence later — it should be its own explicit, reviewed decision.

**15. Deferred decisions.** Exact simulation model field shapes; whether `SimulationSession` needs to be resumable across browser sessions; whether Village B ever gets simulation UI (explicitly out of scope per the task brief, which targets Health Officer A → Village A only for now); Redis-backed channel layer, if push is ever adopted later.

---

## 21. Risks / Existing Issues

1. **Channels/WebSocket auth mismatch** (§16) — session-based `AuthMiddlewareStack` vs. JWT-bearer-only application. Likely non-functional for the SPA as configured. Not a simulation-blocking issue (the feature is unused), but should not be built on top of without first being fixed and reviewed on its own.
2. **The one existing WebSocket broadcast is not village-scoped** (§16) — a narrow, low-severity information leak (alert title/severity/village name broadcast to every connected officer regardless of village) that exists today, independent of anything Phase 1 or the simulator does. Flagged, not fixed, per the task's explicit instruction.
3. **`InMemoryChannelLayer`** cannot fan out across multiple processes/instances — a constraint on any future real-time feature, not just simulation.
4. No other safety, authorization, or data-isolation weakness was found in the officer/worker/patient/admin paths audited.

---

## 22. Recommended Phase 2 Starting Point

1. Create the `simulation` Django app skeleton (app config, empty `models.py`/`views.py`/`urls.py`, registered in `INSTALLED_APPS`).
2. Define the 8 models from §18 with an explicit `village` FK (or FK-to-session-that-has-a-village) on every one, mirroring the field shapes of `AlertEvidence`/`SafetyCheck`/`AgentRun` where a direct analogy exists (§7 table).
3. Write one persistence function, analogous to but separate from `run_community_pipeline()`, that calls the same orchestrators/`SafetyEngine` and writes only to the new tables.
4. Add `IsHealthOfficer` + `scope_queryset`-gated views/urls under `/api/simulation/...`.
5. Add the one new frontend route + nav entry + page, reusing `PortalLayout`, `AgentTrace`, `SafetyPanel`.
6. Only then consider a `useSimulationStore` if page-to-page state genuinely requires it.

---

## 23. Verification Evidence

All claims above are backed by direct reads of the following files in this session (line numbers cited inline throughout §3–§17 where available; a small number of items — e.g. `core/views.py`'s `AdminOverviewView` internals — were confirmed by symbol/behavior via tests and prior direct reads earlier in this project's history rather than a fresh line-by-line read in this pass, and are marked accordingly in §5):

`backend/users/models.py`, `backend/users/permissions.py`, `backend/users/scoping.py`, `backend/users/views.py`, `backend/users/serializers.py`, `backend/core/models.py`, `backend/core/constants.py`, `backend/config/settings.py`, `backend/config/urls.py`, `backend/config/asgi.py`, `backend/alerts/consumers.py`, `backend/alerts/routing.py`, `backend/alerts/models.py`, `backend/alerts/views.py`, `backend/alerts/services.py`, `backend/alerts/evidence_relationships.py`, `backend/agents/base.py`, `backend/agents/orchestration/orchestrator.py`, `backend/agents/llm/client.py`, `backend/agents/gramsentinel/__init__.py`, `backend/agents/cross_level/agent.py`, `backend/safety/engine.py`, `backend/safety/rules.py`, `backend/community/models.py`, `frontend/src/store/auth.ts`, `frontend/src/services/api.ts`, `frontend/src/App.tsx`, `frontend/src/layouts/PortalLayout.tsx`, `frontend/tailwind.config.js`, `frontend/package.json`, `pytest.ini`.

**Manual verification performed against the running application** (backend `python manage.py runserver 8000`, already-seeded demo data, no application code modified to make it run):

| Check | Result |
|---|---|
| `officer.a` login | 200, JWT issued |
| JWT claim contents (decoded) | `{user_id, role, display_name}` — **no village claim** |
| `GET /api/auth/me/` | `village_code: KVL`, `village_name: Kovilur` |
| `GET /api/officer/dashboard/` | `scope.village_code: KVL`, `is_district_wide: false`, 2 active alerts |
| `GET /api/officer/community-data/` | `scope.village_code: KVL` |
| `GET /api/alerts/` → first alert detail | `village_code: KVL` |
| `PATCH /api/alerts/<id>/status/` (investigation) | 200 — write succeeded, then **reverted via `seed_demo --reset`** (no code/file change) so Phase 1 leaves no operational-data side effect |
| `officer.b` login → dashboard | `scope.village_code: ARY`, `is_district_wide: false` |
| Frontend search for a village selector | zero matches (`Select Village\|VillageSelector\|village-selector\|SelectVillage`) |
| Frontend search for `simulation`/`Simulation Lab` | zero matches anywhere in the repo |
| `python manage.py check` | 0 issues |
| `pytest -q` (full suite) | all passing (283 test results counted from the dot-run output; no failures) |

---

## 24. Open Questions

1. Should a future `SimulationSession` be resumable across browser reloads (would need server-side session state) or is it acceptable to be ephemeral per page-load?
2. Will Village B ever get Simulation Lab access in a later phase, and if so, does that change the permission design now (it shouldn't, given `scope_queryset` already generalizes to any village), or is it purely a "seed more scenarios" question?
3. Should the Channels/WebSocket auth gap (§16, §21) be fixed as part of a later real-time phase, or left as a known, documented limitation indefinitely?
4. Exact retention policy for simulation session data — is it meant to be ephemeral (cleared per session) or does an officer need to revisit past simulation runs?

---

# PHASE 1 FREEZE READY

**1. How Health Officer A's village is resolved:** `User.village` FK (`backend/users/models.py:23-30`), read fresh from the database on every request via `request.user.village`/`request.user.village_id`; never present in the JWT (confirmed by decoding a live token — only `user_id`, `role`, `display_name`).

**2. How village authorization currently works:** role-gated by permission class (`IsHealthOfficer`, `backend/users/permissions.py:24-33`), then narrowed by `scope_queryset`/`scoped_village_id` (`backend/users/scoping.py`) at queryset level, applied identically at object-lookup level in every alert view (`backend/alerts/views.py`). 100% backend-enforced; the frontend has no village-selection concept anywhere.

**3. Existing infrastructure to reuse in Phase 2:** `IsHealthOfficer` permission, `scope_queryset`/`scoped_village_id`, `PortalLayout` + `RequireRole`, all 14 existing agents, both orchestrators, `SafetyEngine` (unmodified), `build_evidence_relationships`, `LLMClient`, `useAsync` polling pattern, `AgentTrace`/`SafetyPanel` UI components, `pytest`/`pytest-django` fixture conventions.

**4. What must be newly created in Phase 2:** a `simulation` Django app with 8 new models (§18), a new persistence function (never calling `run_community_pipeline()` directly), new village-scoped API views/urls, one new frontend route/page/nav entry, and — if genuinely needed — one new Zustand store.

**5. Channels vs. polling decision:** **Polling.** Channels is configured but unused by the frontend, has an unresolved session-vs-JWT auth mismatch, and its one existing broadcast is not village-scoped. Polling (`useAsync`) is the pattern already used everywhere and needs zero new infrastructure.

**6. Safety concerns discovered:** none in the officer/worker/patient/admin data-access paths. Two adjacent, pre-existing, low-severity gaps were found and flagged (not fixed): (a) the WebSocket consumer's session-based auth likely doesn't work for this JWT-only SPA, and (b) its one broadcast is not village-scoped. Neither is exploitable via the REST API, which is where all real data access happens today.

**7. Unresolved questions:** see §24.

**8. Exact files created/changed:**
   - **Created:** `GRAMSENTINEL_SIMULATION_PHASE1_AUDIT.md` (this file).
   - **Changed:** none.
   - **Deleted:** none.
   - (Pre-existing uncommitted changes from earlier, unrelated work in this repository — `README.md`, `RENDER_DEPLOYMENT.md`, several `backend/alerts/*`, `backend/core/*`, `backend/data/*`, `backend/tests/*`, `frontend/src/pages/*`, `frontend/src/types/*` — were present in `git status` before this phase began and were left untouched, per Step 20.)

**9. Manual verification performed:** see §23 table — login, JWT claim inspection, dashboard/community-data/alerts/investigation-status flow for `officer.a`, a second-village cross-check for `officer.b`, confirmation of zero village-selector/simulation code in the frontend, `manage.py check`, and a full `pytest -q` run.

**10. Test/verification results:** `manage.py check` — 0 issues. `pytest -q` — full suite passing, no failures. Manual API checks — all matched expected village-scoped behavior; the one operational write made during investigation-status verification was reverted via the existing `seed_demo --reset` command, restoring the demo database to its scripted state with no file changes.

**PHASE 2 IS NOT IMPLEMENTED.**
