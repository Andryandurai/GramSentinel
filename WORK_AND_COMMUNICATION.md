# Work & Communication

One Worker Portal tab (`/worker/work`) holding three related capabilities, plus
the matching Health Officer review area (`/officer/work`, "Team Workspace"):

1. **Supervisor Communication** — a private conversation between a Health
   Worker and their assigned Health Officer.
2. **Report Approval Tracker** — read-only status tracking for a worker's
   submitted community reports.
3. **Correction Request System** — a controlled, approval-gated way to
   request a correction to an already-submitted record, without editing it
   directly.

All backend code lives in one new Django app: `backend/workspace/`.

## Why a new app

`community/models.py`'s own module docstring enforces a schema-level privacy
boundary: *"nothing in this module has a foreign key to `patients.Patient` or
`assessments.PatientAssessment`."* A correction request genuinely needs to
reference a `PatientAssessment`. Putting these models in `community` (or
`assessments`, which has no notion of a Health Officer relationship) would
have broken that boundary or forced an awkward fit. `workspace` is a thin
workflow layer that references records from other apps by explicit FK — it
never recomputes or overrides anything those apps decided (triage, safety
verdicts, aggregation), and nothing in RuralCare, GramSentinel, the Safety
Engine, RAG, or the Simulation Lab reads from it.

## Server-derived relationships — the core security property

A worker never chooses their supervisor, another worker's data, or another
village's data by supplying an id. `workspace/services.py::assigned_officer_for(worker)`
is the **only** place "who is this worker's Health Officer" is decided — it
looks up the one active `HEALTH_OFFICER` in `worker.village`, every time,
fresh. No message, report approval, or correction request ever trusts a
client-supplied `worker_id`/`officer_id`/`village_id` — every view derives
these from `request.user` and a real database relationship
(`users.scoping.scope_queryset`, the same helper every other officer-facing
view in this project already uses).

## Models (`backend/workspace/models.py`)

- **`SupervisorMessage`** — one message. `worker` + `officer` (both
  server-derived, set once) identify the thread; there is no separate
  `Conversation` model, since a village currently has exactly one officer.
  `sender` records who wrote it. `attachment` is a data URI on the row
  itself (see below) — never a filesystem path or public URL. `read_at` is
  a timestamp, not a boolean, per the task's own preference.
- **`WorkflowStatus`** — one shared status vocabulary (`SUBMITTED`,
  `UNDER_REVIEW`, `APPROVED`, `RETURNED_FOR_CORRECTION`, `RESUBMITTED`,
  `REJECTED`) used by both `ReportApproval` and `CorrectionRequest`, so the
  two workflows can never drift apart into duplicate vocabularies.
- **`ReportApproval`** — a `OneToOneField` to `community.CommunityReport`.
  A worker resubmitting the same village/week already updates the *same*
  `CommunityReport` row (its existing `update_or_create` on
  `(village, week_label, worker)`), so a one-to-one is exactly right.
- **`ReportApprovalEvent`** — append-only transition history (the audit
  trail): `from_status`, `to_status`, `comment`, `actor`, `created_at`.
- **`CorrectionRequest`** — targets a record via `ContentType` +
  `object_id` (`GenericForeignKey`), restricted to an explicit allowlist,
  `CORRECTABLE_MODELS = ("assessments.patientassessment",
  "community.communityreport")`. `original_snapshot` freezes a
  plain-language field/value summary at request time. `mistake_description`
  and `proposed_correction` are free text, matching the actual form the
  task specified — there is no structured field-picker, and therefore no
  generic "apply this patch to that model" engine (see Immutability below).
- **`CorrectionEvent`** — mirrors `ReportApprovalEvent` for corrections.

## Status lifecycle and who controls it

```
SUBMITTED → UNDER_REVIEW → APPROVED
                          → RETURNED_FOR_CORRECTION → RESUBMITTED → UNDER_REVIEW → …
                          → REJECTED
```

`workspace/services.py::apply_status_transition()` is the single function
both `ReportApproval` and `CorrectionRequest` transitions go through. A
worker may only ever move `RETURNED_FOR_CORRECTION → RESUBMITTED` (and even
that happens indirectly, by resubmitting through the *existing* report
form — see below, not through a status-change endpoint at all). Every other
transition is Health-Officer-only and checked against a fixed
`OFFICER_ALLOWED_TRANSITIONS` table — never a caller-supplied rule. Every
transition, successful or not, is recorded in the corresponding `*Event`
table.

## Resubmission — reusing the existing submission pathway

There is no second "resubmit" endpoint. `workspace/services.py::record_report_submission()`
is called once, from inside the *existing* `community/views.py::
CommunityReportListCreateView.create()` — the one, small, clearly-commented
hook into existing code this task's own rules allowed ("a tiny change...
technically required"). First submission for a report → `ReportApproval` at
`SUBMITTED`. A resubmission while `RETURNED_FOR_CORRECTION` → `RESUBMITTED`.

## Immutability — what "approved" actually does

Approving a `CorrectionRequest` sets `applied_at` and leaves a full audit
trail — it **never** rewrites the original record's own stored columns.
This is deliberate, not a shortcut: the form collects free text ("what is
wrong" / "what it should be"), not a structured field/value pair a machine
could safely apply unattended. For a `CommunityReport`, the worker then
resubmits corrected figures through the *existing* report form (the
project's own established "how a report's numbers change" pathway). For a
`PatientAssessment`, there is currently no amend pathway at all anywhere in
this codebase — approval here is the institutional record that the
correction is authorised, not a silent rewrite of clinical history.
`temperature_c` (and every other field) on the original assessment is
verified, by test, to remain unchanged after approval.

## Attachments

`backend/workspace/attachments.py` extends the *only* existing secure
file-handling mechanism in this codebase — `users/photos.py`'s data-URI +
paranoid-signature-check pattern for profile photographs — to the document
types this feature needs (PDF, DOC/DOCX, XLS/XLSX, PNG, JPG; 8 MB limit).
An attachment is never a filesystem path or a public media URL: it lives
only inside the `SupervisorMessage` row and is served only through
`MessageAttachmentView`, which re-checks that the requesting user is
actually a party to that specific message (or a platform admin) before
decoding and returning the bytes.

## API endpoints

| Endpoint | Method | Role | Purpose |
|---|---|---|---|
| `/api/work/messages/` | GET/POST | Worker | The worker's own thread with their assigned officer; GET also marks the officer's unread messages read. |
| `/api/work/messages/<id>/read/` | POST | Worker or Officer | Mark one message read (ownership-checked). |
| `/api/work/messages/<id>/attachment/` | GET | Worker or Officer | Authenticated attachment download. |
| `/api/work/report-approvals/` | GET | Worker | The worker's own reports and their status (`?status=` filter). |
| `/api/work/correctable-records/` | GET | Worker | The worker's own recent assessments/reports, for the correction-request picker. |
| `/api/work/corrections/` | GET/POST | Worker | List / submit correction requests. |
| `/api/work/corrections/<id>/` | GET | Worker or Officer | Detail + history (ownership/scope-checked). |
| `/api/officer/work/threads/` | GET | Officer | One row per supervised worker, with unread count and preview. |
| `/api/officer/work/threads/<worker_id>/messages/` | GET/POST | Officer | Conversation with one worker (village-scoped). |
| `/api/officer/work/report-approvals/` | GET | Officer | Team's reports (`?status=` filter). |
| `/api/officer/work/report-approvals/<id>/transition/` | POST | Officer | Change a report's status. |
| `/api/officer/work/corrections/` | GET | Officer | Team's correction requests (`?status=` filter). |
| `/api/officer/work/corrections/<id>/transition/` | POST | Officer | Change a correction's status. |

Every officer-side endpoint filters through `scope_queryset` and every
cross-village or cross-owner lookup returns 404, not 403 — the same
convention `alerts/views.py::officer_alert_queryset` already established
elsewhere in this project, so existence is never confirmed to an
unauthorized user.

## Frontend

- `frontend/src/types/index.ts` — `SupervisorMessage`, `MessageThreadResponse`,
  `OfficerWorkerThread`, `WorkflowStatus`, `WorkflowEvent`, `ReportApproval`,
  `CorrectableRecord`, `CorrectionRequest`.
- `frontend/src/store/workCommunication.ts` — one Zustand store for both the
  worker's and officer's views of all three features; every field is
  populated only from a real API response.
- `frontend/src/pages/worker/WorkCommunication.tsx` — the worker tab, three
  internal sections switched by local state (not three separate routes).
- `frontend/src/pages/officer/TeamWorkspace.tsx` — the officer's review
  area: worker messages (thread list + conversation + reply), report
  approvals (with transition buttons), corrections (with transition
  buttons).
- `frontend/src/App.tsx` — routes `/worker/work` and `/officer/work`.
- `frontend/src/layouts/PortalLayout.tsx` — one new nav item per portal
  ("Work & Communication" / "Team Workspace").

## Files changed

- New: `backend/workspace/` (models, attachments, services, serializers,
  views, urls, admin, migrations), `backend/tests/test_workspace_communication.py`,
  `backend/tests/test_workspace_report_approvals.py`,
  `backend/tests/test_workspace_corrections.py`, this document.
- Modified: `backend/config/settings.py` (+app), `backend/config/urls.py`
  (+include), `backend/community/views.py` (one hook call into
  `record_report_submission`), `frontend/src/types/index.ts`,
  `frontend/src/App.tsx`, `frontend/src/layouts/PortalLayout.tsx`.
