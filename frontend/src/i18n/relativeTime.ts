import type { TFunction } from 'i18next'

/**
 * Locale-aware "N minutes/hours/days ago" — the frontend counterpart to
 * `backend/community/freshness.py::_relative_time()`. That function still
 * exists and still runs (other backend consumers may read its English
 * string), but the UI must never render it directly: bucketing thresholds
 * are mirrored exactly (< 60s "just now", < 60min minutes, < 24h hours,
 * else days) so this always agrees with the backend's own `status`
 * (FRESH/AGING/STALE) for the same underlying delta — only the words
 * change per language, never the math.
 *
 * `seconds === null` means "never reported" (task: never invent a fake
 * elapsed time for missing data — mirrors Safety Engine R8's own "missing
 * is never coerced into a value").
 */
export function formatRelativeTime(seconds: number | null, t: TFunction<'common'>): string {
  if (seconds === null) return t('time.noReportThisPeriod')
  if (seconds < 60) return t('time.justNow')

  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return t('time.minutesAgo', { count: minutes })

  const hours = Math.floor(minutes / 60)
  if (hours < 24) return t('time.hoursAgo', { count: hours })

  const days = Math.floor(hours / 24)
  return t('time.daysAgo', { count: days })
}

/**
 * Locale-aware "Due today" / "Overdue by N days" / "Due in N days" — the
 * frontend counterpart to `backend/assessments/followups.py
 * ::due_description()`. That function's English string is still sent (as
 * `due_description`, kept for backward compatibility) but must never be
 * rendered directly; this derives the same phrase from the raw
 * `days_until_due` integer the API already sends alongside it, so no
 * backend change was needed for this one.
 *
 * Mirrors the backend's own branching exactly: a COMPLETED/MISSED
 * follow-up shows its status word instead of a date phrase (the same
 * `t('status.*')` lookup `FollowUpPill` uses), even if its `due_date`
 * happens to be in the past or future.
 *
 * `daysUntil === null` mirrors the backend's own "no date recorded"
 * case — never invented from a missing value.
 */
export function formatDueDescription(
  daysUntil: number | null,
  status: 'PENDING' | 'COMPLETED' | 'MISSED',
  t: TFunction<'common'>,
): string {
  if (status === 'COMPLETED' || status === 'MISSED') {
    return t(`status.${status}`, { defaultValue: status })
  }
  if (daysUntil === null) return t('time.noFollowUpDateRecorded')
  if (daysUntil === 0) return t('time.dueToday')
  if (daysUntil < 0) return t('time.overdueByDays', { count: Math.abs(daysUntil) })
  if (daysUntil === 1) return t('time.dueTomorrow')
  return t('time.dueInDays', { count: daysUntil })
}
