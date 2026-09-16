import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import commonEn from './locales/en/common.json'
import workerEn from './locales/en/worker.json'
import officerEn from './locales/en/officer.json'
import assessmentsEn from './locales/en/assessments.json'
import pregnancyEn from './locales/en/pregnancy.json'
import simulationEn from './locales/en/simulation.json'
import operationsEn from './locales/en/operations.json'

import commonTa from './locales/ta/common.json'
import workerTa from './locales/ta/worker.json'
import officerTa from './locales/ta/officer.json'
import assessmentsTa from './locales/ta/assessments.json'
import pregnancyTa from './locales/ta/pregnancy.json'
import simulationTa from './locales/ta/simulation.json'
import operationsTa from './locales/ta/operations.json'

import commonHi from './locales/hi/common.json'
import workerHi from './locales/hi/worker.json'
import officerHi from './locales/hi/officer.json'
import assessmentsHi from './locales/hi/assessments.json'
import pregnancyHi from './locales/hi/pregnancy.json'
import simulationHi from './locales/hi/simulation.json'
import operationsHi from './locales/hi/operations.json'

/**
 * Centralized localization — English, Tamil, and Hindi across the Health
 * Worker and Health Officer portals. One i18next instance, initialized
 * once at module load (task §48: "initialize i18n once").
 *
 * The active language is NOT owned by i18next's own detector/persistence —
 * it is driven by the existing Zustand architecture (`store/language.ts`),
 * exactly like the rest of this app's global state (task §6: "if Zustand
 * is already used, extend the existing Zustand architecture. Do not create
 * a second state-management system"). `store/language.ts` calls
 * `i18n.changeLanguage()` and persists the choice to localStorage itself;
 * i18next here only owns the translation resources and the `t()` engine.
 *
 * Namespaces mirror the task's own requested file structure: `common`
 * (shared header/nav/buttons/status labels/validation — task §18's
 * `t('status.${status}')` lives here), `worker`, `officer`, `assessments`,
 * `pregnancy`, `simulation`, `operations`.
 *
 * `returnEmptyString: false` plus `fallbackLng: 'en'` implements task
 * §28's required fallback: a missing key in Tamil/Hindi renders the
 * English string, never `undefined`, a raw key, or blank text.
 */
export const SUPPORTED_LANGUAGES = ['en', 'ta', 'hi'] as const
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number]

export const LANGUAGE_LABELS: Record<SupportedLanguage, string> = {
  en: 'English',
  ta: 'தமிழ்',
  hi: 'हिन्दी',
}

export const DEFAULT_NAMESPACE = 'common'

void i18n.use(initReactI18next).init({
  lng: 'en',
  fallbackLng: 'en',
  supportedLngs: SUPPORTED_LANGUAGES as unknown as string[],
  defaultNS: DEFAULT_NAMESPACE,
  ns: ['common', 'worker', 'officer', 'assessments', 'pregnancy', 'simulation', 'operations'],
  resources: {
    en: {
      common: commonEn,
      worker: workerEn,
      officer: officerEn,
      assessments: assessmentsEn,
      pregnancy: pregnancyEn,
      simulation: simulationEn,
      operations: operationsEn,
    },
    ta: {
      common: commonTa,
      worker: workerTa,
      officer: officerTa,
      assessments: assessmentsTa,
      pregnancy: pregnancyTa,
      simulation: simulationTa,
      operations: operationsTa,
    },
    hi: {
      common: commonHi,
      worker: workerHi,
      officer: officerHi,
      assessments: assessmentsHi,
      pregnancy: pregnancyHi,
      simulation: simulationHi,
      operations: operationsHi,
    },
  },
  interpolation: {
    escapeValue: false, // React already escapes.
  },
  returnEmptyString: false,
  react: {
    useSuspense: false,
  },
  // Task §28: a missing key must still render something safe (i18next's
  // own default — the key path itself — rather than "undefined" or a
  // blank string), but a developer must be able to see it happened. This
  // never runs in production; it exists only in dev tooling.
  saveMissing: import.meta.env.DEV,
  missingKeyHandler: import.meta.env.DEV
    ? (languages, namespace, key) => {
        // eslint-disable-next-line no-console
        console.warn(`[i18n] Missing translation: ${namespace}:${key} (${languages.join(', ')})`)
      }
    : undefined,
})

export default i18n
