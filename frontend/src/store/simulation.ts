import { create } from 'zustand'

import type { SimulationScenario } from '@/types'

/**
 * Simulation Lab client state — Phase 2 only.
 *
 * `availableScenarios` is filled from the API response by the page (via the
 * existing `useAsync` loading/error pattern, same as every other page in
 * the app — see the Phase 1 audit's frontend-state-management finding).
 * `selectedScenario` is pure click-to-highlight UI state: selecting a card
 * never creates a session, advances a week, or calls an agent. `sessionId`
 * stays `null` throughout Phase 2 — it exists now only so Phase 3 can start
 * setting it without another store shape change.
 */
interface SimulationState {
  availableScenarios: SimulationScenario[]
  selectedScenario: SimulationScenario | null
  sessionId: number | null
  loading: boolean
  error: string | null
  setScenarios: (scenarios: SimulationScenario[]) => void
  selectScenario: (scenario: SimulationScenario | null) => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void
}

export const useSimulationStore = create<SimulationState>((set) => ({
  availableScenarios: [],
  selectedScenario: null,
  sessionId: null,
  loading: false,
  error: null,

  setScenarios: (scenarios) => set({ availableScenarios: scenarios }),
  selectScenario: (scenario) => set({ selectedScenario: scenario }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
}))
