import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { Card, ErrorNote, Loading, Stat } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import type { WorkerPregnancySummary } from '@/types'

/**
 * Compact Phase 14 dashboard card — a village-scoped count summary only
 * (`GET /pregnancy/worker/summary/`), never the individual pregnancy list.
 * Clicking through opens New Assessment, where the actual pregnancy record
 * for a specific patient lives (task §14: "clicking the card should show
 * authorized village-scoped records. No cross-village access.").
 */
export function PregnancySummaryCard() {
  const { t } = useTranslation('pregnancy')
  const summary = useAsync<WorkerPregnancySummary>(() => api.get('/pregnancy/worker/summary/'))

  if (summary.loading) return <Loading label={t('officer.loadingSummary')} />
  if (summary.error) return <ErrorNote message={summary.error} onRetry={summary.reload} />
  if (!summary.data) return null

  return (
    <Card
      title={t('workerSummary.title')}
      action={
        <Link to="/worker/assessment/new" className="text-xs text-ink-400 hover:text-ink-600">
          {t('common:nav.newAssessment')}
        </Link>
      }
    >
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat value={summary.data.active_pregnancies} label={t('officer.activePregnancies')} />
        <Stat value={summary.data.due_soon} label={t('workerSummary.dueSoon')} tone="amber" />
        <Stat value={summary.data.overdue} label={t('common:status.OVERDUE')} tone="red" />
        <Stat value={summary.data.missing_picme} label={t('workerSummary.missingPicme')} />
      </div>
    </Card>
  )
}
