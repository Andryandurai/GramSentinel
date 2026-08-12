import type { ReactNode } from 'react'

import type { SafetyVerdict, Severity, TriageLevel } from '@/types'

export function Card({
  title,
  action,
  children,
  className = '',
}: {
  title?: string
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`card ${className}`}>
      {title && (
        <header className="card-header">
          <h2 className="card-title">{title}</h2>
          {action}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  )
}

export function Stat({
  value,
  label,
  tone = 'ink',
}: {
  value: ReactNode
  label: string
  tone?: 'ink' | 'care' | 'sentinel' | 'amber' | 'red'
}) {
  const tones = {
    ink: 'text-ink-800',
    care: 'text-care-600',
    sentinel: 'text-sentinel-600',
    amber: 'text-amber-600',
    red: 'text-red-600',
  }
  return (
    <div className="stat">
      <div className={`stat-value ${tones[tone]}`}>{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  )
}

export function TriagePill({ level }: { level: TriageLevel }) {
  const styles: Record<TriageLevel, string> = {
    ROUTINE: 'bg-care-100 text-care-700',
    CONCERNING: 'bg-amber-100 text-amber-800',
    URGENT: 'bg-red-100 text-red-700',
  }
  return <span className={`pill ${styles[level]}`}>{level}</span>
}

export function SeverityPill({ severity }: { severity: Severity }) {
  const styles: Record<Severity, string> = {
    LOW: 'bg-ink-100 text-ink-600',
    MODERATE: 'bg-amber-100 text-amber-800',
    HIGH: 'bg-red-100 text-red-700',
  }
  return <span className={`pill ${styles[severity]}`}>{severity}</span>
}

export function SafetyPill({ verdict }: { verdict: SafetyVerdict }) {
  const styles: Record<SafetyVerdict, string> = {
    PASS: 'bg-care-100 text-care-700',
    DOWNGRADE: 'bg-amber-100 text-amber-800',
    BLOCK: 'bg-red-100 text-red-700',
  }
  return (
    <span className={`pill ${styles[verdict]}`}>SAFETY&nbsp;{verdict}</span>
  )
}

export function Delta({ value }: { value: number | null }) {
  if (value === null || value === undefined) {
    return <span className="text-ink-400">—</span>
  }
  const rising = value > 0
  return (
    <span
      className={`font-mono tabular-nums font-semibold ${
        rising ? 'text-red-600' : 'text-ink-600'
      }`}
    >
      {rising ? '+' : ''}
      {value.toFixed(0)}%
    </span>
  )
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-10 justify-center text-sm text-ink-600">
      <span className="h-4 w-4 rounded-full border-2 border-ink-200 border-t-care-600 animate-spin" />
      {label}
    </div>
  )
}

export function ErrorNote({
  message,
  onRetry,
}: {
  message: string
  onRetry?: () => void
}) {
  return (
    <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
      <div className="font-medium">Something went wrong</div>
      <p className="mt-1">{message}</p>
      {onRetry && (
        <button className="btn-ghost mt-3 py-1" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="text-sm text-ink-400 py-6 text-center">{children}</p>
  )
}

/** The disclaimer is required on every human-facing surface. */
export function Disclaimer({ className = '' }: { className?: string }) {
  return (
    <p className={`text-xs text-ink-400 ${className}`}>
      Decision-support only. Does not replace professional medical care. Human
      approval required. All data shown is synthetic.
    </p>
  )
}

export function SyntheticBadge() {
  return (
    <span className="pill bg-ink-100 text-ink-600 font-medium">
      SYNTHETIC DEMO DATA
    </span>
  )
}
