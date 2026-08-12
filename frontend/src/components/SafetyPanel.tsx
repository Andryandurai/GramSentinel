import { SafetyPill } from '@/components/ui'
import type { SafetyRule, SafetyVerdict } from '@/types'

/**
 * Per-rule safety result.
 *
 * Showing every rule — passed and failed — is the point: the officer can
 * disagree with the system on specific grounds rather than accepting or
 * rejecting an opaque score.
 */
export function SafetyPanel({
  verdict,
  status,
  rules,
  reasons,
  engineVersion,
}: {
  verdict: SafetyVerdict
  status: string
  rules: SafetyRule[]
  reasons?: string[]
  engineVersion?: string
}) {
  const failed = rules.filter((r) => !r.passed)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <SafetyPill verdict={verdict} />
        <span className="text-sm text-ink-600">
          {status.replace(/_/g, ' ').toLowerCase()}
        </span>
        <span className="ml-auto text-xs text-ink-400">
          Deterministic engine v{engineVersion ?? '1.0.0'} · non-LLM
        </span>
      </div>

      <ul className="space-y-1.5">
        {rules.map((rule) => (
          <li
            key={rule.code}
            className={`flex gap-3 rounded-md border px-3 py-2 ${
              rule.passed
                ? 'border-ink-200 bg-white'
                : 'border-amber-300 bg-amber-50'
            }`}
          >
            <span
              className={`mt-0.5 font-mono text-xs font-bold ${
                rule.passed ? 'text-care-600' : 'text-amber-700'
              }`}
            >
              {rule.passed ? '✓' : '✕'} {rule.code}
            </span>
            <div className="min-w-0">
              <div className="text-sm font-medium">{rule.name}</div>
              <p className="text-xs text-ink-600 mt-0.5">{rule.detail}</p>
            </div>
          </li>
        ))}
      </ul>

      {failed.length > 0 && reasons?.length ? (
        <div className="rounded-md bg-amber-50 border border-amber-200 px-3 py-2">
          <div className="text-xs font-semibold text-amber-800 mb-1">
            Why this was not released at full confidence
          </div>
          <ul className="text-xs text-amber-900 space-y-1 list-disc pl-4">
            {reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <p className="text-xs text-ink-400 border-t border-ink-200 pt-3">
        The safety engine is ordinary Python running after all AI reasoning. No
        prompt or model output can bypass, disable or soften a rule. Human
        review is required regardless of the verdict.
      </p>
    </div>
  )
}
