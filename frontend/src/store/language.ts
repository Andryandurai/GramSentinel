import { create } from 'zustand'

import i18n, { SUPPORTED_LANGUAGES, type SupportedLanguage } from '@/i18n'

/**
 * Global language preference — the same Zustand architecture every other
 * piece of shared state in this app already uses (`store/auth.ts`,
 * `store/fieldOperations.ts`, etc.), not a second state-management system
 * (task §6).
 *
 * Persisted directly to `localStorage` under a dedicated key (task §7) —
 * a UI preference, never sent to the backend as patient/user data. Works
 * identically for the Worker and Officer portals and on the pre-login
 * screen (task §8/§16): this store has no dependency on `useAuth`.
 */
const STORAGE_KEY = 'gramsentinel.language'

function readStoredLanguage(): SupportedLanguage {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored && (SUPPORTED_LANGUAGES as readonly string[]).includes(stored)) {
      return stored as SupportedLanguage
    }
  } catch {
    // localStorage unavailable (private browsing, etc.) — fall back silently.
  }
  return 'en'
}

interface LanguageState {
  language: SupportedLanguage
  setLanguage: (language: SupportedLanguage) => void
  initializeLanguage: () => void
}

export const useLanguage = create<LanguageState>((set) => ({
  language: 'en',

  setLanguage(language) {
    void i18n.changeLanguage(language)
    try {
      window.localStorage.setItem(STORAGE_KEY, language)
    } catch {
      // Best-effort persistence only — the in-memory switch above already
      // updated every subscribed component regardless.
    }
    set({ language })
  },

  initializeLanguage() {
    const language = readStoredLanguage()
    void i18n.changeLanguage(language)
    set({ language })
  },
}))
