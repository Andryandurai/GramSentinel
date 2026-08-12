import type { AgentTraceEntry } from '@/types'

const LAYER_LABEL: Record<string, string> = {
  RURALCARE: 'Individual',
  GRAMSENTINEL: 'Community',
  CROSS_LEVEL: 'Cross-level',
}

const LAYER_DOT: Record<string, string> = {
  RURALCARE: 'bg-care-500',
  GRAMSENTINEL: 'bg-sentinel-500',
  CROSS_LEVEL: 'bg-violet-500',
}

/**
 * How the assessment was processed, in the order it happened.
 *
 * Each row is one real agent invocation — the name, purpose and result all
 * come from that agent's own recorded output. What is deliberately *not* here
 * is the raw output payload: a health worker has no use for a JSON dump, and
 * showing one made the screen look like a debug console.
 */
export function AgentTrace({ trace }: { trace: AgentTraceEntry[] }) {
  if (!trace?.length) {
    return (
      <p className="text-sm text-ink-400">
        No processing steps were recorded for this assessment.
      </p>
    )
  }

  const safetyStep = trace.find((entry) => entry.stage === 'SAFETY_VERIFICATION')

  return (
    <div>
      <ol className="relative">
        {trace.map((entry, index) => {
          const isLast = index === trace.length - 1
          const failed = entry.status !== 'OK'
          const isSafety = entry.stage === 'SAFETY_VERIFICATION'

          return (
            <li key={entry.sequence} className="relative flex gap-3 pb-4 last:pb-0">
              {/* Connector line between steps */}
              {!isLast && (
                <span
                  className="absolute left-[11px] top-6 bottom-0 w-px bg-ink-200"
                  aria-hidden="true"
                />
              )}

              <span
                className={`relative z-10 mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${
                  failed
                    ? 'bg-red-100 text-red-700'
                    : isSafety
                      ? 'bg-sentinel-100 text-sentinel-700'
                      : 'bg-care-100 text-care-700'
                }`}
                aria-hidden="true"
              >
                {failed ? (
                  <span className="text-xs font-bold">!</span>
                ) : (
                  <svg
                    viewBox="0 0 20 20"
                    className="h-3.5 w-3.5"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.5"
                  >
                    <path
                      d="m5 10 3.5 3.5L15 7"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                )}
              </span>

              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="text-sm font-medium text-ink-800">
                    {entry.display_name || entry.agent}
                  </span>
                  <span className="inline-flex items-center gap-1 text-[11px] text-ink-400">
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${
                        LAYER_DOT[entry.layer] ?? 'bg-ink-400'
                      }`}
                    />
                    {LAYER_LABEL[entry.layer] ?? entry.layer}
                  </span>
                  {isSafety && (
                    <span className="pill bg-sentinel-100 text-sentinel-700">
                      deterministic
                    </span>
                  )}
                </div>

                {entry.purpose && (
                  <p className="text-xs text-ink-600 mt-0.5">{entry.purpose}</p>
                )}

                {entry.result_summary && (
                  <p
                    className={`text-sm mt-1 ${
                      failed ? 'text-red-700' : 'text-ink-800'
                    }`}
                  >
                    {entry.result_summary}
                  </p>
                )}
              </div>
            </li>
          )
        })}
      </ol>

      <p className="mt-3 border-t border-ink-200 pt-3 text-xs text-ink-400">
        {trace.length} steps ran in sequence, each passing its result to the
        next.
        {safetyStep
          ? ' The final step is deterministic rule checking, not AI — it runs after all AI reasoning and can override it.'
          : ''}
      </p>
    </div>
  )
}
