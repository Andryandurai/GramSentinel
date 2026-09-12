import { useEffect } from 'react'

import { Card, Empty, ErrorNote, Loading } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import { useSimulationStore } from '@/store/simulation'
import { useAuth } from '@/store/auth'
import type { SimulationScenario } from '@/types'

/**
 * Reads the authenticated officer's own village from the existing auth
 * store (`useAuth().user`, populated at login/`/auth/me/` exactly like the
 * rest of the app) — never a second village state, never a value the user
 * can change. There is deliberately no dropdown, no selector, and no
 * frontend-supplied village id anywhere on this page: the backend resolves
 * and enforces the officer's village independently (see
 * `simulation.permissions.IsScenarioInOfficerVillage`), this banner is a
 * read-only reflection of that same server-side fact.
 */
function CurrentScopeBanner() {
  const user = useAuth((state) => state.user)

  return (
    <div className="rounded-lg border border-sentinel-200 bg-sentinel-50 px-4 py-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-sentinel-700">
        Current operational scope
      </div>
      <p className="text-lg font-semibold text-sentinel-900 mt-0.5">
        {user?.village_name ?? 'No village assigned'}
      </p>
      <p className="text-xs text-sentinel-800 mt-1">
        Fixed to your own assigned area. There is no option to switch village
        here — the same server-side scoping used everywhere else in your
        portal applies to the Simulation Lab.
      </p>
    </div>
  )
}

function ScenarioCard({
  scenario,
  selected,
  onSelect,
}: {
  scenario: SimulationScenario
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`w-full rounded-lg border p-4 text-left transition-colors ${
        selected
          ? 'border-sentinel-500 bg-sentinel-50'
          : 'border-ink-200 bg-white hover:bg-ink-50'
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-ink-800">
          {scenario.name}
        </span>
        <span className="pill bg-ink-100 text-ink-600">
          {scenario.scenario_type_display}
        </span>
        <span className="ml-auto pill bg-amber-100 text-amber-800">
          Coming soon
        </span>
      </div>
      <p className="text-sm text-ink-600 mt-2 leading-relaxed">
        {scenario.description}
      </p>
      {selected && (
        <p className="text-xs text-sentinel-700 mt-3 border-t border-sentinel-200 pt-2">
          Selected. Nothing has run — this scenario does not execute yet.
        </p>
      )}
    </button>
  )
}

function ScenarioListPanel({
  scenarios,
  selectedId,
  onSelect,
}: {
  scenarios: SimulationScenario[]
  selectedId: number | null
  onSelect: (scenario: SimulationScenario) => void
}) {
  if (scenarios.length === 0) {
    return (
      <Empty>No simulation scenarios are available for your area yet.</Empty>
    )
  }

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {scenarios.map((scenario) => (
        <ScenarioCard
          key={scenario.id}
          scenario={scenario}
          selected={scenario.id === selectedId}
          onSelect={() => onSelect(scenario)}
        />
      ))}
    </div>
  )
}

export default function SimulationLabPage() {
  const { data, loading, error, reload } = useAsync<SimulationScenario[]>(() =>
    api.get('/simulation/scenarios/'),
  )
  const { availableScenarios, selectedScenario, setScenarios, selectScenario } =
    useSimulationStore()

  useEffect(() => {
    if (data) setScenarios(data)
  }, [data, setScenarios])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">
          Simulation Lab
        </h1>
        <p className="text-sm text-ink-600 mt-0.5">
          GramSentinel Intelligence Simulator — synthetic demonstration
          scenarios for exploring how the community intelligence pipeline
          works, without touching any real operational data.
        </p>
      </div>

      <CurrentScopeBanner />

      <Card title={`Scenarios (${availableScenarios.length})`}>
        {loading && !data ? (
          <Loading label="Loading simulation scenarios…" />
        ) : error && !data ? (
          <ErrorNote message={error} onRetry={reload} />
        ) : (
          <ScenarioListPanel
            scenarios={availableScenarios}
            selectedId={selectedScenario?.id ?? null}
            onSelect={(scenario) =>
              selectScenario(
                selectedScenario?.id === scenario.id ? null : scenario,
              )
            }
          />
        )}
        <p className="mt-4 border-t border-ink-200 pt-3 text-xs text-ink-400">
          All scenario data shown here is synthetic and stored separately
          from operational records. Selecting a scenario only displays its
          description — running a scenario is not yet available.
        </p>
      </Card>
    </div>
  )
}
