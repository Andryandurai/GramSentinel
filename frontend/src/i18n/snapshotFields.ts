import type { TFunction } from 'i18next'

/**
 * Correction Request "before" snapshots (`backend/workspace/services.py
 * ::record_label_and_snapshot()`) are stored as a plain `{English field
 * name: value}` dict — already-persisted data, so the backend's key
 * format cannot change retroactively without leaving old correction
 * requests inconsistent with new ones. This maps the fixed, known set of
 * English field names that function can produce to a translation key, so
 * the *label* the officer/worker sees is localized even though the
 * underlying stored dict key stays English. An unrecognized field name
 * (should never happen — the function's own field set is closed) falls
 * back to the raw English text rather than showing nothing.
 */
const FIELD_KEYS: Record<string, string> = {
  'Encounter date': 'encounterDate',
  'Primary category': 'primaryCategory',
  'Triage level': 'triageLevel',
  'Temperature (C)': 'temperatureC',
  'Pulse (bpm)': 'pulseBpm',
  'Blood sugar (mg/dL)': 'bloodSugarMgDl',
  'Reporting week': 'reportingWeek',
  'Fever cases': 'feverCases',
  'Respiratory cases': 'respiratoryCases',
  'Diarrhoeal cases': 'diarrhoealCases',
  'Other cases': 'otherCases',
}

export function translateSnapshotField(field: string, t: TFunction<'common'>): string {
  const key = FIELD_KEYS[field]
  return key ? t(`snapshotFields.${key}`, { defaultValue: field }) : field
}
