# GramSentinel Simulation — Complete Technical Details

This document explains, with direct grounding in the current source code, how the GramSentinel Simulation Lab actually works. It is not a tutorial and not a generic description of "how a multi-agent health system works" — every claim below is traceable to a specific file, function, or test in this repository. Where the codebase defines something but does not yet use it, that is stated explicitly rather than described as working.

All source paths are relative to the repository root. Backend code lives under `backend/simulation/`; frontend code lives under `frontend/src/`.

---

## Executive Summary

The Simulation Lab is a self-contained, database-backed rehearsal environment for GramSentinel's community-signal detection concept. It runs entirely on synthetic, seeded data through the **same kind** of deterministic pipeline the product is built around, but it is a separate Django app (`simulation`) with its own models, its own API namespace (`/api/simulation/...`), and its own frontend pages. It never reads, writes, or is influenced by real patient records, real community reports, or real operational alerts.

High-level pipeline, one simulated reporting week at a time:

```
Synthetic Scenario Data (SimulationScenario / SimulationEvent / SimulationSourceSignal)
        ↓
Simulation Session (SimulationSession — one officer's run of a scenario)
        ↓
Data Ingestion Agent            (deterministic)
        ↓
Signal Analysis Agent           (deterministic trend; optional LLM-assisted wording only)
        ↓
Correlation Agent               (deterministic)
        ↓
Evidence Agent                  (deterministic, preliminary only)
        ↓
Safety Engine                   (deterministic, 9 rules, independent of the LLM)
        ↓
Intelligence / Alert Presentation (Signal Timeline, Evidence Constellation, right-panel alert)
        ↓
Human Investigation             (Investigation Notebook — officer's own decision)
        ↓
Feedback & Monitoring           (officer-experience evaluation, never autonomous tuning)
```

**Simulation vs. real operational GramSentinel data — the distinction that matters most:**

| | Simulation | Real GramSentinel |
|---|---|---|
| Models | `simulation.SimulationScenario`, `SimulationSession`, `SimulationEvent`, `SimulationSourceSignal`, `SimulationAgentRun`, `SimulationSafetyCheck`, `SimulationResult`, `SimulationInvestigation`, `SimulationFeedback` | `community.CommunityReport`, `community.CommunitySignal`, `alerts.Alert`, `alerts.Investigation`, `alerts.Feedback`, `assessments.Assessment`, `core.Patient` |
| Data source | Seeded by `core/management/commands/seed_demo.py::_seed_simulation_scenarios` | Real Health Worker assessments and community reports |
| Orchestrator | `simulation.orchestrator.MultiAgentOrchestrator` | `agents.orchestration.orchestrator` |
| Safety engine | `simulation.safety.SafetyEngine` (own PASS/BLOCK/INSUFFICIENT vocabulary) | `backend.safety.engine.SafetyEngine` (own PASS/DOWNGRADE/BLOCK vocabulary) |
| Can it create a real Alert / CommunityReport / patient record? | No — structurally impossible; the simulation app never imports the models that create those rows (see §36) | Yes, that is its purpose |

Both pipelines share the *design philosophy* (deterministic classification, an LLM used only for wording, an independent safety gate, mandatory human review) but they are two physically separate code paths. Nothing in the simulation app is wired into the real one.

---

## 1. Data Origin

### `SimulationScenario` (`backend/simulation/models.py:57`)
A reusable, database-backed template. Fields: `village` (FK, inherited from `SimulationVillageScoped`), `name`, `scenario_type` (`ScenarioType` choices — see §2), `description`, `is_active`, `version`, timestamps. One village's scenarios are versioned and uniquely constrained on `(village, scenario_type, version)`. Always synthetic. Created only by the seed command. Read by `SimulationScenarioListView` / `SimulationScenarioDetailView`.

### `SimulationSession` (`models.py:106`)
One run of a scenario. Fields: `scenario` (FK), `health_officer` (FK, nullable), `status` (`NOT_STARTED` / `IN_PROGRESS` / `COMPLETED`), `replay_position` (which week has been revealed so far), `created_at`. A session with `health_officer=None` is a **template session** — the seed-created, never-advanced holder of a scenario's canonical timeline (`models.get_template_session`). A session with `health_officer` set is a **real, officer-owned run**, created by `SimulationEngine.start()` (§15). Every officer-initiated `POST /simulation/sessions/` call creates a brand new session — sessions are never shared between officers.

### `SimulationEvent` (`models.py:187`)
One simulated reporting week within a session. Fields: `session` (FK), `week_number`, `source_signals` (JSON: `{"categories": {...}, "status_label": "...", "context": [...]}`), `is_synthetic` (always `True` for seeded data), `created_at`. `source_signals["status_label"]` is **seed-authored narrative only** — it is never read by any classification logic (see §2's worked example, where the real computed trend differs from this label). `source_signals["context"]` is an optional list of plain-text notes, read only by the Investigation Notebook's Community Context section (§32).

### `SimulationSourceSignal` (`models.py:258`)
One source's reported value for one week — the authoritative "missing ≠ zero" record. Fields: `event` (FK, related_name `per_source_signals`), `source_type` (reuses `core.constants.SourceKind`: `CHW`, `PHC`, `PHARMACY`, `SCHOOL`, `WEATHER`, `LAB`, `RURALCARE_AGGREGATE`), `value` (nullable float), `reported` (bool). A `CheckConstraint` enforces `reported=True ⇒ value is not null` and `reported=False ⇒ value is null` at the database level — it is structurally impossible to store a "missing" row with a numeric value. Only `CHW` and `PHC` are used by the four currently-seeded scenarios (§2); the other `SourceKind` values exist in the vocabulary but no seeded scenario currently populates them.

### `SimulationAgentRun` (`models.py:324`)
One persisted pipeline-stage execution. Fields: `session` (FK), `agent_name` (`ingestion` / `signal_analysis` / `correlation` / `evidence` / `safety`), `status` (`WAITING` / `PROCESSING` / `COMPLETE` / `FAILED`), `input` (JSON), `output` (JSON), `duration_ms`, `started_at`, `ended_at`. Every `advance()` call creates exactly 5 of these (4 pipeline stages + 1 safety stage), or fewer if an earlier stage failed (§12). Consumed by `simulation.intelligence.build_intelligence` and `SafetyEngine`.

### `SimulationSafetyCheck` and `SimulationResult` (`models.py:410`, `models.py:443`)
One `SimulationSafetyCheck` row per rule (9 per advance), plus one `SimulationResult` row holding the finalized `evidence_strength`, `gate_result`, and `investigation_priority` for that week. Both are an append-only audit trail — never read back by the live API (`.../intelligence/` and `.../safety/` recompute on every request via `SafetyEngine.evaluate_latest()`, so a stale persisted row can never silently diverge from what the officer is shown "now"). `is_what_if` (default `False`) marks a row as belonging to a hypothetical What-If evaluation — in practice this never survives past the request (§29), but the field exists as an explicit, defensive filter used by Monitoring (§34).

### `SimulationInvestigation` and `SimulationFeedback` — see §32 and §33.

---

## 2. Scenario Data

Only **four** scenarios are actually seeded, by `_seed_simulation_scenarios` in `backend/core/management/commands/seed_demo.py:1005`, all for a single village (Kovilur, code `KVL`). The `SimulationScenario.ScenarioType` enum also defines `WEAK_EVIDENCE`, `SOURCE_DISAGREEMENT`, `WHAT_IF`, and `REPLAY` values (`models.py:69`) — **these are defined vocabulary, not seeded scenarios; planned but not currently implemented as standalone demo scenarios.** (`SOURCE_DISAGREEMENT`-style behavior is instead demonstrated ad hoc inside the backend test suite, e.g. `test_conflicting_evidence_does_not_force_a_false_block`.)

For each scenario below, the "Real computed trend" column was verified by running the scenario to completion against the live backend on 2026-09-13 — it is **not** the seed's own `status_label` field, which is cosmetic narration only.

### Emerging Community Signal (`EMERGING_SIGNAL`, village Kovilur)
> "A synthetic community signal gradually increases across four reporting weeks — fever-related reports and CHW/PHC counts climb together."

| Week | FEVER (primary) | CHW | PHC | Seed `status_label` | Real computed trend |
|---|---|---|---|---|---|
| 1 | 2 | 2 | 5 | NORMAL | NORMAL |
| 2 | 3 | 3 | 6 | STABLE | STABLE |
| 3 | 5 | 5 | 9 | INCREASING | INCREASING |
| 4 | 8 | 8 | 14 | SIGNAL_DETECTED | **SIGNAL_DETECTED** |

Verified live result at week 4: `evidence_strength=STRONG`, `safety.gate_result=PASS`, `suggested_next_step=CONDUCT_FIELD_VERIFICATION`, supporting sources `[CHW, PHC]`, no conflicting sources, `completeness_pct=100`. Week 3 also seeds an optional community-context note ("Increased rainfall reported…"); week 4 seeds two more. This scenario is the one where the seed's cosmetic label happens to match the real computed trend at every week.

### Stable Community (`STABLE_COMMUNITY`)
> "A synthetic community signal that stays within its ordinary range across four reporting weeks — no escalation."

| Week | FEVER | CHW | PHC | Seed `status_label` | Real computed trend |
|---|---|---|---|---|---|
| 1 | 2 | 2 | 5 | NORMAL | NORMAL |
| 2 | 2 | 2 | 5 | **NORMAL** | **STABLE** |
| 3 | 3 | 3 | 5 | STABLE | STABLE |
| 4 | 2 | 2 | 5 | NORMAL | NORMAL |

Week 2 is a deliberate, concrete illustration of §2's own warning: the seed's `status_label` says "NORMAL" but `_classify_trend(current=2, previous=2)` (§6) actually returns `STABLE` (the `previous == 0` fast path does not apply, and none of the escalation/de-escalation conditions match a flat 2→2). The pipeline **never reads** `status_label` — this divergence is harmless and expected, and is exactly why the codebase's own docstrings insist the label must never be trusted as ground truth. Verified live final state: `evidence_strength=WEAK`, `safety.gate_result=PASS`, `suggested_next_step=CLOSE_AS_INSUFFICIENT_EVIDENCE`, supporting `[CHW]`, insufficient `[PHC]` (PHC never moves, so its own direction is `FLAT` every week — see §8).

### Live Signal Emergence (`LIVE_EMERGENCE`)
> "The same kind of gradually emerging community signal as 'Emerging Community Signal', run through the Phase 8 live WebSocket stream instead of manual Next-Week clicks."

| Week | FEVER | CHW | PHC | Real computed trend |
|---|---|---|---|---|
| 1 | 2 | 2 | 4 | NORMAL |
| 2 | 3 | 3 | 5 | STABLE |
| 3 | 4 | 4 | 6 | STABLE |
| 4 | 6 | 6 | 10 | INCREASING |
| 5 | 10 | 10 | 16 | SIGNAL_DETECTED |

Same underlying pipeline and rules as every other scenario (§16, §31); the only difference is transport (WebSocket instead of REST `advance()` clicks). Verified final state: `evidence_strength=STRONG`, `safety.gate_result=PASS`, supporting `[CHW, PHC]`.

### Missing Data (`MISSING_DATA`)
> "A synthetic scenario where one source stops reporting partway through — demonstrating that an absent report is recorded as not reported, never silently treated as zero."

| Week | FEVER | CHW | PHC | Real computed trend |
|---|---|---|---|---|
| 1 | 2 | 2 | 1 | NORMAL |
| 2 | 3 | 3 | 2 | STABLE |
| 3 | 4 | 4 | **not reported** | STABLE |
| 4 | 5 | 5 | **not reported** | STABLE |

Verified final state: `evidence_strength=WEAK`, `safety.gate_result=INSUFFICIENT` (Safety Rule 6 fires — `completeness_pct=75%` is below the 80% minimum), `data_quality.missing=['PHC — Week 3', 'PHC — Week 4']`, `suggested_next_step=REQUEST_MORE_DATA`. This is the scenario that actually demonstrates the missing-data safety rule (§10, Rule 6).

---

## 3. Information Flow

```
SimulationSourceSignal rows (per source, per week)
        ↓  (event.per_source_signals.all())
Data Ingestion  — { week, sources: {source_type: {reported, value}}, reported_source_count, missing_source_count }
        ↓
Signal Analysis — reads ingestion.sources' owning event's source_signals["categories"]
                  → { primary_signal, trend, current_value, previous_value, direction, explanation, explanation_used_llm }
        ↓
Correlation     — reads signal_output["direction"] + per-source current/previous SimulationSourceSignal rows
                  → { relationships: [{source, relationship, reason}], explanation }
        ↓
Evidence        — reads ingestion + signal_analysis + correlation outputs, does NOT compute a strength
                  → { primary_signal, trend, current_value, source_relationships, reporting_summary, preliminary_evidence: true, explanation }
        ↓
Safety Engine   — reads session/officer/template + the 4 upstream outputs + build_intelligence(session)
                  → { checks: [9 rule results], gate_result, human_review_required: true, evidence_strength }
        ↓
Intelligence (simulation.intelligence.build_intelligence) — re-reads the SAME persisted SimulationAgentRun rows,
                  never recomputes trend/relationship
                  → { timeline, constellation, source_fusion, data_quality, explanation } + safety merged in
        ↓
Health Officer  — SimulationLab.tsx right panel, Investigation Notebook
```

Every arrow above is a **read of already-computed, already-persisted data**, except the five pipeline-stage calls themselves (ingestion → safety), which are the one place computation actually happens, once per `advance()` call, inside one database transaction.

---

## 4. Agent Inventory

| Stage | Purpose | Input | Deterministic / LLM | Code location |
|---|---|---|---|---|
| Data Ingestion | Normalize this week's source rows | `SimulationEvent` + its `SimulationSourceSignal` rows | Fully deterministic | `orchestrator.py::_ingestion` |
| Signal Analysis | Classify the week's trend | Ingestion output + current/previous `SimulationEvent` | Trend: deterministic. Explanation sentence: optional LLM, deterministic fallback | `orchestrator.py::_signal_analysis` |
| Correlation | Compare each source's own direction to the primary trend | Signal Analysis output + current/previous source rows | Fully deterministic | `orchestrator.py::_correlation` |
| Evidence | Assemble a preliminary, unscored evidence packet | Ingestion + Signal Analysis + Correlation outputs | Fully deterministic (no strength computed here) | `orchestrator.py::_evidence` |
| Safety Engine | Independent 9-rule safety gate + evidence-strength finalization | Real session/officer + all 4 upstream outputs + `build_intelligence()` | Fully deterministic; statically verified to import no LLM | `safety/engine.py`, `safety/rules.py` |

These five are genuine pipeline **stages** ("agents" in this codebase's own vocabulary — `MultiAgentOrchestrator`, `STAGE_ORDER`). They are distinguished here from:
- **Services** — `SimulationEngine` (`services.py`): session lifecycle (start/advance), not a pipeline stage itself; it *calls* the orchestrator.
- **Engines** — `SafetyEngine`, `WhatIfEngine`: named "Engine" because each is the one authoritative place a specific kind of evaluation happens (safety rules; hypothetical rerun), not because either is an LLM or a scoring model.
- **A Safety Rule** — one of the 9 individual functions inside `safety/rules.py` (§10) — a sub-component of the Safety Engine stage, not a stage of its own.
- **UI components** — `AgentPipelineView`, `SignalStateBanner`, `SimulationResponsePanel` etc. (frontend, §47) render the above; they compute nothing.

---

## 5. Data Ingestion Agent

**WHAT it does:** Reads this week's `SimulationSourceSignal` rows for the current `SimulationEvent` and reshapes them into one structured dict.

**HOW:**
```python
def _ingestion(event, previous_event):
    sources = {}
    for row in event.per_source_signals.all():
        sources[row.source_type] = {"reported": row.reported, "value": row.value}
    ...
    return {"week": ..., "sources": sources, "reported_source_count": ..., "missing_source_count": ...}
```
(`orchestrator.py:76`)

**Where it gets information:** Directly from the database — the seeded `SimulationSourceSignal` rows for the officer's current week. No other data source exists.

**Exact input structure:** `(event: SimulationEvent, previous_event: SimulationEvent | None)` — the ORM objects themselves, not a pre-shaped dict.

**Missing vs. zero (the codebase's own central invariant):**
- `reported=True, value=0` → a genuine report of zero cases. `_ingestion` produces `{"reported": true, "value": 0}`.
- `reported=False, value=None` → no report was received. `_ingestion` produces `{"reported": false, "value": null}`.

**Why this matters:** A missing report and a genuine zero mean opposite things operationally (one means "checked, nothing found"; the other means "we don't know"). Conflating them would silently understate uncertainty. This is enforced not just by convention but by a database `CheckConstraint` on `SimulationSourceSignal` (§1) — a row that violates the distinction cannot be saved at all.

**How invalid values are handled:** There is no invalid-value path in `_ingestion` itself — by the time a row reaches here it has already passed the model's own constraint and (for What-If overrides) `WhatIfInputSerializer`'s structural validation (§24). A category with no reported values at all causes the *next* stage (Signal Analysis) to fail, not this one (see Failure behavior below).

**Output structure:** `{"week": int, "sources": {source_type: {"reported": bool, "value": float|null}}, "reported_source_count": int, "missing_source_count": int}`.

**How downstream agents receive it:** `MultiAgentOrchestrator.run_pipeline` threads `ingestion_result["output"]` directly into Signal Analysis's, Correlation's, and Evidence's own `input` dict — plain Python dict passing, no re-serialization.

**Deterministic guarantees:** No branching on wall-clock time, no randomness, no LLM call anywhere in this function.

**Failure behavior:** `_ingestion` cannot itself raise `StageFailure` under normal operation (it has no validation to fail). If it did raise unexpectedly, `MultiAgentOrchestrator.run_stage` catches it, records a `FAILED` `SimulationAgentRun` with a clean error message, and `_fill_remaining` marks every later stage (including Safety) as explicitly skipped — never silently treated as passed.

---

## 6. Signal Analysis Agent

**Input:** `(ingestion_output: dict, event: SimulationEvent, previous_event: SimulationEvent | None)`.

**Processing (`orchestrator.py::_signal_analysis`, `_classify_trend`):**

1. Read `categories` from `event.source_signals["categories"]` (e.g. `{"FEVER": 8, "RESPIRATORY": 3, "HEADACHE": 2}`). If empty, raise `StageFailure`.
2. `primary_signal = max(categories, key=lambda k: categories[k])` — the category with the largest reported count this week (ties broken by dict insertion order, i.e. whichever key was listed first in the seed data).
3. `current_value = categories[primary_signal]`; `previous_value` = that same category's value in the previous week's categories, or `None` for week 1.
4. **Trend classification — computed first, before any LLM call, and never overwritten:**

```python
def _classify_trend(current, previous):
    if previous is None:
        return NORMAL
    change = current - previous
    if previous == 0:
        if change >= 3: return SIGNAL_DETECTED
        if change >= 2: return INCREASING
        return NORMAL if change == 0 else STABLE
    change_pct = (change / previous) * 100.0
    if change_pct >= 60.0 and change >= 3: return SIGNAL_DETECTED
    if change_pct >= 25.0 and change >= 2:  return INCREASING
    if change_pct <= -20.0:                 return NORMAL
    return STABLE
```

### Signal states (exactly four; no others exist)

| State | Exact condition | Why |
|---|---|---|
| `NORMAL` | No previous week to compare, OR `previous>0` and the relative drop is ≥20%, OR `previous==0` and `change==0` | First observation, or a clear return to baseline |
| `STABLE` | Everything that is neither an escalation nor a ≥20% drop | The "nothing notable happened" default |
| `INCREASING` | `previous==0` and `change∈{2}`; or `previous>0`, `change_pct≥25%` **and** `change≥2` | A real but not yet dramatic rise — both a relative AND absolute floor, so 2→3 (+50%, +1) does *not* qualify |
| `SIGNAL_DETECTED` | `previous==0` and `change≥3`; or `previous>0`, `change_pct≥60%` **and** `change≥3` | A sharp, sustained rise by both measures |

**Worked example (real seeded data, Emerging Community Signal, week 4):** current=8, previous=5. `change=3`, `change_pct=(3/5)*100=60.0`. `60.0 ≥ 60.0` and `3 ≥ 3` → `SIGNAL_DETECTED`. Verified live.

**Combining a relative and an absolute threshold is deliberate** (documented in `orchestrator.py:112`): a purely relative rule would call 2→3 a "+50% increase" — technically true but misleading for genuinely small counts.

### Deterministic rule table

| Rule | Condition | Result |
|---|---|---|
| R1 | `previous is None` | NORMAL |
| R2 | `previous==0` and `change≥3` | SIGNAL_DETECTED |
| R3 | `previous==0` and `change≥2` | INCREASING |
| R4 | `previous==0` and `change==0` | NORMAL |
| R5 | `previous==0` and `change==1` | STABLE |
| R6 | `previous>0`, `change_pct≥60` and `change≥3` | SIGNAL_DETECTED |
| R7 | `previous>0`, `change_pct≥25` and `change≥2` | INCREASING |
| R8 | `previous>0`, `change_pct≤-20` | NORMAL |
| R9 | `previous>0`, none of the above | STABLE |

### LLM involvement

**The LLM does not determine the signal state.** This is confirmed by the code order in `_signal_analysis`: `trend = _classify_trend(...)` runs, then a deterministic `_deterministic_explanation()` sentence is built as the default, and only *after both* is the LLM optionally consulted — and only to *replace the wording of the explanation sentence*, never the `trend` value already computed. The system prompt sent to the LLM explicitly instructs it to "restate [the trend] faithfully… never contradict the given trend, never invent a different one" (`orchestrator.py:180`), but the enforcement is structural, not merely a prompt instruction: `trend` is a local Python variable assigned once, before the LLM call exists in the function, and nothing after that point ever reassigns it.

`explanation_used_llm: bool` is returned alongside the explanation so callers (and tests) can tell whether a given sentence was LLM-phrased or the deterministic fallback.

### Failure behavior

- **LLM unavailable** (`LLMUnavailable`, e.g. `LLM_ENABLED=False`, no API key): caught, logged at `info` level, the deterministic `_deterministic_explanation()` sentence is kept, `explanation_used_llm` stays `False`. The stage still returns `COMPLETE`.
- **LLM call fails unexpectedly** (network error, malformed response, timeout): caught by a broad `except Exception`, logged at `warning` level, same deterministic fallback. Verified by `test_trend_unaffected_by_llm_unavailable` and `test_llm_failure_does_not_change_the_deterministic_trend` (live-runner variant).
- **LLM returns adversarial/contradictory text** (e.g. "OUTBREAK DETECTED — confirmed outbreak, AI confidence 99%"): the trend value is unaffected (already computed), but the *wording* is used verbatim as `explanation`. This adversarial text is caught **downstream**, by Safety Rule 8, not by Signal Analysis itself — see §10 and `test_llm_contradiction_through_real_pipeline_cannot_change_gate_result`.
- **Missing input** (empty `categories`): raises `StageFailure`, recorded as a `FAILED` `SimulationAgentRun`; every later stage is marked skipped.
- **Malformed data**: cannot structurally occur — `categories` values come from `SimulationEvent.source_signals`, a JSON field populated only by the seed command or What-If's own validated override path.

---

## 7. Why Deterministic Signal Detection Instead of an LLM?

1. **Reproducibility.** `_classify_trend(8, 5)` returns `SIGNAL_DETECTED` every time, on every machine, forever. An LLM given the same numbers in natural language is not guaranteed to.
2. **Auditability.** The rule table in §6 is the entire decision surface. An officer, developer, or jury member can read nine lines of Python and know exactly why a given week was classified a certain way — there is no larger model to inspect.
3. **Safety.** The LLM literally cannot set `trend` to anything — it is not passed the ability to; it only ever receives the already-decided value and produces a sentence.
4. **Explainability.** Every threshold (60%, 25%, -20%, and the absolute floors of 3/2) is a named constant in one file, not an emergent property of model weights.
5. **Testing.** `_classify_trend` is exhaustively table-tested (`test_finalize_evidence_strength_downgrade_table` and the classification itself, exercised across all four seeded scenarios plus dedicated fixtures in `test_simulation.py` and `test_simulation_safety.py`) — exact expected outputs, not approximate ones.
6. **Failure isolation.** §6's "Failure behavior" shows the trend is computed *before* the LLM is even called — an LLM outage changes nothing about classification.
7. **Regulatory/clinical trust.** A safety-sensitive numerical classification (is this a signal worth an officer's attention?) is not the kind of decision this project is willing to hand to free-form generation, even a well-behaved one.
8. **Data consistency.** The same historical `SimulationEvent`/`SimulationSourceSignal` rows always produce the same `trend` — replaying week 3 of a session a year from now (§30) reads the same persisted value.
9. **Resistance to hallucination.** The deterministic code cannot invent a numerical trend that the underlying counts do not support — there is no generative step between the numbers and the classification.
10. **Debugging.** A developer can reproduce any classification by hand with a calculator; there is nothing to "re-run the model" for.

This is a claim about **suitability for this specific task**, not a blanket claim that deterministic code is always better than an LLM. Deterministic logic is used here specifically for: thresholding, numerical comparison, state classification, the safety gate, and access-control validation. An LLM **is** used, deliberately, for the one place natural-language generation is actually useful in this pipeline: phrasing the Signal Analysis explanation sentence (§6, §18).

---

## 8. Correlation Agent

**Input:** `(event, previous_event, signal_output)` — specifically `signal_output["direction"]` (`UP`/`DOWN`/`FLAT`, from `_trend_direction`) and each source's current/previous `SimulationSourceSignal` row.

**Processing (`orchestrator.py::_correlation`):** For every source reported this week, compute that source's own direction (`current.value - previous.value`, sign only) and compare it to the primary signal's direction.

### Deterministic rule table

| Source condition | Primary condition | Result | Reason text |
|---|---|---|---|
| `current_row.reported == False` | any | `INSUFFICIENT` | "`{source}` did not report this week." |
| No usable previous week (`previous_row is None` or not reported or `value is None`) | any | `INSUFFICIENT` | "`{source}` has no usable prior week to compare against." |
| Source direction == primary direction, and neither is FLAT | — | `SUPPORTING` | "`{source}` moved {direction}, matching the primary signal." |
| Either direction is FLAT | — | `INSUFFICIENT` | "`{source}` moved {direction}, too small to compare against the primary signal." |
| Source direction opposite primary direction, neither FLAT | — | `CONFLICTING` | "`{source}` moved {direction}, opposite the primary signal." |

**What happens when a source is missing:** `INSUFFICIENT`, never silently dropped from the constellation and never treated as agreement or disagreement.

**What happens when a source agrees:** `SUPPORTING` — contributes to a stronger evidence strength (§9) and is listed in `explanation.sources_supporting`.

**What happens when a source disagrees:** `CONFLICTING` — visible in the Evidence Constellation and in `explanation.sources_conflicting`, and (per Safety Rule 5, §10) this **never by itself blocks or downgrades** the result; disagreement is surfaced for human interpretation, not auto-resolved.

**Why disagreement does not mean a source is "wrong":** the code makes no causal claim anywhere — it only classifies *directional agreement*, and the reason string is a plain factual statement ("PHC moved down, opposite the primary signal"), never an inference about why.

**Real verified example (Missing Data scenario, week 4):** `supporting=['CHW']`, `insufficient=['PHC']` — PHC has not reported since week 3, so every subsequent week correlates it as `INSUFFICIENT`.

**Why correlation is useful:** it turns "does the rest of the evidence line up with the headline number?" into an explicit, per-source, auditable answer instead of leaving the officer to eyeball raw counts.

---

## 9. Evidence Agent

**What it receives:** the ingestion, signal-analysis, and correlation outputs for the current week.

**How it assembles evidence (`orchestrator.py::_evidence`):** a plain reshaping — `primary_signal`, `trend`, `current_value` (copied from signal analysis), `source_relationships` (copied from correlation's `relationships` list), `reporting_summary` (counts from ingestion), and a fixed flag `preliminary_evidence: True`.

**Does it create an evidence strength?** **No.** The Evidence stage itself computes nothing numeric — it explicitly labels its own output `"This is not a final evidence strength or safety determination."` The actual `STRONG`/`MODERATE`/`WEAK` value is computed one layer up, in `simulation.intelligence._evidence_strength` (Phase 5), and *finalized* (downgrade-only) by the Safety Engine (`safety/engine.py::finalize_evidence_strength`, §10).

**Exact evidence categories — a fixed lookup table, not a score:**

```python
def _evidence_strength(trend, supporting, conflicting):
    escalating = trend in (INCREASING, SIGNAL_DETECTED)
    if not escalating or supporting == 0 or conflicting > supporting:
        return "WEAK"
    if escalating and supporting > 0 and conflicting == 0:
        return "STRONG"
    return "MODERATE"
```
(`intelligence.py:75`)

| Evidence condition | Result |
|---|---|
| Trend not escalating, OR no supporting source at all, OR conflicting sources outnumber supporting ones | WEAK |
| Escalating trend, ≥1 supporting source, 0 conflicting sources | STRONG |
| Everything else (e.g. escalating with a genuine disagreement, or escalating with only insufficient corroboration) | MODERATE |

This is three small integers/booleans through an `if`/`elif`/`else` — there is no weighted formula, percentage, or "confidence" anywhere in this function.

**How missing data affects evidence:** indirectly, through `supporting`/`conflicting` counts (a missing source contributes to neither, so it can only ever pull toward `WEAK`, never inflate `STRONG`) — and directly through the Safety Engine's separate completeness rule (Rule 6, §10), which can independently downgrade the finalized value regardless of what this preliminary lookup produced.

---

## 10. Safety Engine

`simulation.safety.SafetyEngine` (`backend/simulation/safety/engine.py`) is the fifth and final pipeline stage. It is **physically separated** into its own `simulation/safety/` package specifically so it can be statically verified to import no LLM client — `test_no_llm_import_under_safety_package` (`test_simulation_safety.py:631`) parses every `.py` file under that package with Python's `ast` module and fails the whole suite if `agents.llm`, `openai`, or `anthropic` is ever imported there. This is the one Safety Engine test in this project that is enforced by static analysis of the source text itself, not just by behavior.

It is independent of the operational `backend.safety.engine.SafetyEngine` — different vocabulary (`PASS`/`BLOCK`/`INSUFFICIENT` here, vs. `PASS`/`DOWNGRADE`/`BLOCK` operationally), different rules, different purpose (this one gates a *simulation* session, never an operational `Alert`).

All 9 rules verified against the current code (`safety/rules.py`):

### Rule 1 — `village_scope_verified`
- **Purpose:** re-derive the officer's own village independently of whatever permission layer already ran.
- **Input:** `scoped_village_id(ctx.officer)` vs `ctx.session.village_id`.
- **Condition:** officer has a village AND it differs from the session's village.
- **BLOCK:** "Session village does not match the authenticated officer's village."
- **PASS:** "Session village matches the authenticated officer's village."
- **INSUFFICIENT:** never returned by this rule.
- **Failure scenario:** Officer B, scoped to Village B, somehow obtains a reference to a Village A session and calls `SafetyEngine.evaluate_latest` directly (bypassing the view layer). Verified by `test_unauthorized_village_direct_engine_call_cannot_silently_pass`.
- **Why it matters:** the third of three independent village checks (§35) — even a bug in the other two cannot leak cross-village data past this one.
- **Code:** `safety/rules.py:161`.

### Rule 2 — `reporting_period_validated`
- **Purpose:** confirm `session.replay_position` corresponds to a real, contiguous seeded reporting history.
- **Condition:** `position ≤ 0`; OR the scenario has no seeded weeks; OR `position` is not among the scenario's seeded weeks; OR the revealed weeks `1..position` have a gap.
- **BLOCK:** in every one of the above cases (distinct reason text per case).
- **PASS:** "Reporting period (week N) is valid."
- **Failure scenario:** a session's `replay_position` is manually forced past the last seeded week. Verified by `test_reporting_period_beyond_available_data_is_blocked`.
- **Code:** `safety/rules.py:184`.

### Rule 3 — `duplicate_records_checked`
- **Purpose:** catch duplicate *pipeline processing* for the same week (e.g. a retried `advance()` call), which the schema's uniqueness constraints do **not** by themselves prevent (those constrain `SimulationEvent`/`SimulationSourceSignal`, not `SimulationAgentRun`).
- **Condition:** more than one `ingestion`-named `SimulationAgentRun` claims the same `output["week"]` for this session.
- **BLOCK:** "Duplicate pipeline processing detected for week(s) N…"
- **PASS:** explicitly explains that the schema's own constraints already prevent duplicate events/signals — this rule catches the one remaining duplicate class.
- **Failure scenario:** verified by `test_duplicate_ingestion_records_for_the_same_week_are_blocked`, which manually injects a second ingestion row.
- **Code:** `safety/rules.py:234`.

### Rule 4 — `sufficient_historical_window`
- **Purpose:** refuse to treat an escalating trend as safe to act on until at least `MIN_HISTORICAL_WEEKS = 3` reporting weeks have been revealed.
- **Condition:** `trend ∈ {INCREASING, SIGNAL_DETECTED}` AND `revealed_count < 3`.
- **INSUFFICIENT:** "Only N reporting week(s) are available; additional historical data is required before escalation."
- **PASS:** any non-escalating trend, or an escalating trend with ≥3 revealed weeks.
- **Failure scenario (verified by test, not by a seeded scenario — no currently seeded scenario reaches an escalating trend before its 3rd week):** `test_insufficient_historical_window_for_an_escalating_signal` seeds week 1 `FEVER=2`, week 2 `FEVER=6` (a jump that reaches `SIGNAL_DETECTED` with only 2 revealed weeks) → `INSUFFICIENT`.
- **Why 3:** every real seeded scenario is a 4-week timeline, and Emerging Signal's own trend first reaches `INCREASING` at week 3 — the earliest point an escalating signal genuinely exists to evaluate (`safety/rules.py:52`).
- **Code:** `safety/rules.py:274`.

### Rule 5 — `source_relationships_evaluated`
- **Purpose:** confirm the Correlation stage's output is structurally usable before Safety relies on it — **not** a judgment on whether sources agree.
- **Condition:** evidence output is malformed/missing expected keys/`source_relationships` isn't a list; OR `intelligence["constellation"]` is empty; OR any constellation entry has an unrecognized `relation`.
- **INSUFFICIENT:** in each malformed/empty case above.
- **PASS:** "Source relationships evaluated across N source(s)." — **including when sources conflict.** The rule's own comment is explicit: "A conflicting source is not, by itself, unsafe… Manufacturing a BLOCK here merely because evidence disagrees would be a false failure."
- **Failure scenario:** `test_malformed_evidence_output_is_non_pass_not_an_exception` feeds four different malformed shapes and confirms none crash the engine — all return `INSUFFICIENT`, never an exception, never a false `PASS`.
- **Code:** `safety/rules.py:296`.

### Rule 6 — `missing_data_assessed`
- **Purpose:** gate on overall reporting completeness.
- **Condition:** `intelligence["data_quality"]["completeness_pct"] < MIN_COMPLETENESS_PCT (80)`.
- **INSUFFICIENT:** "Reporting completeness is N%, below the 80% required before escalation."
- **PASS:** "Reporting completeness is N%, meeting the required threshold."
- **Real seeded example:** Missing Data scenario, week 4 — `completeness_pct=75%` → `INSUFFICIENT`, verified live.
- **Why 80%:** set above the Missing Data scenario's own steady-state figure (75% once PHC stops reporting) specifically so that scenario deterministically demonstrates this rule, while the fully-reporting scenarios (100% throughout) are unaffected (`safety/rules.py:61`).
- **Code:** `safety/rules.py:351`.

### Rule 7 — `no_individual_diagnosis_generated`
- **Purpose:** prevent any upstream narrative text (i.e. wording the LLM may have supplied, §6/§13) from presenting an individual clinical diagnosis.
- **Condition:** the lower-cased concatenation of `signal_output["explanation"]` and `evidence_output["explanation"]` contains any of: `"diagnosis is"`, `"diagnosed with"`, `"the patient has"`, `"confirmed case of"`, `"patient is positive for"`.
- **BLOCK:** "Upstream narrative contains individual-diagnosis language ('…')…"
- **PASS:** "No individual-diagnosis language detected…"
- **Failure scenario:** `test_individual_diagnosis_language_is_blocked` injects `"The patient has confirmed dengue fever."` directly into `signal_output["explanation"]` → BLOCK.
- **Code:** `safety/rules.py:379`, phrase list `safety/rules.py:83`.

### Rule 8 — `no_autonomous_outbreak_declaration`
- **Purpose:** prevent any narrative text from declaring an outbreak.
- **Condition:** same narrative text as Rule 7, checked against: `"outbreak confirmed"`, `"confirmed outbreak"`, `"outbreak declared"`, `"outbreak detected"`, `"declare an outbreak"`, `"declaring an outbreak"`, `"we declare"`, `"epidemic confirmed"`.
- **BLOCK:** "Upstream narrative contains an autonomous outbreak-declaration phrase ('…')…"
- **PASS:** "No outbreak-declaration language detected…"
- **Adversarial-LLM test:** `test_llm_contradiction_through_real_pipeline_cannot_change_gate_result` mocks the LLM client to return `"OUTBREAK DETECTED — this is a confirmed outbreak, AI confidence 99%."` through the *real* Signal Analysis stage, then confirms `gate_result == BLOCK` and this exact rule fires. This is the strongest available evidence that outbreak-declaration protection works end-to-end, not just against a hand-built dict.
- **Code:** `safety/rules.py:399`, phrase list `safety/rules.py:97`.

### Rule 9 — `human_review_required`
- **Purpose:** an unconditional standing invariant, not a gate on any condition.
- **Condition:** none — always evaluates the same way.
- **Result:** always `PASS`, always with the reason "Human review is always required before any operational action is taken on this signal."
- **Why it matters:** this is the rule that formally states "even a full PASS is not autonomous approval" (§12, §14).
- **Code:** `safety/rules.py:419`.

---

## 11. Safety Result Aggregation

```python
def _aggregate(results):
    values = {r.result for r in results}
    if SafetyGateResult.BLOCK in values: return BLOCK
    if SafetyGateResult.INSUFFICIENT in values: return INSUFFICIENT
    return PASS
```
(`safety/engine.py:50`, tested by `test_aggregate_rule_is_block_over_insufficient_over_pass`)

**Precedence: `BLOCK > INSUFFICIENT > PASS`.** A single rule returning `BLOCK` makes the whole week's `gate_result` `BLOCK`, regardless of how many other rules passed. This means one unsafe condition (an authorization mismatch, a forbidden phrase, a duplicate record) is enough to override eight rules that all passed — the aggregate is never a majority vote or an average.

**Evidence-strength finalization is separate from, but coupled to, this aggregate** — `finalize_evidence_strength(preliminary, gate_result)` (`safety/engine.py:62`) is strictly downgrade-only:

| `gate_result` | Effect on evidence strength |
|---|---|
| `BLOCK` | forced to `WEAK`, regardless of preliminary value |
| `INSUFFICIENT` | one tier down (`STRONG→MODERATE`, `MODERATE→WEAK`, `WEAK→WEAK`) |
| `PASS` | unchanged |

A `min()` against the preliminary tier is applied as a second, redundant safety net so that even a future coding mistake in the branches above could not accidentally produce an upgrade (verified exhaustively by `test_finalize_evidence_strength_never_upgrades`).

---

## 12. Safety vs. Signal Detection — an explicit distinction

**`SIGNAL_DETECTED` does not mean "outbreak," and does not mean automatic public-health action.** Concretely:

```
Signal Detection   ≠   Safety Approval   ≠   Human Decision
(Signal Analysis        (Safety Engine's         (Health Officer,
 stage, §6)              9 rules, §10)            Investigation Notebook, §32)
```

- `SIGNAL_DETECTED` is only the Signal Analysis stage's trend classification — a statement about the shape of reported counts over time, nothing else.
- Reaching `SIGNAL_DETECTED` does not bypass or shortcut the Safety Engine — all 9 rules still run, and can still produce `BLOCK` or `INSUFFICIENT` for an escalating week (e.g. if it happens before 3 revealed weeks, or with poor completeness).
- Even a `SIGNAL_DETECTED` + `gate_result=PASS` week is never presented as a conclusion — Rule 9 (§10) guarantees `human_review_required: true` on every single evaluation, and the frontend's own recommendation (§27, §28) is always phrased as an investigative next step ("conduct field verification"), never a diagnosis or an outbreak statement.
- The word "outbreak" never appears anywhere in a system-generated payload except inside the phrase-detection lists themselves (§10, Rules 7/8) and the tests that inject it adversarially.

---

## 13. Outbreak Protection

The mechanism is **deterministic substring matching against upstream narrative text**, implemented as Safety Rules 7 and 8 (§10) — not a separate "sanitization" layer, not an assertion system, and not an LLM-based classifier judging its own output.

- `_narrative_text(ctx)` (`safety/rules.py:140`) concatenates and lower-cases `signal_output["explanation"]` and `evidence_output["explanation"]` — the only two places free-text (potentially LLM-phrased) content exists anywhere in the pipeline.
- Rule 8 checks that text against a fixed 8-phrase list (`OUTBREAK_DECLARATION_PHRASES`); Rule 7 against a fixed 5-phrase list (`INDIVIDUAL_DIAGNOSIS_PHRASES`).
- A match forces `gate_result=BLOCK` for that whole evaluation — via the aggregation rule in §11, this single BLOCK overrides everything else.
- These lists are this package's **own**, independent of the two other phrase lists that exist elsewhere in the codebase (`core.constants.PROHIBITED_OUTPUT_TERMS`, `backend.safety.rules.PROHIBITED_TERMS`) — documented as a deliberate choice to keep `simulation/safety/` physically self-contained and independently auditable, at the cost of some duplication (`safety/rules.py:70-106`).
- **Verified end-to-end, not just unit-tested:** `test_llm_contradiction_through_real_pipeline_cannot_change_gate_result` and `test_malicious_llm_output_is_still_blocked_over_the_live_path` (live-streaming variant) both mock the LLM client to actually return outbreak-declaration text through the real Signal Analysis stage, and confirm the Safety Engine still blocks it.

**Honest limitation:** this is substring matching against a fixed phrase list, not semantic understanding. A sufficiently different phrasing of the same claim (not on either list) would not be caught by these two rules specifically — though Rule 9's unconditional human-review requirement still applies regardless.

---

## 14. Human-in-the-Loop

```
System detects a signal (Signal Analysis, §6)
        ↓
System gathers evidence (Correlation + Evidence, §8-9)
        ↓
Safety gate evaluates (9 rules, §10-13)
        ↓
Health Officer investigates (Investigation Notebook, §32)
        ↓
Health Officer decides (POST .../investigation/decision/)
```

**What the system does not decide:** which `InvestigationDecision` to record. `suggested_decision()` (§28) computes a *suggestion*, never persisted as the actual decision, never read by the decision-recording endpoint. `InvestigationDecisionDecisionInputSerializer` requires the officer to submit one of the seven values explicitly; nothing auto-fills it.

**`InvestigationDecision` vocabulary — verified against `models.py:533`:**

| Value | Display label |
|---|---|
| `CONTINUE_MONITORING` | Continue monitoring |
| `REQUEST_MORE_DATA` | Request more data |
| `VERIFY_WITH_PHC` | Verify with PHC |
| `CONDUCT_FIELD_VERIFICATION` | Conduct field verification |
| `REQUEST_LABORATORY_VERIFICATION` | Request laboratory verification |
| `ESCALATE_FOR_HUMAN_REVIEW` | Escalate for human review |
| `CLOSE_AS_INSUFFICIENT_EVIDENCE` | Close as insufficient evidence |

Deliberately its own vocabulary — **not** a reuse of the operational `alerts.Feedback.Outcome` (`VALID_SIGNAL`/`FALSE_ALERT`/`RESOLVED`), which answers a different, post-hoc question. Every one of the seven options is a next *investigative* step, never a medical or treatment recommendation, and never something the system selects on its own.

**Safety BLOCK hard-stops decision recording** — `SimulationInvestigationDecisionView.post()` re-evaluates `SafetyEngine.evaluate_latest()` fresh (never trusting a stale frontend value) and returns HTTP 403 if `gate_result == BLOCK`, before the decision is ever written (`views.py:463-500`; verified by `test_safety_block_prevents_decision_recording`).

---

## 15. Simulation Engine

`simulation.services.SimulationEngine` (`services.py`) — session lifecycle only, never the pipeline itself.

**Session states (`SimulationSession.Status`, `models.py:126`) — the real names in this codebase, not an illustrative `RUNNING`/`COMPLETE` naming:**

| Status | Meaning |
|---|---|
| `NOT_STARTED` | A seed-created template session, never advanced (`health_officer=None`) — permanent state |
| `IN_PROGRESS` | A real officer-owned run, between `start()` and its final week |
| `COMPLETED` | The session has landed on the scenario's last seeded week; can never advance again |

**`start(scenario, health_officer)`** (`services.py:351`): re-verifies village scope independently of the view-layer permission; creates a new `SimulationSession` at `IN_PROGRESS`, `replay_position = 1`; returns week 1's raw data with **no pipeline run** (the multi-agent pipeline runs on `advance()` only — week 1 has no "previous week" to analyze yet).

**`advance(session, health_officer, on_stage_start=None, on_stage_persisted=None)`** (`services.py:380`): re-verifies village scope; rejects if `status != IN_PROGRESS` (`SimulationSessionNotRunning`, HTTP 409); moves `replay_position` forward one seeded week; flips `status` to `COMPLETED` the instant it lands on the last seeded week; runs and persists the 5-stage pipeline inside one `transaction.atomic()` block (§16). A `COMPLETED` session cannot advance again — enforced here in the service layer, not only by the frontend disabling a button.

**Reset:** there is no server-side "reset a session" endpoint — `resetSession()` (frontend, §47) simply discards the client-side session reference and returns to the scenario picker; the session's own database rows are untouched (they remain available for Replay, §30, even after the officer navigates away).

**Error handling:** `SimulationVillageMismatch` (403) for a cross-village attempt; `SimulationSessionNotRunning` (409) for advancing a session that is not `IN_PROGRESS`, or for a scenario with no seeded timeline.

The optional `on_stage_start`/`on_stage_persisted` hooks are Phase 8's Live Streaming addition — both default to `None`, so the ordinary REST `advance()` call is completely unaffected; only `simulation.live_runner` supplies them (§31).

---

## 16. Multi-Agent Orchestrator

`MultiAgentOrchestrator` (`orchestrator.py:297`) runs stages 1–4 only (`ingestion → signal_analysis → correlation → evidence`); the 5th stage (safety) deliberately lives outside this class, invoked separately by `simulation.services._persist_agent_runs` — because Safety needs the `SimulationSession`/officer to re-verify village scope (Rule 1) and to read back the just-persisted week's own `SimulationAgentRun` rows (Rules 5/6), neither of which the pure `run_pipeline()` call has or needs.

**Exact execution order, fixed:** `STAGE_ORDER = ("ingestion", "signal_analysis", "correlation", "evidence", "safety")` — a plain Python tuple, never reordered by any stage's own output, never decided by an LLM.

**Can stages be skipped or reordered?** No skipping by choice, no reordering ever. A stage *can* fail to complete (§5's Failure behavior) — in that case every remaining stage, including safety, is explicitly recorded as `FAILED`/skipped by `_fill_remaining`, never silently omitted and never marked as if it had succeeded.

**What happens when an earlier stage fails:** `run_pipeline` checks each stage's `status` immediately after running it; on the first non-`COMPLETE` result it calls `_fill_remaining(results, failed_at)`, which appends a `FAILED` entry for every stage from `failed_at`'s successor onward, each with `output={"error": "Skipped: an earlier stage ({failed_at}) failed."}`.

**How `SimulationAgentRun` is persisted (`services.py::_persist_agent_runs`, `_create_agent_run`):** one row per stage result, `duration_ms`/`started_at`/`ended_at` computed by walking a single timestamp cursor forward by each stage's own measured duration (so five rows for one `advance()` call form a contiguous, non-overlapping timeline). Status transitions map 1:1 from the stage result: `COMPLETE` or `FAILED`. `input`/`output` are stored exactly as the stage function produced them — plain JSON, never prose.

**Safety persistence, when evidence genuinely completed:** the real `SafetyEngine.evaluate_latest()` runs; its result becomes the 5th `SimulationAgentRun` (`agent_name="safety"`); if evidence completed, `_persist_safety_evaluation` additionally writes 9 `SimulationSafetyCheck` rows and one `SimulationResult` row. If the Safety Engine itself raises an unexpected exception (a genuine bug, not a rule finding), the row is persisted as `FAILED` with a generic error message — **never a false `COMPLETE`/PASS** (`services.py:284`, comment: "never let a bug produce a false PASS").

---

## 17. Agent Failure Handling

| Failure | Actual behavior |
|---|---|
| Data Ingestion fails | Cannot normally happen (no validation to fail); if it did, every later stage recorded `FAILED`/skipped |
| Signal Analysis fails | Raises `StageFailure` only when `categories` is empty; correlation/evidence/safety all skipped |
| Correlation fails | No `StageFailure` path exists in `_correlation` under normal input; an unexpected exception is caught by `run_stage`'s broad `except Exception`, recorded `FAILED`, remaining stages skipped |
| Evidence fails | Same generic exception-catching behavior as Correlation |
| Safety fails (unexpected exception, not a rule BLOCK) | Persisted as `FAILED` with `{"error": "Safety evaluation could not complete."}` — never a false PASS |
| LLM fails (unavailable or errors) | Caught inside Signal Analysis; deterministic fallback sentence used; `trend` unaffected; stage still `COMPLETE` |
| Malformed agent output reaches Safety | Rule 5 (`source_relationships_evaluated`) returns `INSUFFICIENT`, never an exception — verified by `test_malformed_evidence_output_is_non_pass_not_an_exception` across four different malformed shapes |
| Missing data | Represented structurally (`reported=False`), never coerced to a value; propagates into lower evidence/completeness, never a crash |

Every stage function runs inside `MultiAgentOrchestrator.run_stage`'s own `try/except`, which catches both the project's own `StageFailure` and any unexpected `Exception`, always producing a structured `FAILED` result rather than letting a raw traceback reach the officer or the HTTP response.

---

## 18. LLM Usage

**There is exactly one place an LLM is consulted anywhere in the simulation feature: Signal Analysis's explanation-wording call** (`orchestrator.py:178`, `_signal_analysis`). Confirmed by a repository-wide grep for `get_llm_client`/`LLMUnavailable`/`agents.llm` under `backend/simulation/` — the only real import and usage is in `orchestrator.py`; the two other textual matches (in `models.py` and `safety/engine.py`) are documentation strings, not code.

- **Which agent uses it:** Signal Analysis, and only for the human-readable `explanation` sentence.
- **Where the call occurs:** `orchestrator.py::_signal_analysis`, after `trend` has already been computed.
- **What input is sent:** category name, current value, previous value (or "unavailable"), and the already-decided `trend` string — never patient data, never raw source rows, never anything identifying.
- **What output is expected:** one short plain-language sentence (`max_tokens=80`).
- **Is the output structured?** No — free text, used only as a display string.
- **Can it alter numerical results?** No — see §6's "LLM involvement."
- **What happens if it fails?** Deterministic template fallback (§6, §17); the stage never fails because of an LLM issue.
- **Does a fallback exist?** Yes, always — `_deterministic_explanation()`, computed unconditionally before the LLM is ever attempted.

**LLM client implementation (`backend/agents/llm/client.py`):** a plain `requests.post()` HTTPS call to the Anthropic Messages API (`LLM_API_URL`, default `https://api.anthropic.com/v1/messages`) — no vendor SDK is installed (`requirements.txt` has no `anthropic`/`openai` package). `LLM_ENABLED` defaults to `bool(LLM_API_KEY)` (`config/settings.py:238`) — i.e. **disabled by default** unless an API key is configured in the environment. `LLMClient.summarise()` raises `LLMUnavailable` on any failure (no key, network error, empty response, non-2xx status); it never raises an unrecoverable exception into the caller. The client module's own docstring states its three governing constraints: (1) every caller must have a deterministic fallback, (2) only already-aggregated, non-identifying data is ever sent, (3) nothing here can influence the Safety Engine — narrative it produces is screened *by* the engine, never the reverse.

**Under `simulation/safety/`, no LLM is used at all** — statically enforced (§10, §13).

**Deterministic vs. LLM table:**

| Component | Deterministic? | LLM? | Why | Failure safety |
|---|---|---|---|---|
| Data Ingestion | Yes | No | Pure reshaping | N/A |
| Signal Analysis — trend | Yes | No | Safety-sensitive classification | N/A |
| Signal Analysis — explanation sentence | Fallback yes | Optional | Natural-language wording only | Deterministic fallback always available |
| Correlation | Yes | No | Directional comparison | N/A |
| Evidence (preliminary) | Yes | No | Structured reshaping | N/A |
| Evidence strength (Phase 5) | Yes | No | Fixed lookup table | N/A |
| Safety Engine (9 rules) | Yes | No, statically verified | Independent, auditable gate | N/A |
| Investigation suggestion (`suggested_decision`) | Yes | No | Reused deterministic mapping (§28) | N/A |
| Monitoring aggregates | Yes | No | ORM counts/percentages | N/A |
| Replay | Yes (read-only) | No | Re-displays persisted data | N/A |
| What-If | Yes | Inherits Signal Analysis's optional LLM wording | Reruns the real pipeline | Same fallback as live pipeline |
| Access control / validation | Yes | No | Server-derived identity/village only | N/A |

---

## 19. Why GramSentinel Does Not Use One LLM for Everything

- **Numerical decisions** (is this a signal? how strong is the evidence? does safety pass?) are handled by deterministic code because they are exactly the kind of decision where "the same input must always produce the same output" is a hard requirement, not a nice-to-have.
- **Safety** rules are auditable line-by-line (§10) — a jury member or an officer can read the nine functions in `safety/rules.py` and know exactly what was checked; a single model's internal reasoning offers no equivalent guarantee.
- **Reproducibility** — Replay (§30) depends on this: viewing week 3 of a session today must show the same trend/evidence/safety result it showed when the officer first advanced into it. An LLM re-asked the same question is not guaranteed to answer identically.
- **Hallucination resistance** — the LLM is never given the ability to invent a count; it only ever receives numbers already computed by code and is asked to describe them in one sentence.
- **Traceability** — every result in this document maps to a named rule or function (§6, §8, §9, §10). There is no equivalent trace for "why did the model say this."
- **Testing** — the entire deterministic surface is table-tested (§6's rule table, §10's rule-by-rule tests, §11's aggregation tests) with exact expected outputs; that is not achievable for free-form generation.
- **Human control** — the LLM never becomes the final decision-maker; Rule 9 (§10) and the Investigation Notebook (§32) both structurally guarantee a human makes the last call.
- **Appropriate role for the LLM** — used exactly once, for exactly the kind of task language models are actually good at: turning an already-decided classification into a readable sentence (§6, §18).

This is not a claim that LLMs are unsafe in general. It is a claim specific to this project: for a safety-sensitive numerical early-warning workflow, deterministic rules provide reproducibility and auditability that this use case specifically requires, and the LLM is reserved for the one task — natural-language wording — where those properties are not the bottleneck.

---

## 20. Why Use Multiple Agents Instead of One Model?

The five-stage split (Ingestion → Signal Analysis → Correlation → Evidence → Safety) exists for:

- **Modularity** — each stage has one job and one, independently testable function (`_ingestion`, `_signal_analysis`, `_correlation`, `_evidence`, the 9 safety rules).
- **Traceability** — `SimulationAgentRun` persists every stage's own input/output separately, so `AgentTrace`-style views can show exactly what each stage received and produced (§47).
- **Failure isolation** — a failure in one stage is recorded and stops the pipeline cleanly (§17) rather than corrupting a monolithic computation.
- **Testability** — each stage function is called directly by unit tests with hand-built inputs, without needing to run the whole pipeline (e.g. every Safety rule test constructs a `SafetyContext` directly).
- **Separation of concerns** — Correlation only ever compares directions; Evidence only ever reshapes; Safety is the only place authorization, completeness, and phrase-screening rules live. No single function does more than one of these.
- **Safety boundaries** — the physical package separation of `simulation/safety/` (§10) is a direct consequence of wanting one stage to be independently, statically auditable for LLM-freedom.
- **Human review** — the pipeline's terminal state is always "safety evaluated, human review required" (Rule 9), never an autonomous action of any stage.

None of the five stages is "independently intelligent" in the sense of having its own learned model or judgment — each is a plain Python function (optionally, for stage 2 only, assisted by one LLM call for wording). "Multi-agent" in this codebase means "a fixed pipeline of narrowly-scoped, independently-persisted processing steps," not a group of autonomous reasoning entities negotiating with each other.

---

## 21. How the Simulation Prevents Incorrect Results

| Risk | What prevents it | If prevention fails |
|---|---|---|
| Missing report treated as zero | `reported`/`value` DB `CheckConstraint` (§1, §5) | Cannot happen — constraint violation at save time |
| Cross-village data leak | 3 independent checks: permission class, `officer_may_access_village` (service layer), Safety Rule 1 (§35) | Any one of the three alone still blocks it |
| Duplicate pipeline processing | Safety Rule 3 (§10) | `BLOCK`, visible in the checklist |
| Escalating trend acted on too early | Safety Rule 4, `MIN_HISTORICAL_WEEKS=3` (§10) | `INSUFFICIENT` |
| Poor reporting completeness silently ignored | Safety Rule 6, `MIN_COMPLETENESS_PCT=80` (§10) | `INSUFFICIENT`, evidence downgraded |
| LLM invents a numeric trend | Trend computed before the LLM call, never overwritten (§6) | Structurally impossible given current code |
| LLM produces outbreak/diagnosis language | Safety Rules 7 & 8, substring match (§10, §13) | `BLOCK`, verified end-to-end against a mocked adversarial LLM |
| A stage silently fails but is shown as succeeding | `_fill_remaining` marks every later stage `FAILED` explicitly (§16) | N/A — this is the guarantee itself |
| A conflicting source manufactures a false BLOCK | Safety Rule 5 explicitly refuses to gate on disagreement alone (§10) | N/A |
| Malformed upstream output crashes safety evaluation | Rule 5 returns `INSUFFICIENT` for four different malformed shapes rather than raising (§17) | N/A |
| A bug inside the Safety Engine produces a false PASS | Any unexpected exception is caught and recorded as `FAILED`, never `COMPLETE` (§16) | N/A |
| Human review skipped | Rule 9, unconditional (§10) | Structurally impossible — Rule 9 always PASSes but always exists |
| What-If input contaminates the real session | `transaction.atomic()` + unconditional `set_rollback(True)` (§29) | Database guarantee, not a promise |
| Replay silently recomputes a different result for an old week | Reads the exact persisted `SimulationAgentRun`/safety row for that week; never calls `SafetyEngine.evaluate()` again (§30) | N/A |
| A hypothetical (What-If) result contaminates Monitoring statistics | `is_what_if` filter, plus What-If never survives its own transaction anyway (§29) | N/A |
| Simulation data reaches an operational table | The `simulation` app imports no operational model that writes rows (§36) | N/A |

---

## 22. Missing Data

**Missing ≠ zero — enforced at the database layer** (§1, §5): `SimulationSourceSignal` cannot store `reported=False` with a non-null `value`.

**Effect at each stage:**
- **Signal Analysis:** unaffected directly — trend is computed from `SimulationEvent.source_signals["categories"]`, a separate denormalized summary that is always populated by the seed data for the primary category; a missing *source* does not remove the category total.
- **Correlation:** a source with `reported=False` this week is classified `INSUFFICIENT` (§8) — never silently excluded, never treated as agreement or disagreement.
- **Evidence:** an `INSUFFICIENT` source contributes to neither `supporting` nor `conflicting` counts, which can only ever pull the preliminary evidence strength toward `WEAK` (§9).
- **Safety:** Rule 6 (§10) independently checks overall `completeness_pct` (reported weeks ÷ expected weeks, per source and overall — `intelligence.py::_compute_data_quality`) against an 80% floor, regardless of what Correlation/Evidence separately concluded.
- **Recommendation:** `suggested_decision()` (§28) checks `completeness_pct < 80` **before** looking at evidence strength or conflicting sources at all — insufficient completeness always routes to `REQUEST_MORE_DATA` first.

---

## 23. Source Disagreement

Three concrete cases, using the real system vocabulary (`SUPPORTING` / `CONFLICTING` / `INSUFFICIENT`):

- **CHW supports, PHC supports:** both sources' own week-over-week direction matches the primary signal's direction → both `SUPPORTING` → contributes toward `STRONG` evidence (verified live: Emerging Community Signal and Live Signal Emergence, both `supporting=[CHW, PHC]`, `evidence_strength=STRONG`).
- **CHW supports, PHC conflicts:** PHC's direction is opposite the primary signal's → `CONFLICTING` for PHC → evidence can only reach `MODERATE` at best (never `STRONG`, since `_evidence_strength` requires zero conflicting sources for `STRONG`) → `suggested_decision()` routes to `VERIFY_WITH_PHC` specifically (§29's What-If example demonstrates exactly this transition: STRONG→MODERATE when PHC is overridden low).
- **Source unavailable:** `INSUFFICIENT` (§8) — neither agreement nor disagreement is claimed.

**Why disagreement does not mean a source is "wrong":** nothing in `_correlation` or `_evidence_strength` makes a truth claim about which source is correct — it only reports directional (dis)agreement as a fact for the officer to investigate. Safety Rule 5 explicitly refuses to treat disagreement as unsafe by itself (§10).

---

## 24. Data Quality

`simulation.intelligence._compute_data_quality` (`intelligence.py:137`) — the **one** completeness formula in the codebase, reused unmodified by both the real session view and What-If's hypothetical evaluation.

- **`completeness_pct`** (overall) = `total_reported ÷ (expected_weeks × source_count) × 100`, rounded.
- **Per-source `completeness_pct`** = `reported_weeks ÷ expected_weeks × 100` for that one source.
- **`expected_weeks`** = the number of weeks *this session* has actually revealed so far (`session.replay_position`), never the scenario's eventual full length — a session on week 2 of 4 is not penalized for weeks 3–4 it has not reached yet.
- **`missing`** — an explicit list of `"{source} — Week {n}"` strings, one per not-reported source/week pair. Never inferred, never silently summarized away.
- **`duplicates_checked`** — hard-coded `False`, with an explicit code comment stating no duplicate-report metadata exists anywhere in the schema: **"say so plainly rather than inventing detection."**

**How poor data quality affects evidence/safety:** feeds Safety Rule 6 directly (§10) and, indirectly, the Evidence strength lookup (§9) through reduced `supporting` counts when sources are missing.

---

## 25. Intelligence View

`simulation.intelligence.build_intelligence(session, as_of_week=None)` (`intelligence.py:194`) assembles the ONE payload every frontend intelligence component reads: `{timeline, constellation, source_fusion, data_quality, explanation}` (+ a `safety` key merged in by `with_safety`, §10).

| Field | Source | Computed here, or copied? |
|---|---|---|
| `timeline[].value` | `SimulationEvent.source_signals["categories"][primary_signal]` | Copied (real reported count) |
| `timeline[].status` | The revealed week's own persisted `signal_analysis` `SimulationAgentRun.output["trend"]` | Copied — **never recomputed** |
| `constellation` | The most recent completed `correlation` run's `relationships` | Copied |
| `source_fusion` | Same `relationships`, merged with the latest week's raw ingestion values | Copied + one merge |
| `data_quality` | `_compute_data_quality(revealed_events)` | Computed here (the one formula, §24) |
| `explanation.evidence_strength` | `_evidence_strength(trend, len(supporting), len(conflicting))` | Computed here (the one lookup, §9) |
| `explanation.signal` / `routed_reason` | Fixed phrase templates (`_TREND_PHRASES`) keyed by `trend` | Computed here, deliberately **never** the persisted `signal_analysis` run's own (possibly LLM-phrased) explanation — this panel stays 100% template-driven with zero LLM involvement, even indirectly |
| `explanation.safety_status` | The latest persisted `safety` run's own `explanation` string | Copied |

**`as_of_week`** (used by Replay, §30) caps the revealed history at an earlier point instead of always "now" — the exact same truncation logic, just anchored differently.

---

## 26. "Why This Alert?" / "Why Am I Seeing This?"

Produced entirely from `explanation` (§25) — `signal`, `sources_supporting`, `sources_conflicting`, `sources_insufficient`, `data_quality_summary`, `evidence_strength`, `routed_reason`, `suggested_verification`, `safety_status`. Every one of these is either a direct copy of already-computed stage output or a deterministic phrase-template lookup keyed by an already-computed value (`_TREND_PHRASES`, `_VERIFICATION_BY_STRENGTH`) — nothing here performs a new classification.

---

## 27. Red `SIGNAL_DETECTED` Alert

Implemented in the frontend at `frontend/src/pages/officer/SimulationLab.tsx` (`SignalStateBanner`). It reads `intelligence.timeline`'s last entry — the exact same `status` field described in §25 — and applies red styling **only** when `latest.status === 'SIGNAL_DETECTED'`. **The frontend computes nothing here** — `deriveSignalReading()` only picks the latest/previous timeline points and a display `percent`, purely for presentation; the underlying `SIGNAL_DETECTED` classification itself came entirely from the backend (§6).

The recommendation shown alongside it (`RecommendedNextStep`) reads `intelligence.suggested_next_step` — the backend's `suggested_decision()` value (§28) — through a **fixed phrasing lookup** (`RECOMMENDATION_SENTENCE`), never invented client-side. When `safety.gate_result === 'BLOCK'`, the banner is overridden with a fixed safety-wording sentence regardless of what the recommendation would otherwise have been.

A hypothetical (What-If) version of this same banner exists in the right panel's `SimulationResponsePanel`, explicitly labeled `🔴 HYPOTHETICAL SIGNAL DETECTED` and visually distinct (violet "HYPOTHETICAL" badge) — never rendered with the same styling as a real detection (§29's own original-vs-hypothetical distinction).

---

## 28. Officer Recommendation

`simulation.investigation.suggested_decision(intelligence, safety)` (`investigation.py:208`) — the **one** recommendation function in the codebase, reused verbatim by:
- `SimulationSessionIntelligenceView` (`.../intelligence/`),
- `SimulationSessionReplayView` (`.../replay/`),
- `SimulationSessionWhatIfView` (`.../what-if/`, against the hypothetical intelligence/safety),
- `simulation.monitoring._decision_alignment` (§34).

```python
def suggested_decision(intelligence, safety):
    if safety.get("gate_result") == BLOCK:
        return ""
    if data_quality.completeness_pct < 80:
        return REQUEST_MORE_DATA
    if conflicting sources exist:
        return VERIFY_WITH_PHC if "PHC" in conflicting else REQUEST_MORE_DATA
    if evidence_strength == "STRONG":
        return CONDUCT_FIELD_VERIFICATION
    if evidence_strength == "WEAK":
        return CLOSE_AS_INSUFFICIENT_EVIDENCE
    return CONTINUE_MONITORING
```

**Deterministic mapping table (in evaluation order):**

| Condition | Result |
|---|---|
| `safety.gate_result == BLOCK` | `""` (nothing to suggest) |
| `completeness_pct < 80` | `REQUEST_MORE_DATA` |
| Any conflicting source, and `"PHC"` among them | `VERIFY_WITH_PHC` |
| Any conflicting source, `"PHC"` not among them | `REQUEST_MORE_DATA` |
| `evidence_strength == STRONG` | `CONDUCT_FIELD_VERIFICATION` |
| `evidence_strength == WEAK` | `CLOSE_AS_INSUFFICIENT_EVIDENCE` |
| Otherwise (`MODERATE`, no conflicts, complete data) | `CONTINUE_MONITORING` |

**Verified progression (`test_simulation_signal_alert.py::test_recommendation_changes_across_the_real_progression`):** STABLE → `CLOSE_AS_INSUFFICIENT_EVIDENCE`, INCREASING → `CONDUCT_FIELD_VERIFICATION`, SIGNAL_DETECTED → `CONDUCT_FIELD_VERIFICATION` — not a single constant across the progression, and never invented per-request.

**SYSTEM RECOMMENDATION vs. HUMAN DECISION:** `suggested_next_step`/`suggested_decision` is exposed everywhere as a **non-binding, always-recomputed suggestion** — it is never persisted anywhere as "the decision," and `SimulationInvestigationDecisionView` (§14, §32) has no code path that reads it. The officer's actual `InvestigationDecision` is a separate, explicit POST.

---

## 29. What-If Simulation

`simulation.what_if.WhatIfEngine.run(session, officer, overrides)` (`what_if.py`) — the one hypothetical-rerun mechanism.

**What can be changed:** only the current week's per-source numeric values (`overrides: {source_type: number|null}`) — validated as an allowlist of exactly the source types this session's current real week actually has (`WhatIfInputSerializer` validates structure; `WhatIfEngine` validates the allowed keys). A `null` override means "hypothetically not reported" (`reported=False`), preserving the missing-vs-zero distinction (§5) even for hypothetical input.

**Who changes it:** the authenticated officer, via `POST /simulation/sessions/<id>/what-if/` — re-verified against `officer_may_access_village` independently of the view-layer permission (three total checks, matching every other session endpoint).

**Where it is stored:** nowhere, durably. A throwaway `SimulationSession`/`SimulationEvent`/`SimulationSourceSignal` set is created **inside** one `transaction.atomic()` block, used to rerun the real pipeline, and the block **always** ends in `transaction.set_rollback(True)` — this is a database guarantee, not a promise the code merely intends to keep.

**Does original data change?** No — verified by `test_what_if_leaves_original_rows_unchanged` and, more strongly, by re-fetching `.../intelligence/` for the real session after a What-If call and asserting byte-for-byte equality (`test_simulation_signal_alert.py::test_what_if_conflict_downgrades_evidence_and_changes_recommendation_without_touching_original`).

**How the pipeline is rerun:** the exact same `MultiAgentOrchestrator.run_pipeline()` (§16) — no second orchestrator. Only stages 1–4 run inside `WhatIfEngine`; stage 5 is a fresh `SafetyEngine.evaluate()` call against the **real** session/officer (so village-scope and reporting-period checks still validate against genuine history) but with `intelligence_override` substituting the hypothetical constellation/completeness for Rules 5/6.

**Do all agents execute?** Yes — ingestion, signal_analysis, correlation, evidence, then safety, in the same fixed order.

**Central architectural fact — category totals are never overridden:** only the current week's *source values* are hypothetical; `SimulationEvent.source_signals["categories"]` (what Signal Analysis classifies from) is copied unchanged from the real week. **This means `hypothetical.trend` can never differ from the original week's own trend** — only correlation, evidence strength, safety, and the recommendation can change, because overriding a source's value can still flip its own directional relationship against the (unchanged) primary trend.

**How original vs. hypothetical is compared / marked:** the response is `{week, is_hypothetical: true, original: {...}, hypothetical: {...}, changed_sources: [...]}`. `original` is read from the real session's own **persisted** safety row (`_persisted_safety_for_week`, shared with Replay, §30) — never recomputed. `hypothetical` carries the full rerun result including its own `pipeline` (raw stage outputs, for transparency) and `safety`.

### Real, verified example (not invented — run against the live backend, session started from scenario 36, "Emerging Community Signal," week 3)

| | Original | Hypothetical (`PHC` overridden to `2`) |
|---|---|---|
| CHW | 5 (reported) | 5 (unchanged) |
| PHC | 9 (reported) | **2** |
| Trend | INCREASING | INCREASING *(unchanged — category totals never overridden)* |
| Correlation | CHW & PHC both SUPPORTING | CHW SUPPORTING, **PHC CONFLICTING** |
| Evidence strength | STRONG | **MODERATE** |
| Safety gate | PASS | PASS (unchanged) |
| `suggested_next_step` | `CONDUCT_FIELD_VERIFICATION` | **`VERIFY_WITH_PHC`** |

`changed_sources: ["PHC"]`. Re-fetching the real session's own `.../intelligence/` afterward returned the identical `STRONG`/`CONDUCT_FIELD_VERIFICATION` original state — confirming isolation.

---

## 30. Replay

`simulation.replay.build_replay_state(session, week=None)` (`replay.py`) is deliberately **read-only** in every sense: no `SimulationEvent`, `SimulationAgentRun`, `SimulationSafetyCheck`, or `SimulationResult` row is ever created, modified, or deleted by this module.

- **`replay_position`** bounds what is reachable — `min_week` (the scenario's first seeded week) to `max_week = session.replay_position` (the session's own current, already-revealed position). A future/unrevealed week is a structural 400 (`ReplayWeekOutOfRange`), not merely a frontend-disabled button.
- **Do agents rerun?** No. `build_intelligence(session, as_of_week=week)` (§25) just caps which already-revealed weeks are read. Safety is read back from the exact persisted `SimulationAgentRun` row for that week (`_persisted_safety_for_week`) — `SafetyEngine.evaluate()`/`evaluate_latest()` is never called again by this module. This is intentional: recomputing safety for an old week could, in principle, silently show a different result if a future code change ever touched a threshold constant, misrepresenting what the officer actually saw at the time.
- **Does data change?** No.
- **How does the UI reconstruct the historical view?** By calling `GET .../replay/?week=N`, which returns the exact same `intelligence` shape (§25) `.../intelligence/` returns, just anchored at week N.

---

## 31. Live Signal Emergence

```
Officer's browser                     Django Channels (ASGI)
─────────────────                     ───────────────────────
WebSocket connect                →    JWTAuthMiddleware (ws_auth.py) resolves scope["user"]
  ?token=<JWT access token>      →    SimulationSessionConsumer.connect() — 5-check authorization
                                       (authenticated · session exists · real officer-owned
                                        session, not a template · role HEALTH_OFFICER/admin ·
                                        officer_may_access_village)
                                  ←    simulation.connected snapshot
send {action:"start"}            →    LiveSessionRunner created, joins group simulation_session_<id>
                                       run() loop: for each remaining week →
                                         SimulationEngine.advance() (the SAME service call
                                         the REST endpoint uses) with on_stage_start/
                                         on_stage_persisted hooks
                                  ←    simulation.week_started {week}
                                  ←    simulation.stage {week, stage, status: PROCESSING}
                                  ←    simulation.stage {week, stage, status: COMPLETE, payload: <SimulationAgentRun>}
                                       (repeated per stage, in STAGE_ORDER)
                                  ←    simulation.week_completed {week, is_complete}
                                  ←    simulation.completed {week}   (once the last seeded week is reached)
send {action:"pause"/"resume"/"stop"} → LiveSessionRunner.pause()/resume()/stop()
                                  ←    simulation.paused / simulation.resumed / simulation.stopped
```

**Route:** `ws/simulation/sessions/<int:session_id>/`, wrapped only for this one route by `JWTAuthMiddleware` (`simulation/routing.py`, `config/asgi.py`) — every other consumer in the project still uses the unmodified `AuthMiddlewareStack`.

**Authentication:** a browser `WebSocket` cannot set an `Authorization` header, so the JWT access token travels as a `?token=` query parameter (`frontend/src/services/api.ts::buildSimulationSocketUrl`); `JWTAuthMiddleware` resolves it to `scope["user"]`, never raising — an invalid/missing token becomes `AnonymousUser()`, and `connect()` is the one place that actually rejects the connection (with a specific close code: `4401` unauthenticated, `4403` forbidden, `4404` not found/template session).

**Village authorization:** identical rule to every REST endpoint — `officer_may_access_village` (§35), re-checked independently in `_load_authorized_session`.

**Event types (verified exhaustively against `consumers.py`/`live_runner.py`):** `simulation.connected`, `simulation.started`, `simulation.week_started`, `simulation.stage`, `simulation.week_completed`, `simulation.completed`, `simulation.paused`, `simulation.resumed`, `simulation.stopped`, `simulation.error`.

**Is the frontend animation the source of truth? No.** `_advance_one_week_sync` runs entirely inside `database_sync_to_async` — every week's `advance()` call fully commits (its own `transaction.atomic()`, the same one the REST endpoint uses) **before** a single event for that week is broadcast. `run()` only drains an already-collected list of plain-dict events afterward, pacing included. `STAGE_PACING_SECONDS=0.5` and `WEEK_PACING_SECONDS=0.8` (`live_runner.py:79-80`) are the **only** simulation-pacing values anywhere in the feature, isolated in this one module specifically so they can be set to `0` (changing only how fast an officer *sees* already-computed, already-persisted results arrive) without touching what is computed.

**Concurrency:** one `LiveSessionRunner` per session, enforced by a process-local `_RUNNERS` dict — an explicitly documented limitation, consistent with the project's `CHANNEL_LAYERS` setting (`InMemoryChannelLayer`, "enough for a single demo process"; a horizontally-scaled deployment would need a Redis/DB-backed lock instead).

**Ownership on disconnect:** a live run belongs to the WebSocket connection that started it; `disconnect()` stops the runner it owns. Another connected tab is merely an observer and is unaffected; it can issue "start" again afterward to resume from the next unadvanced week (nothing is lost — every already-advanced week is already durably persisted).

---

## 32. Investigation Notebook

Opened via "Investigate Signal" from Simulation Lab, routed to `/officer/simulation/investigation/:sessionId`, backed by `SimulationInvestigation` (§1).

- **Creation:** `GET .../investigation/` is get-or-create — opening the notebook *is* the action that creates the row, immediately at `IN_PROGRESS` (`views.py::SimulationInvestigationView.get`). No separate "create" endpoint exists.
- **One-per-session:** enforced at the database level (`unique_simulation_investigation_per_session` constraint), not merely by convention.
- **Notes:** `PATCH .../investigation/` with `notes`; frontend debounces autosave at 800ms (`store/simulation.ts::saveInvestigationNotes`, `NOTES_DEBOUNCE_MS`) — never one request per keystroke.
- **Checklist:** derived fresh every time from `checklist_items(intelligence)` (`investigation.py:54`) — only items relevant to *this* session's actual sources plus 6 fixed items (timeline reviewed, missing data reviewed, contradictions reviewed, community context reviewed, field observations reviewed, human verification completed). `normalize_checklist` discards any client-supplied key not in this session's own item set. When every item is checked, status auto-transitions to `READY_FOR_DECISION`.
- **Decision:** `POST .../investigation/decision/`, restricted to the 7-value `InvestigationDecision` vocabulary (§14); rejected outright with HTTP 403 if Safety is `BLOCK`.
- **Attribution:** always `request.user` — the serializers have no field capable of accepting a client-supplied officer id (`decided_by`, and `SimulationFeedback.officer`, §33).
- **Safety restrictions:** viewing/updating the notebook is allowed even under `BLOCK` (the officer must be able to see *why* it is blocked); only the decision-recording step is hard-blocked.
- **PDF export:** `GET .../investigation/report/`, generated by `investigation.py::build_investigation_report_pdf` via `reportlab` (`requirements.txt: reportlab==4.2.2`) — deterministic, no LLM call anywhere in PDF generation. Every page is stamped "SYNTHETIC SIMULATION — DEMONSTRATION ONLY — NOT REAL SURVEILLANCE DATA."
- **What stays simulation-only:** the whole model (`is_simulation=True`, non-editable field), `decided_by`/`officer_notes`/`observations` never reference a real patient or operational record structurally (no such field exists on the serializers to populate).

---

## 33. Feedback

`SimulationFeedback` (§1, one per investigation) — a Phase 10 addition, deliberately its **own** vocabulary, not a reuse of `InvestigationDecision` or the operational `alerts.Feedback.Outcome`.

**What the officer can rate:**

| Field | Choices |
|---|---|
| `usefulness` | Very useful / Useful / Partially useful / Not useful |
| `evidence_sufficiency` | Sufficient / Partially sufficient / Insufficient |
| `recommendation_helpful` | Yes / Partially / No |
| `additional_verification_required` | Yes / No |
| `comment` | free text |

**How it is stored:** `SimulationFeedback`, `UniqueConstraint(["investigation"])` — `PATCH .../investigation/feedback/` always updates the same row (get-or-create), never creates a second one.

**Attribution:** always `request.user`, overwritten on every save regardless of what was there before ("never silently change authorship").

**Does it change the simulation, thresholds, or safety rules? No — explicitly.** `SimulationFeedback` is read by exactly one other module, `monitoring.py`, for display aggregation only (§34). It is never read by `SafetyEngine`, `MultiAgentOrchestrator`, or `SimulationEngine`. Nothing in the feedback view can modify `SimulationResult.evidence_strength`/`gate_result` or `SimulationInvestigation.decision` — the serializer and view have no code path that writes to those fields. "Missing feedback" (`submitted: False`) is kept structurally distinct from any real negative choice (verified by `test_missing_feedback_is_distinct_from_any_negative_choice`).

---

## 34. Monitoring

`simulation.monitoring.build_monitoring_report(village)` (`monitoring.py`) — village-scoped, backend-aggregated, read-only.

**Metrics produced:**

| Section | Content |
|---|---|
| `sessions` | total / completed real (officer-owned) sessions |
| `investigations` | started, decisions recorded, decision rate (`MonitoringRatio`) |
| `feedback` | submitted count, response rate, per-choice distribution for all 4 feedback fields |
| `evidence` | count of `STRONG`/`MODERATE`/`WEAK` finalized results |
| `safety` | count of `PASS`/`INSUFFICIENT`/`BLOCK` |
| `decisions` | distribution across the 7 `InvestigationDecision` values |
| `source_relationships` | **per-source** SUPPORTING/CONFLICTING/INSUFFICIENT tally, read from persisted `correlation` `SimulationAgentRun.output` |
| `missing_data_occurrences` | count of `reported=False` rows |
| `decision_alignment` | aligned / differed / no_suggestion, comparing each decided investigation's actual decision to a freshly recomputed `suggested_decision()` |
| `recent_activity` | last 15 activity-history entries, village-wide, flattened from existing `SimulationInvestigation.activity_history` — no new event system |
| `quality_observations` | fixed, count-based sentences (e.g. "N week(s) produced weak evidence") |

**Source relationship tally is explicitly NOT pairwise** — it tallies each source's relationship to the *primary signal*, never a source-to-source cross-tabulation, because the underlying correlation data was never computed that way (§8) — inventing a pairwise table would be a second, unrequested computation.

**`MonitoringRatio` shape:** `{numerator, denominator, percentage, limited_sample}` — `limited_sample: true` whenever `denominator < MIN_SAMPLE_SIZE (5)`, and `percentage: null` (never a crash) when `denominator == 0`.

**What-If isolation:** every evidence/safety aggregate filters `SimulationResult.objects.filter(is_what_if=False)` — belt-and-braces, since What-If's `transaction.atomic()` rollback (§29) already prevents its rows from surviving in the first place.

**Is this observability or autonomous tuning? Observability only, explicitly.** `monitoring.py`'s own module docstring: "This module is READ-ONLY. It never writes to any model — Phase 10 is an observability/evaluation loop, never an autonomous learning or tuning loop… nothing here can change a safety rule, an evidence-strength value, a threshold, or an officer's decision." Decision alignment is deliberately framed as "alignment," never "AI accuracy" — a human choosing differently from the suggestion is not treated as an error anywhere in this module.

---

## 35. Security / Village Scoping

`Officer A → Village A`, `Officer B → Village B`, **no Village C**, and no village selector exists anywhere in the simulation UI or API.

**Defense in depth — every session-scoped endpoint has (at minimum) two independent layers, several have three:**

1. **Object-level DRF permission** (`simulation.permissions.IsScenarioInOfficerVillage` / `SessionBelongsToOfficerVillage`) — compares `scoped_village_id(request.user)` against the object's `village_id`, returns HTTP 403 (deliberately not 404) on mismatch.
2. **Service-layer re-check** (`simulation.services.officer_may_access_village`) — called again, independently, inside `SimulationEngine.start/advance`, `WhatIfEngine.run`, and every view's own explicit re-check before touching a session.
3. **Safety Engine Rule 1** (`village_scope_verified`, §10) — a *third*, independent re-derivation, evaluated as part of the normal rule sequence on every `.../safety/`/`.../intelligence/` call, not bolted on as a special case.
4. **WebSocket consumer's own 5-check `connect()`** (§31) — the same rule set re-implemented for the one transport that cannot reuse DRF permission classes directly.

**Officer identity and village are always server-derived** — `scoped_village_id(request.user)`/`scope["user"]`, resolved from the authenticated JWT, never accepted as a client-supplied field. Every serializer that writes attribution (`decided_by`, `SimulationFeedback.officer`) structurally has no id field a client could populate.

**A district-wide officer (no village)** is treated as unrestricted — the same rule `users.scoping` already applies everywhere else in the codebase, not a simulation-specific carve-out. `SimulationMonitoringView` is the one endpoint that explicitly refuses this case (HTTP 400: "Intelligence Monitoring is currently village-scoped only") rather than silently aggregating across villages.

**Why frontend village selectors cannot be trusted:** there is no frontend-supplied village id anywhere in the simulation request/response cycle to trust in the first place — `CurrentScopeBanner` (`SimulationLab.tsx`) is a read-only reflection of the officer's own `useAuth().user.village`, and the backend independently re-derives and enforces the officer's village on every request regardless of what the frontend displays.

---

## 36. Simulation / Operational Isolation

Simulation data is structurally, not just conventionally, separate from operational data:

- **Physically separate app.** `simulation` is its own Django app with its own models — `SimulationScenario`/`Session`/`Event`/`SourceSignal`/`AgentRun`/`SafetyCheck`/`Result`/`Investigation`/`Feedback`. None of these is a subclass or proxy of an operational model.
- **What is protected — verified by grep across `backend/simulation/`:** the app imports exactly two things from operational code, both read-only reuses of a *vocabulary*, never a write path: `from alerts.models import Alert` (only to reuse `Alert.Severity` — LOW/MODERATE/HIGH — for `SimulationResult.investigation_priority`, `services.py:52`), and, separately, `core.constants.SourceKind` for the source-type vocabulary (§1). **No code path in `simulation/` ever calls `Alert.objects.create()`, `CommunityReport.objects.create()`, `Investigation.objects.create()` (the operational one), `Feedback.objects.create()` (operational), or touches any `Patient`/`Assessment` model.**
- **Every simulation model carries its own explicit `village` FK** (`SimulationVillageScoped`, §1) rather than relying on a join chain — a deliberate duplication so a permission check is always a same-row comparison.
- **How isolation is tested — directly, not assumed:** every major test file includes an explicit operational-isolation assertion, e.g. `test_full_simulation_run_leaves_operational_tables_untouched`, `test_signal_detected_week_never_touches_operational_tables`, `test_safety_evaluation_leaves_operational_tables_untouched`, `test_no_operational_alert_investigation_or_feedback_created`, `test_replay_leaves_operational_data_untouched`, `test_what_if_leaves_operational_tables_untouched`, `test_investigation_workflow_never_touches_operational_tables`, `test_monitoring_never_touches_operational_tables`, `test_live_run_never_touches_operational_tables` — each captures `_operational_counts()` (Alert/Investigation/Feedback/CommunityReport row counts) before and after exercising the simulation feature and asserts equality.
- **What-If's isolation is a database guarantee, not application logic** — the throwaway session/event/signal rows exist only inside one `transaction.atomic()` block that always ends in `transaction.set_rollback(True)` (§29); even before that rollback, the real session's own read path (`build_intelligence`, `SafetyEngine`) never queries the throwaway rows at all.

---

## 37. Complete Decision Trace Example (real data)

Session for **Emerging Community Signal**, advanced to week 4, verified live against the running backend on 2026-09-13.

```
Week 4
  ↓
Source values: CHW=8 (reported), PHC=14 (reported)
  ↓
Ingestion: {"CHW": {"reported": true, "value": 8}, "PHC": {"reported": true, "value": 14}},
           reported_source_count=2, missing_source_count=0
  ↓
Signal Analysis: primary_signal="FEVER" (categories {"FEVER": 8, "RESPIRATORY": 3, "HEADACHE": 2})
                 current=8, previous=5 (week 3's FEVER value)
                 change=3, change_pct=60.0%
                 60.0 ≥ 60.0 AND 3 ≥ 3  →  trend = SIGNAL_DETECTED
  ↓
Correlation: CHW week3→4: 5→8 (UP), same direction as primary (UP) → SUPPORTING
             PHC week3→4: 9→14 (UP), same direction as primary (UP) → SUPPORTING
  ↓
Evidence: preliminary packet — escalating trend, 2 supporting, 0 conflicting sources
  ↓
Safety: all 9 rules → PASS (village verified · period valid week 4 · no duplicates ·
        4 revealed weeks ≥ 3 minimum · relationships evaluated across 2 sources ·
        completeness 100% ≥ 80% · no diagnosis language · no outbreak language ·
        human review always required)
        → gate_result = PASS, evidence_strength: preliminary STRONG (escalating,
          2 supporting, 0 conflicting) → finalize_evidence_strength(STRONG, PASS) = STRONG
  ↓
Right-panel result: 🔴 SIGNAL DETECTED · Evidence Strength: STRONG · Safety: PASS
  ↓
Officer recommendation: suggested_decision() → completeness 100% (not <80) →
        no conflicting sources → evidence STRONG → CONDUCT_FIELD_VERIFICATION
        → "Verify the signal with PHC and conduct field verification before
           further escalation."
  ↓
Human investigation: officer opens the Investigation Notebook, reviews the
        checklist, and records ONE of the 7 InvestigationDecision values —
        the system never selects this for them.
```

---

## 38. If the Jury Asks: "Why Did the System Give This Answer?"

1. The data came from **seeded `SimulationEvent`/`SimulationSourceSignal` rows** — a synthetic demonstration timeline, never a real patient or a real community report.
2. The ingestion stage normalized **which sources reported, and what value each reported (or that a value was missing)**, preserving the missing-vs-zero distinction structurally.
3. Signal Analysis applied **a fixed, published threshold table** (relative AND absolute change floors) to classify the week's trend — computed before any language model was ever involved.
4. Correlation evaluated **each source's own week-over-week direction against the primary trend's direction**, producing SUPPORTING/CONFLICTING/INSUFFICIENT — never a causal claim.
5. Evidence considered **only the counts of supporting vs. conflicting sources and whether the trend was escalating**, through a fixed three-outcome lookup table — no score, no percentage.
6. Safety checked **nine independent, deterministic rules** — authorization, reporting-period validity, duplicate detection, historical sufficiency, relationship validity, completeness, and two banned-phrase screens — with one BLOCK anywhere overriding everything else.
7. The system therefore produced **a signal classification, an evidence strength, a safety verdict, and a non-binding investigative recommendation** — never a diagnosis, never an outbreak declaration, never an autonomous action.
8. The Health Officer remains responsible for **reviewing the evidence in the Investigation Notebook and recording their own decision from a fixed list of next-step options** — the system's recommendation is a suggestion it never persists as the actual decision.

---

## 39. If the Jury Asks: "Why Not Just Use an LLM?"

"We intentionally do not use an LLM as the source of truth for numerical signal detection or safety decisions." The trend classification (§6), the source-correlation logic (§8), and the nine-rule safety gate (§10) are all deterministic Python, chosen specifically for:

- **Reproducibility** — the same seeded week always classifies the same way, forever.
- **Auditability** — every threshold is a named constant in one file; every safety rule is a short, independently-readable function.
- **Testability** — the classification table (§6) and every safety rule (§10) are exercised by exact-expected-output tests, including adversarial ones that mock the LLM to try to contradict the deterministic result.
- **Hallucination resistance** — the classification is computed from real counts by code; there is no generative step between the numbers and the state.
- **Human review** — Safety Rule 9 unconditionally guarantees the pipeline's output is never presented as final; a human always makes the operational call.

**Where an LLM is actually used:** exactly one place — Signal Analysis's own explanation sentence (§6, §18), and only for wording, never for the trend value itself. If the LLM is unreachable, misconfigured, or returns something adversarial, the classification and the safety verdict are provably unaffected (§10's `test_llm_contradiction_through_real_pipeline_cannot_change_gate_result`).

---

## 40. If the Jury Asks: "How Do You Prevent Wrong Information?"

- **Validated synthetic input** — `SimulationSourceSignal`'s own DB constraint makes "missing recorded as zero" structurally impossible (§5).
- **Deterministic numerical processing** — trend, correlation, and preliminary evidence are all fixed rules over real counts (§6, §8, §9).
- **Missing-data distinction** — preserved through every stage down to the completeness percentage (§22, §24).
- **Source disagreement** — surfaced explicitly (CONFLICTING), never resolved automatically or hidden (§8, §23).
- **Evidence qualification** — a fixed WEAK/MODERATE/STRONG lookup, never a fabricated confidence score (§9).
- **Independent safety gate** — nine rules, BLOCK-over-INSUFFICIENT-over-PASS precedence, statically verified to be LLM-free (§10, §11, §13).
- **No autonomous outbreak declaration** — two dedicated phrase-screening rules, tested against a real adversarial LLM response injected through the live pipeline (§13).
- **Human review** — unconditionally required on every single evaluation (§10 Rule 9, §14).
- **Isolation from operational data** — the simulation app cannot write to `Alert`/`CommunityReport`/`Investigation`/`Feedback`/`Patient` tables; verified by dedicated tests in every simulation test file (§36).
- **Tests** — 227 simulation-specific backend tests across 8 files (§48), covering every rule, every isolation boundary, and every cross-village negative case.

---

## What If the Input Data Is Wrong?

The simulation does not, and cannot, know whether a synthetic source's reported value reflects "reality" — there is no reality behind it; it is a seeded demonstration number, or (in What-If) an officer-supplied hypothetical one. What the system **can** and does detect:

| Detectable | Not detectable by this system |
|---|---|
| Malformed input (structurally invalid override values — rejected by `WhatIfInputSerializer`, §29) | Whether a *真实* external source is being truthful |
| Missing input (`reported=False`, §5, §22) | Whether a reported number reflects the real-world situation |
| Conflicting sources (§8, §23) | Which of two conflicting sources is "right" |
| Incomplete reporting (§24) | — |
| Invalid reporting period (Safety Rule 2, §10) | — |
| Duplicate records (Safety Rule 3, §10) | — |
| Insufficient history for an escalating claim (Safety Rule 4, §10) | — |

The critical distinction: **"data is invalid"** (malformed, missing, duplicated, out of period — all structurally detectable and safety-gated) is a different question from **"data is valid but may not reflect reality"** (a genuine report that happens to be wrong for reasons no software can know from the number alone). This system only ever claims the former kind of protection. It never claims to verify ground truth, which is exactly why every path terminates in mandatory human review (§14, §18) rather than an autonomous conclusion.

---

## 41. Current Limitations

Stated plainly, because the task requires honesty over marketing:

- **All data is synthetic.** Four seeded scenarios, one village (Kovilur), authored by `seed_demo.py` — not real epidemiological history.
- **Only two source types are actually populated** by the current seed data (`CHW`, `PHC`), though the `SourceKind` vocabulary defines five more (`PHARMACY`, `SCHOOL`, `WEATHER`, `LAB`, `RURALCARE_AGGREGATE`).
- **Only four of six defined `ScenarioType` values are seeded** — `WEAK_EVIDENCE` and `SOURCE_DISAGREEMENT` exist as enum choices but have no seeded demonstration scenario (source disagreement is instead demonstrated only inside the backend test suite).
- **No live external epidemiological integrations** — nothing here connects to a real health information system, laboratory feed, or weather service; `WEATHER`/`LAB` source types are structurally supported but never populated by any seeded data.
- **Limited historical depth** — every seeded scenario is 4–5 weeks; the 80%-completeness and 3-week-minimum thresholds (§10) were tuned specifically for that scale, not validated against months or years of real reporting.
- **Single-process real-time assumption** — `LiveSessionRunner`'s concurrency guard (`_RUNNERS`, §31) is an in-memory, per-process dict, consistent with the project's `InMemoryChannelLayer` setting; it does not scale to multiple backend processes without a shared lock.
- **This is decision-support, not surveillance.** Nothing in this document should be read as "real-time surveillance" or "outbreak prediction" — the correct framing, used throughout this document and enforced by the Safety Engine's own banned-phrase rules, is **community signal detection** and **early-warning decision support**.

---

## 42. Production vs. Simulation

| Capability | Current Simulation | Production Extension (future work — not implemented) |
|---|---|---|
| Data | Synthetic, seeded, 4 scenarios / 1 village | Real Health Worker assessments and community reports (already exists in the *operational* app, separately) |
| Source integrations | 2 populated source types (`CHW`, `PHC`) via seed data only | Live PHC/pharmacy/school/lab/weather feeds |
| Data quality baselines | Fixed thresholds tuned for 4–5 week demo timelines | Baselines derived from months/years of real reporting history |
| Real-time transport | Single-process `InMemoryChannelLayer`, one `LiveSessionRunner` per process | Redis/DB-backed channel layer + distributed lock for multi-process deployments |
| LLM usage | One optional wording call, env-gated, off by default | Same design, potentially more narrative surfaces, still wording-only |
| Monitoring scope | Single-village aggregates only (district-wide explicitly refused, §34) | District/state-level aggregation, if ever required |
| Governance | Simulation-only audit trail (`SimulationAgentRun`, `SimulationSafetyCheck`) | Same pattern already exists for the operational pipeline independently |
| Privacy | No patient-identifying field exists anywhere in the simulation schema | Operational app already has its own separate patient-privacy handling |

---

## 43. Complete Deterministic Rule Inventory

### Signal Rules (`orchestrator.py::_classify_trend`)
| ID | Rule | Input | Condition | Output |
|---|---|---|---|---|
| SIG-1 | No prior week | `previous is None` | always | NORMAL |
| SIG-2 | Zero-baseline sharp rise | `previous==0` | `change≥3` | SIGNAL_DETECTED |
| SIG-3 | Zero-baseline moderate rise | `previous==0` | `change≥2` | INCREASING |
| SIG-4 | Zero-baseline flat | `previous==0` | `change==0` | NORMAL |
| SIG-5 | Zero-baseline small rise | `previous==0` | `change==1` | STABLE |
| SIG-6 | Sharp relative+absolute rise | `previous>0` | `change_pct≥60 ∧ change≥3` | SIGNAL_DETECTED |
| SIG-7 | Moderate relative+absolute rise | `previous>0` | `change_pct≥25 ∧ change≥2` | INCREASING |
| SIG-8 | Clear drop | `previous>0` | `change_pct≤-20` | NORMAL |
| SIG-9 | Everything else | `previous>0` | default | STABLE |

### Correlation Rules (`orchestrator.py::_correlation`)
| ID | Rule | Input | Condition | Output |
|---|---|---|---|---|
| COR-1 | Not reported | `current_row.reported` | `False` | INSUFFICIENT |
| COR-2 | No usable prior | `previous_row` | missing/unreported/null value | INSUFFICIENT |
| COR-3 | Matching direction | source vs. primary direction | equal, neither FLAT | SUPPORTING |
| COR-4 | Flat movement | either direction | `FLAT` | INSUFFICIENT |
| COR-5 | Opposing direction | source vs. primary direction | opposite, neither FLAT | CONFLICTING |

### Evidence Rules (`intelligence.py::_evidence_strength`)
| ID | Rule | Input | Condition | Output |
|---|---|---|---|---|
| EVI-1 | Non-escalating or unsupported or outnumbered | trend, supporting, conflicting | `¬escalating ∨ supporting=0 ∨ conflicting>supporting` | WEAK |
| EVI-2 | Clean escalation | trend, supporting, conflicting | `escalating ∧ supporting>0 ∧ conflicting=0` | STRONG |
| EVI-3 | Everything else | — | default | MODERATE |

### Safety Rules (`safety/rules.py`) — see §10 for full detail
| ID | Rule name | Category |
|---|---|---|
| SAF-1 | village_scope_verified | Access-control |
| SAF-2 | reporting_period_validated | Validation |
| SAF-3 | duplicate_records_checked | Validation |
| SAF-4 | sufficient_historical_window | Validation |
| SAF-5 | source_relationships_evaluated | Validation |
| SAF-6 | missing_data_assessed | Data Quality |
| SAF-7 | no_individual_diagnosis_generated | Outbreak/diagnosis protection |
| SAF-8 | no_autonomous_outbreak_declaration | Outbreak/diagnosis protection |
| SAF-9 | human_review_required | Human-in-the-loop |
| SAF-AGG | `_aggregate` — BLOCK > INSUFFICIENT > PASS | Aggregation |
| SAF-FIN | `finalize_evidence_strength` — downgrade-only | Evidence finalization |

### Data Quality Rules (`intelligence.py::_compute_data_quality`)
| ID | Rule | Formula |
|---|---|---|
| DQ-1 | Per-source completeness | `reported_weeks / expected_weeks × 100` |
| DQ-2 | Overall completeness | `total_reported / (expected_weeks × source_count) × 100` |

### Investigation Rules (`investigation.py`)
| ID | Rule | Location |
|---|---|---|
| INV-1 | Checklist derived from session's actual sources + 6 fixed items | `checklist_items` |
| INV-2 | Auto-transition to READY_FOR_DECISION when checklist complete | `views.py::SimulationInvestigationView.patch` |
| INV-3 | `suggested_decision()` mapping (§28) | `investigation.py:208` |
| INV-4 | Decision blocked when safety gate = BLOCK | `views.py::SimulationInvestigationDecisionView.post` |

### Validation Rules (serializers)
| ID | Rule | Location |
|---|---|---|
| VAL-1 | What-If override: non-negative float or null | `WhatIfInputSerializer` |
| VAL-2 | Investigation notes: ≤20,000 chars | `InvestigationUpdateSerializer` |
| VAL-3 | Investigation decision: restricted to 7-value vocabulary | `InvestigationDecisionInputSerializer` |
| VAL-4 | Feedback: at least one field required on PATCH | `InvestigationFeedbackInputSerializer.validate` |

### Access-Control Rules
| ID | Rule | Location |
|---|---|---|
| AC-1 | Object-level village permission (scenario/session) | `permissions.py` |
| AC-2 | Service-layer village re-check | `services.py::officer_may_access_village` |
| AC-3 | Safety Rule 1 (village_scope_verified) | `safety/rules.py` |
| AC-4 | WebSocket 5-check authorization | `consumers.py::_load_authorized_session` |

### What-If Validation Rules
| ID | Rule | Location |
|---|---|---|
| WI-1 | Only real, currently-existing source types accepted | `what_if.py::WhatIfEngine.run` (allowlist against `real_sources`) |
| WI-2 | Session must have a current reporting week | `what_if.py` (`current_week < 1` → 400) |
| WI-3 | Rollback is unconditional | `transaction.set_rollback(True)`, always executed |

### Replay Rules
| ID | Rule | Location |
|---|---|---|
| RPL-1 | Week bounded to `[min_week, session.replay_position]` | `replay.py::build_replay_state` |
| RPL-2 | Never recomputes safety; reads the persisted row | `replay.py::_persisted_safety_for_week` |

### Monitoring Rules
| ID | Rule | Location |
|---|---|---|
| MON-1 | `limited_sample` below `MIN_SAMPLE_SIZE=5` | `monitoring.py::_ratio` |
| MON-2 | `is_what_if=False` filter on every evidence/safety aggregate | `monitoring.py::_real_results` |
| MON-3 | Per-source (not pairwise) relationship tally | `monitoring.py::_source_relationship_tally` |
| MON-4 | Decision alignment framed as alignment, never accuracy | `monitoring.py::_decision_alignment` |

---

## 44. Complete Data Lineage

```
SimulationScenario (village, scenario_type, version)
   ↓ get_template_session()
SimulationSession (health_officer=None — template)
   ↓ .events
SimulationEvent (week_number, source_signals JSON: categories/status_label/context)
   ↓ .per_source_signals
SimulationSourceSignal (source_type, value, reported)
   ↓ read by MultiAgentOrchestrator.run_pipeline() — real, officer-owned session's advance()
Agent Input (per-stage dicts, threaded stage-to-stage)
   ↓ MultiAgentOrchestrator.run_stage()
Agent Output (per-stage dicts)
   ↓ services.py::_create_agent_run
SimulationAgentRun (session, agent_name, status, input, output, duration_ms)
   ↓ (if evidence completed) SafetyEngine.evaluate_latest()
SimulationSafetyCheck × 9  +  SimulationResult (evidence_strength, gate_result, investigation_priority)
   ↓ simulation.intelligence.build_intelligence(session) — re-reads the SimulationAgentRun rows above
Intelligence payload {timeline, constellation, source_fusion, data_quality, explanation, safety}
   ↓ SimulationIntelligenceSerializer via GET .../intelligence/
UI (SimulationLab.tsx, InvestigationNotebook.tsx, SimulationMonitoring.tsx)
```

---

## 45. Simulation API Map

All routes prefixed `/api/` (`config/urls.py` includes `simulation.urls`). Every endpoint requires `IsHealthOfficer`; every session-scoped endpoint additionally requires `SessionBelongsToOfficerVillage` (or `IsScenarioInOfficerVillage` for scenario endpoints).

| Method | Endpoint | Purpose | Village scope | Side effects |
|---|---|---|---|---|
| GET | `/simulation/scenarios/` | List active scenarios for the officer's village | Queryset-filtered | None |
| GET | `/simulation/scenarios/<pk>/` | One scenario's detail | Object permission, 403 on mismatch | None |
| POST | `/simulation/sessions/` | Start a new officer-owned session | `IsScenarioInOfficerVillage` + service re-check | Creates 1 `SimulationSession` |
| POST | `/simulation/sessions/<pk>/advance/` | Advance one week, run the pipeline | `SessionBelongsToOfficerVillage` + service re-check | Creates up to 5 `SimulationAgentRun`, up to 9 `SimulationSafetyCheck`, 1 `SimulationResult` |
| GET | `/simulation/sessions/<pk>/intelligence/` | Full aggregated intelligence + safety + recommendation | Two-layer check | None (read-only, computed on read) |
| GET | `/simulation/sessions/<pk>/safety/` | Safety gate only | Two-layer check + Rule 1 | None |
| GET | `/simulation/sessions/<pk>/replay/?week=N` | Read-only historical view | Two-layer check | None |
| POST | `/simulation/sessions/<pk>/what-if/` | Hypothetical rerun | Two-layer check + engine re-check | None (transaction always rolled back) |
| GET/PATCH | `/simulation/sessions/<pk>/investigation/` | Investigation workspace | Two-layer check | GET: get-or-create 1 `SimulationInvestigation`. PATCH: updates notes/checklist |
| POST | `/simulation/sessions/<pk>/investigation/decision/` | Record the officer's decision | Two-layer check + fresh safety re-check (403 on BLOCK) | Updates the investigation's `decision`/`decided_by`/`decided_at` |
| POST | `/simulation/sessions/<pk>/investigation/observations/` | Add a simulated field observation | Two-layer check | Appends to `observations` JSON |
| GET | `/simulation/sessions/<pk>/investigation/report/` | PDF export | Two-layer check | Appends one `report_exported` activity entry |
| GET/PATCH | `/simulation/sessions/<pk>/investigation/feedback/` | Officer-experience feedback | Two-layer check | GET/PATCH-creates 1 `SimulationFeedback` |
| GET | `/simulation/monitoring/` | Village-wide aggregated metrics | `scoped_village_id`; district-wide → 400 | None |
| WS | `/ws/simulation/sessions/<session_id>/?token=<jwt>` | Live streaming | 5-check `connect()` | Drives the same `advance()` path per week |

---

## 46. Simulation Database Model Map

| Model | Purpose | Key fields | Relationships | Village scope | Simulation/Operational |
|---|---|---|---|---|---|
| `SimulationScenario` | Reusable synthetic template | `name`, `scenario_type`, `version`, `is_active` | has many `SimulationSession` | Own `village` FK | Simulation |
| `SimulationSession` | One run of a scenario | `status`, `replay_position`, `health_officer` (nullable) | FK `scenario`; has many `events`, `agent_runs`, `safety_checks`, `results`, `investigations`, `feedback_entries` | Own `village` FK | Simulation |
| `SimulationEvent` | One simulated week | `week_number`, `source_signals` JSON, `is_synthetic` | FK `session`; has many `per_source_signals` | Own `village` FK | Simulation |
| `SimulationSourceSignal` | One source's value for one week | `source_type`, `value`, `reported` | FK `event` | Own `village` FK | Simulation |
| `SimulationAgentRun` | One persisted stage execution | `agent_name`, `status`, `input`, `output`, `duration_ms` | FK `session` | Own `village` FK | Simulation |
| `SimulationSafetyCheck` | One persisted rule result | `rule_name`, `result`, `reason` | FK `session` | Own `village` FK | Simulation |
| `SimulationResult` | Finalized week outcome | `evidence_strength`, `gate_result`, `investigation_priority`, `is_what_if` | FK `session` | Own `village` FK | Simulation |
| `SimulationInvestigation` | Officer's investigation workspace | `status`, `checklist`, `observations`, `activity_history`, `decision`, `decided_by`, `decided_at` | FK `session`, FK `decided_by` (User) | Own `village` FK | Simulation |
| `SimulationFeedback` | Officer-experience evaluation | `usefulness`, `evidence_sufficiency`, `recommendation_helpful`, `additional_verification_required`, `comment` | FK `investigation`, FK `session`, FK `officer` | Own `village` FK | Simulation |

All nine models share `SimulationVillageScoped` (`village = ForeignKey(core.Village, on_delete=PROTECT)`), and reuse the existing `core.Village`/`User` models rather than defining parallel ones.

---

## 47. Simulation Frontend Map

| Piece | File | Role |
|---|---|---|
| Page — Simulation Lab | `pages/officer/SimulationLab.tsx` | Scenario selector, left control panel (advance/live/replay/officer investigation input), center pipeline+intelligence visualization, right "Officer Intelligence & Response" panel |
| Page — Investigation Notebook | `pages/officer/InvestigationNotebook.tsx` | Overview → Timeline → Evidence → Contradictions → Community Context → Field Notes → Checklist → Decision → Recommendation → Feedback |
| Page — Intelligence Monitoring | `pages/officer/SimulationMonitoring.tsx` | Village-scoped aggregate dashboard, reads `GET /simulation/monitoring/` |
| Store | `store/simulation.ts` | Single Zustand store — session/pipeline/intelligence/replay/what-if/live/investigation/feedback/monitoring state, one action per API call, no client-side computation of trend/evidence/safety |
| API client | `services/api.ts` | `api.get/post/patch` (JWT bearer), `buildSimulationSocketUrl()` (JWT-over-query-param for WS) |
| Types | `types/index.ts` | One TypeScript interface per backend payload shape (`SimulationIntelligence`, `SimulationWhatIfResult`, `SimulationReplayState`, `SimulationInvestigationState`, `SimulationMonitoringReport`, etc.) — mirrors the backend contract, computes nothing |
| Routes | `App.tsx` | `/officer/simulation`, `/officer/simulation/investigation/:sessionId`, `/officer/simulation/monitoring` — same `PortalLayout`, `wide` + `hideFooterDisclaimer` variant |

**Where information comes from, structurally:** every number/label shown anywhere in these three pages traces back to a single store fetch (`loadIntelligence`, `stepReplay`, `runWhatIf`, `loadInvestigation`, `loadFeedback`, `loadMonitoring`, or a live WebSocket event) — the frontend never independently computes a trend, evidence strength, safety verdict, or recommendation; every such value is a direct read of a backend response field.

---

## 48. Verification and Test Coverage

**227 simulation-specific backend tests**, collected and passing at the time of writing:

| File | Count | Focus |
|---|---|---|
| `tests/test_simulation.py` | 66 | Models, village scoping, seed data, session lifecycle, orchestrator execution order, intelligence payload structure |
| `tests/test_simulation_safety.py` | 44 | All 9 safety rules individually, aggregation, evidence-strength finalization, LLM independence (static + adversarial), isolation, cross-village |
| `tests/test_simulation_replay_whatif.py` | 35 | Replay bounds/immutability, What-If overrides/isolation/validation, LLM-failure independence |
| `tests/test_simulation_investigation.py` | 22 | Investigation lifecycle, checklist, decision recording, Safety-BLOCK enforcement, PDF export, isolation |
| `tests/test_simulation_live.py` | 20 | WebSocket auth (5 rejection cases), event ordering, pause/resume/stop, disconnect ownership, isolation |
| `tests/test_simulation_monitoring.py` | 15 | Village-scoped aggregation correctness, ratio edge cases, What-If/Replay exclusion, banned wording |
| `tests/test_simulation_feedback.py` | 13 | Feedback CRUD, attribution, never-modifies-decision/safety guarantees |
| `tests/test_simulation_signal_alert.py` | 12 | Signal-detection progression, recommendation variation, Safety-BLOCK override, Replay/What-If consistency |

**What is explicitly, directly tested (not merely implied):**
- Deterministic rules: `test_finalize_evidence_strength_downgrade_table`, `test_aggregate_rule_is_block_over_insufficient_over_pass`, full correlation/evidence classification coverage in `test_simulation.py`.
- Every one of the 9 safety rules, individually, with both a PASS and a triggering case (§10).
- Cross-village access: `test_cross_village_negative_authorization`, `test_unauthorized_village_api_returns_403`, `test_connect_rejected_cross_village_officer_*`, and equivalents in every other test file.
- Missing data: `test_reported_zero_differs_from_not_reported`, `test_timeline_shows_null_not_zero_for_a_genuinely_missing_category`, `test_low_completeness_is_insufficient_and_downgrades_strong_evidence`.
- Source disagreement: `test_constellation_marks_disagreeing_source_conflicting`, `test_conflicting_evidence_does_not_force_a_false_block`.
- LLM failure and adversarial LLM output: `test_trend_unaffected_by_llm_unavailable`, `test_trend_unaffected_by_llm_contradiction`, `test_llm_contradiction_through_real_pipeline_cannot_change_gate_result`, `test_malicious_llm_output_is_still_blocked_over_the_live_path`, `test_what_if_llm_failure_does_not_alter_deterministic_trend`.
- Isolation: at least one dedicated operational-isolation test per feature area (§36).
- What-If: 20 dedicated tests including `test_what_if_leaves_original_rows_unchanged`, `test_what_if_safety_result_can_diverge_from_original`, `test_what_if_preserves_missing_vs_reported_zero`.
- Replay: 12 dedicated tests including bounds enforcement and `test_replay_direct_engine_rejects_out_of_range_with_typed_exception`.
- Investigation: `test_safety_block_prevents_decision_recording`, `test_decision_ignores_client_supplied_officer_id`.
- Feedback: `test_feedback_never_modifies_investigation_decision`, `test_feedback_never_modifies_safety_or_evidence`.
- Monitoring: `test_what_if_does_not_contaminate_monitoring_metrics`, `test_replay_does_not_change_monitoring_metrics`, `test_no_banned_wording_in_monitoring_payload`.

Test run confirmed passing on 2026-09-13 (`pytest tests/test_simulation*.py -q`): **227 passed, 0 failed.**

---

## 49. Architectural Diagrams

### 1. Overall architecture
```
Seed data (seed_demo.py)
        │
        ▼
Simulation DB tables (Scenario/Session/Event/SourceSignal)
        │
        ▼
┌───────────────────────────────────────────────┐
│  MultiAgentOrchestrator (4 stages) + SafetyEngine (1 stage)  │
└───────────────────────────────────────────────┘
        │
        ▼
SimulationAgentRun / SimulationSafetyCheck / SimulationResult (persisted)
        │
        ▼
simulation.intelligence.build_intelligence  (re-reads, never recomputes)
        │
        ▼
REST API  ──────────────┬──────────────  WebSocket (live only)
        │                                        │
        ▼                                        ▼
SimulationLab.tsx / InvestigationNotebook.tsx / SimulationMonitoring.tsx (Zustand store)
```

### 2. Agent pipeline
```
SimulationEvent + SimulationSourceSignal
        │
        ▼
[1] Ingestion ──► [2] Signal Analysis ──► [3] Correlation ──► [4] Evidence ──► [5] Safety
        (deterministic)   (deterministic trend;    (deterministic)   (deterministic,     (deterministic,
                           optional LLM wording)                      preliminary only)    9 rules, no LLM)
        │                       │                     │                    │                    │
        └───────────────────────┴─────────────────────┴────────────────────┴────────────────────┘
                                     one SimulationAgentRun row per stage
```

### 3. Safety gate
```
9 rules run in fixed order
  Rule1 Rule2 Rule3 Rule4 Rule5 Rule6 Rule7 Rule8 Rule9
   │     │     │     │     │     │     │     │     │
   ▼     ▼     ▼     ▼     ▼     ▼     ▼     ▼     ▼
 {PASS|BLOCK|INSUFFICIENT} per rule
                    │
                    ▼
        _aggregate(): BLOCK > INSUFFICIENT > PASS
                    │
                    ▼
        finalize_evidence_strength(preliminary, gate_result)   (downgrade only)
                    │
                    ▼
        {checks, gate_result, evidence_strength, human_review_required: true}
```

### 4. Data lineage
See §44 (full lineage diagram already provided there).

### 5. Human-in-the-loop
```
Signal Analysis → Correlation → Evidence → Safety Engine
                                                │
                                                ▼
                            suggested_decision()  (non-binding, always recomputed)
                                                │
                                                ▼
                              Health Officer opens Investigation Notebook
                                                │
                                                ▼
                    Officer reviews checklist / evidence / contradictions
                                                │
                                                ▼
                POST .../investigation/decision/  ← BLOCKED if safety = BLOCK
                                                │
                                                ▼
                        SimulationInvestigation.decision  (human-authored, final)
```

### 6. What-If
```
Officer overrides (source_type → value|null)
        │
        ▼
transaction.atomic()
  ├─ throwaway SimulationSession/Event/SourceSignal rows created
  ├─ MultiAgentOrchestrator.run_pipeline()  (same code as live)
  ├─ SafetyEngine.evaluate(..., intelligence_override=hypothetical)
  └─ transaction.set_rollback(True)   ← ALWAYS, unconditionally
        │
        ▼
{original (from persisted row), hypothetical (fresh), changed_sources}
        │
        ▼
Real session: byte-for-byte unchanged (verified by re-fetch)
```

### 7. Replay
```
GET .../replay/?week=N
        │
        ▼
bound N to [min_week, session.replay_position]
        │
        ▼
build_intelligence(session, as_of_week=N)   ← reads persisted SimulationAgentRun rows only
        │
        ▼
_persisted_safety_for_week(session, N)      ← reads persisted safety row only, no recompute
        │
        ▼
{week, min_week, max_week, is_first, is_last, intelligence}
        (no row created, modified, or deleted anywhere in this path)
```

### 8. Live streaming
```
WebSocket connect (?token=JWT)
        │
        ▼
JWTAuthMiddleware → scope["user"]
        │
        ▼
SimulationSessionConsumer.connect()  — 5-check authorization
        │
        ▼
group_add(simulation_session_<id>)
        │
        ▼
{action: "start"} → LiveSessionRunner.run()
        │
        ├─ database_sync_to_async(SimulationEngine.advance(...))   ← fully commits first
        │        │
        │        ▼
        │   collects plain-dict events (never sent from inside the sync call)
        │
        ▼
drain events with STAGE_PACING_SECONDS / WEEK_PACING_SECONDS pacing → group_send → all connected tabs
```

### 9. Operational isolation
```
simulation/  (own app, own tables)              operational apps
─────────────────────────────────               ─────────────────────────
SimulationScenario                               community.CommunityReport
SimulationSession        ✕  no import path  ✕    alerts.Alert
SimulationEvent          ✕  no write path   ✕    alerts.Investigation
SimulationSourceSignal                           alerts.Feedback
SimulationAgentRun        (read-only: Alert.Severity choices reused for a label)
SimulationSafetyCheck                            core.Patient
SimulationResult                                 assessments.Assessment
SimulationInvestigation
SimulationFeedback
```

---

## 50. Code References (quick index)

| Concept | File | Key names |
|---|---|---|
| Stage order, trend classification | `backend/simulation/orchestrator.py` | `STAGE_ORDER`, `_classify_trend`, `MultiAgentOrchestrator` |
| Safety rules | `backend/simulation/safety/rules.py` | `RULES`, `RULE_ORDER`, `rule_1_…` through `rule_9_…` |
| Safety aggregation | `backend/simulation/safety/engine.py` | `SafetyEngine`, `_aggregate`, `finalize_evidence_strength` |
| Intelligence assembly | `backend/simulation/intelligence.py` | `build_intelligence`, `_evidence_strength`, `_compute_data_quality` |
| Session lifecycle | `backend/simulation/services.py` | `SimulationEngine.start/advance`, `_persist_agent_runs` |
| Investigation logic | `backend/simulation/investigation.py` | `suggested_decision`, `checklist_items`, `build_investigation_report_pdf` |
| Monitoring aggregation | `backend/simulation/monitoring.py` | `build_monitoring_report`, `_decision_alignment` |
| What-If | `backend/simulation/what_if.py` | `WhatIfEngine.run` |
| Replay | `backend/simulation/replay.py` | `build_replay_state`, `_persisted_safety_for_week` |
| Live streaming | `backend/simulation/live_runner.py`, `consumers.py`, `ws_auth.py` | `LiveSessionRunner`, `SimulationSessionConsumer`, `JWTAuthMiddleware` |
| Village scoping | `backend/simulation/permissions.py`, `services.py` | `SessionBelongsToOfficerVillage`, `officer_may_access_village` |
| LLM client | `backend/agents/llm/client.py` | `LLMClient`, `get_llm_client`, `LLMUnavailable` |
| Seed data | `backend/core/management/commands/seed_demo.py` | `_seed_simulation_scenarios` |
| Frontend store | `frontend/src/store/simulation.ts` | `useSimulationStore` |
| Frontend pages | `frontend/src/pages/officer/SimulationLab.tsx`, `InvestigationNotebook.tsx`, `SimulationMonitoring.tsx` | — |

---

## 51. Implementation Verification Matrix

| Feature | Documented | Actually Implemented | Source |
|---|---|---|---|
| Signal Detection (4-state deterministic) | Yes | Yes | `orchestrator.py::_classify_trend`, verified live against all 4 seeded scenarios |
| Multi-Agent Pipeline (5 fixed stages) | Yes | Yes | `orchestrator.py::MultiAgentOrchestrator`, `STAGE_ORDER` |
| Correlation (SUPPORTING/CONFLICTING/INSUFFICIENT) | Yes | Yes | `orchestrator.py::_correlation`, verified live |
| Evidence (WEAK/MODERATE/STRONG lookup) | Yes | Yes | `intelligence.py::_evidence_strength` |
| Safety Engine (9 rules, BLOCK>INSUFFICIENT>PASS) | Yes | Yes | `safety/rules.py`, `safety/engine.py`, 44 dedicated tests |
| LLM used only for Signal Analysis wording | Yes | Yes | `orchestrator.py:178`, confirmed sole LLM usage by repo-wide grep |
| No LLM under `simulation/safety/` | Yes | Yes | Statically enforced by `test_no_llm_import_under_safety_package` |
| Replay (read-only) | Yes | Yes | `replay.py::build_replay_state` |
| What-If (isolated, rollback-guaranteed) | Yes | Yes | `what_if.py::WhatIfEngine.run`, verified live |
| Live (WebSocket, same pipeline) | Yes | Yes | `live_runner.py`, `consumers.py`, 20 dedicated tests |
| Investigation (one per session, human decision) | Yes | Yes | `models.py::SimulationInvestigation`, `views.py` |
| Feedback (never affects safety/evidence/decision) | Yes | Yes | `models.py::SimulationFeedback`, `monitoring.py` docstring + tests |
| Monitoring (village-scoped, read-only) | Yes | Yes | `monitoring.py::build_monitoring_report` |
| `WEAK_EVIDENCE` / `SOURCE_DISAGREEMENT` seeded scenarios | Yes | **No — enum values exist, not seeded** | `models.py::ScenarioType`, absent from `seed_demo.py::_seed_simulation_scenarios` |
| District-wide Monitoring | Yes | **No — explicitly refused (HTTP 400)** | `views.py::SimulationMonitoringView.get` |

---

# Jury Quick Reference

**Where does the data come from?** Seeded, synthetic `SimulationEvent`/`SimulationSourceSignal` rows, authored by `seed_demo.py`, for one village and four scenarios.

**Is the data real?** No. Explicitly synthetic throughout — labeled "SYNTHETIC DEMO DATA" in the UI, and no code path connects it to any real patient, worker, or community-report data.

**How is the signal detected?** A deterministic classification comparing this week's primary-category count to the previous week's, using a combined relative (%) and absolute (count) threshold — `_classify_trend` in `orchestrator.py`.

**What are the deterministic rules?** Signal classification (9 branches), source correlation (5 branches), evidence-strength lookup (3 outcomes), and the Safety Engine's 9 independent rules — the full inventory is in §43.

**Why not use an LLM for detection?** Because this is a safety-sensitive numerical classification that must be reproducible, auditable, and testable — properties an LLM cannot structurally guarantee. See §7 and §19.

**Where is the LLM used?** Exactly one place: phrasing the Signal Analysis explanation sentence, after the trend is already computed, with a deterministic fallback always available. Disabled by default.

**What does the Correlation Agent do?** Compares each reporting source's own week-over-week direction to the primary signal's direction and classifies it SUPPORTING, CONFLICTING, or INSUFFICIENT.

**What does the Evidence Agent do?** Assembles a preliminary, unscored packet of the upstream outputs; the actual WEAK/MODERATE/STRONG strength is a separate fixed lookup one layer up.

**What does the Safety Engine do?** Runs 9 independent, deterministic rules — authorization, reporting-period validity, duplicate detection, historical sufficiency, relationship validity, data completeness, and two banned-phrase screens — and aggregates them with BLOCK taking precedence over INSUFFICIENT over PASS. Independently verified to import no LLM.

**What happens when sources disagree?** They are marked CONFLICTING and shown explicitly — this never by itself blocks or downgrades the result (Safety Rule 5 explicitly refuses to manufacture a false failure from disagreement alone), but it can prevent evidence from reaching STRONG and changes the officer recommendation to "verify with PHC."

**What happens when data is missing?** Recorded as `reported=False`, never coerced to zero; classified INSUFFICIENT in correlation; lowers overall completeness, which the Safety Engine independently gates at 80%.

**Can the system declare an outbreak?** No — the word never appears in any system-generated output except inside the two banned-phrase detection lists and the tests that deliberately inject it; any occurrence forces `gate_result=BLOCK`.

**Can it diagnose a patient?** No — same mechanism (Safety Rule 7), and structurally there is no patient-identifying field anywhere in the simulation schema.

**Can it change operational alerts?** No — the simulation app never imports or writes to `alerts.Alert`, `community.CommunityReport`, the operational `Investigation`, or `Feedback` models. Verified by a dedicated isolation test in every simulation test file.

**What happens in What-If?** The officer overrides this week's source values; the real pipeline and Safety Engine rerun against a throwaway, transaction-rolled-back copy; the real session is never touched; the category totals (and therefore the trend) can never differ from the original.

**What happens in Replay?** A pure, read-only re-display of an already-computed and already-persisted week — no agent, LLM, or Safety Engine call happens again.

**What happens in Live Simulation?** The same `advance()` call the REST endpoint uses, run automatically week-by-week with pacing, streamed over a session-specific, JWT-authenticated WebSocket group — never a second simulation engine.

**Who makes the final decision?** The Health Officer, via the Investigation Notebook — the system's `suggested_decision()` is a non-binding, always-recomputed suggestion, never persisted as the actual decision.

**How is wrong information prevented?** Structural database constraints (missing≠zero), deterministic classification, an independent multi-rule safety gate, mandatory human review on every evaluation, and isolation from operational data — see §21 and §40 for the full list.

**How is village data protected?** Four independent layers per request path (object permission, service-layer re-check, Safety Rule 1, and — for WebSocket — the consumer's own 5-check authorization), all deriving village/identity from the authenticated server session, never from client input.

**How is the system tested?** 227 dedicated backend tests across 8 files, covering every deterministic rule, every safety rule individually, cross-village negative cases, missing/conflicting data, adversarial LLM output, and operational-data isolation for every feature area.

---

## Final Confirmation

This document was produced by directly reading the current source of every file it cites — `backend/simulation/*.py` (models, orchestrator, safety engine and rules, intelligence, services, investigation, monitoring, what_if, replay, live_runner, consumers, ws_auth, permissions, serializers, views, urls), `backend/agents/llm/client.py`, `backend/config/settings.py`, `backend/core/management/commands/seed_demo.py`, the full simulation backend test suite (227 tests, collected and confirmed passing), and the frontend store/types/pages — plus live verification against the running backend for every scenario's real computed trend, evidence strength, and safety result (not the seed's cosmetic `status_label`). No rule, threshold, agent, or behavior described here was invented; where the codebase defines something not yet used (the two unseeded `ScenarioType` values), that is stated explicitly rather than described as active.
