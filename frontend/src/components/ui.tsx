import { useState, type ReactNode } from 'react'

import type {
  FollowUpState,
  SafetyVerdict,
  Severity,
  TriageLevel,
} from '@/types'

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

/**
 * Follow-up urgency. Overdue and due-today read clearly without shouting —
 * this sits in a clinical worklist, not a notification centre.
 */
export function FollowUpPill({
  status,
  label,
}: {
  status: FollowUpState
  label?: string
}) {
  const styles: Record<FollowUpState, string> = {
    OVERDUE: 'bg-red-100 text-red-700',
    DUE_TODAY: 'bg-amber-100 text-amber-800',
    UPCOMING: 'bg-ink-100 text-ink-600',
    COMPLETED: 'bg-care-100 text-care-700',
    MISSED: 'bg-red-50 text-red-700',
    UNSCHEDULED: 'bg-ink-100 text-ink-400',
  }
  const fallback: Record<FollowUpState, string> = {
    OVERDUE: 'Overdue',
    DUE_TODAY: 'Due today',
    UPCOMING: 'Upcoming',
    COMPLETED: 'Completed',
    MISSED: 'Missed',
    UNSCHEDULED: 'No date',
  }
  return (
    <span className={`pill ${styles[status] ?? styles.UPCOMING}`}>
      {label || fallback[status] || 'Upcoming'}
    </span>
  )
}

/**
 * A profile photograph, or the person's initials when none has been uploaded.
 * Never renders a broken image: a photo that fails to load falls back to the
 * same initials.
 */
export function Avatar({
  src,
  initials,
  name,
  size = 'md',
}: {
  src?: string | null
  initials?: string
  name?: string
  size?: 'sm' | 'md' | 'lg'
}) {
  const [failed, setFailed] = useState(false)
  const sizes = {
    sm: 'h-9 w-9 text-xs',
    md: 'h-12 w-12 text-sm',
    lg: 'h-24 w-24 text-xl',
  }
  const letters =
    (initials || '').trim() ||
    (name || '')
      .split(/\s+/)
      .map((part) => part[0])
      .filter((c) => c && /[a-z]/i.test(c))
      .slice(0, 2)
      .join('')
      .toUpperCase() ||
    '—'

  const shell = `${sizes[size]} shrink-0 rounded-full overflow-hidden border border-ink-200 bg-ink-100`

  if (src && !failed) {
    return (
      <img
        src={src}
        alt={name ? `${name} — profile photograph` : 'Profile photograph'}
        className={`${shell} object-cover`}
        onError={() => setFailed(true)}
      />
    )
  }

  return (
    <span
      className={`${shell} grid place-items-center font-semibold text-ink-600`}
      aria-hidden="true"
    >
      {letters}
    </span>
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
