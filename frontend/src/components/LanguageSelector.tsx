import { useTranslation } from 'react-i18next'

import { LANGUAGE_LABELS, SUPPORTED_LANGUAGES, type SupportedLanguage } from '@/i18n'
import { useLanguage } from '@/store/language'

/**
 * Compact, always-visible language selector — task §37: native-script
 * language names, never flags (flags imply a country, not a language).
 * Native `<select>` rather than a custom dropdown: it needs no extra
 * open/close state, renders Tamil/Hindi correctly out of the box, and
 * stays keyboard/screen-reader accessible for free.
 *
 * Used identically in both the authenticated header (`PortalLayout`) and
 * the pre-login `Login` page (task §16) — one component, not a second
 * copy per portal (task's own "do not create a separate language system
 * for each portal").
 */
export function LanguageSelector({ tone = 'light' }: { tone?: 'light' | 'dark' }) {
  const { t } = useTranslation()
  const language = useLanguage((state) => state.language)
  const setLanguage = useLanguage((state) => state.setLanguage)

  const toneClasses =
    tone === 'dark'
      ? 'border-white/30 bg-white/10 text-white'
      : 'border-ink-200 bg-white text-ink-700'

  return (
    <label className="inline-flex items-center gap-1.5">
      <span className="sr-only">{t('header.language')}</span>
      <select
        aria-label={t('header.language')}
        value={language}
        onChange={(event) => setLanguage(event.target.value as SupportedLanguage)}
        className={`rounded-md border px-2 py-1 text-xs font-medium ${toneClasses}`}
      >
        {SUPPORTED_LANGUAGES.map((code) => (
          <option key={code} value={code} className="text-ink-800">
            {LANGUAGE_LABELS[code]}
          </option>
        ))}
      </select>
    </label>
  )
}
