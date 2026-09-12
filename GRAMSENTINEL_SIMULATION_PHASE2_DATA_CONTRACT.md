# GramSentinel Intelligence Simulator — Phase 2 Data Contract

Companion to `GRAMSENTINEL_SIMULATION_PHASE1_AUDIT.md`. Documents the persistent schema created in Phase 2, per model.

| Model | Purpose | Key fields | Village scope | Relationship | Created | Populated |
|---|---|---|---|---|---|---|
| `SimulationScenario` | Reusable, database-backed synthetic demonstration template | `name`, `scenario_type`, `description`, `is_active`, `version` | Own `village` FK | Parent of `SimulationSession` | Phase 2 | Phase 2 (seed) |
| `SimulationSession` | One run/template of a scenario | `scenario` FK, `health_officer` FK (nullable), `status`, `replay_position` | Own `village` FK, denormalized from `scenario.village` | Child of Scenario; parent of Event/AgentRun/SafetyCheck/Result/Investigation | Phase 2 | Phase 2 (seed creates one unexecuted template session per scenario; `health_officer=None`) — real officer-owned sessions from Phase 3 |
| `SimulationEvent` | One synthetic reporting week | `session` FK, `week_number`, `source_signals` (JSON), `is_synthetic` | Own `village` FK | Child of Session; parent of SourceSignal | Phase 2 | Phase 2 (seed) |
| `SimulationSourceSignal` | One source's value (or absence) for one week | `event` FK, `source_type` (reuses `SourceKind`), `value`, `reported` | Own `village` FK | Child of Event | Phase 2 | Phase 2 (seed) |
| `SimulationAgentRun` | One simulated agent invocation | `session` FK, `agent_name`, `status`, `input`/`output` (JSON), `started_at`/`ended_at` | Own `village` FK | Child of Session | Phase 2 | **Phase 4** |
| `SimulationSafetyCheck` | One simulated deterministic-rule result | `session` FK, `rule_name`, `result`, `reason` | Own `village` FK | Child of Session | Phase 2 | **Phase 6** |
| `SimulationResult` | Evidence/prioritisation outcome | `session` FK, `evidence_strength`, `investigation_priority` (reuses `Alert.Severity`), `is_what_if` | Own `village` FK | Child of Session | Phase 2 | **Phase 5/7** |
| `SimulationInvestigation` | Simulated officer decision | `session` FK, `officer_notes`, `decision` (reuses `Feedback.Outcome`), `decided_at`, `is_simulation=True` | Own `village` FK | Child of Session | Phase 2 | **Phase 9** |

## `SimulationEvent.source_signals` JSON contract

```json
{
  "categories": {"FEVER": 8, "RESPIRATORY": 3, "HEADACHE": 2},
  "status_label": "SIGNAL_DETECTED"
}
```

- `categories` — reported-case counts for the week, keyed by an uppercase label. Real `SignalCategory` values (`FEVER`, `RESPIRATORY`, ...) are used where one exists; a label with no real counterpart (`HEADACHE`) is simulation-only and must never be presented as a real community-report category.
- `status_label` — a plain narrative marker (`NORMAL`/`STABLE`/`INCREASING`/`SIGNAL_DETECTED`/`INSUFFICIENT_DATA`), authored by the seed as scenario narration only — **not** computed by any signal-analysis logic. This JSON is a denormalized weekly *summary*; the authoritative "missing ≠ zero" record lives in the child `SimulationSourceSignal` rows.

## Village-scoping pattern

Every model above inherits from `simulation.models.SimulationVillageScoped`, an abstract base contributing one field: `village = models.ForeignKey("core.Village", on_delete=models.PROTECT)`. This is structural, not optional — a new simulation model cannot be added without a village FK unless it deliberately opts out of the shared base.
