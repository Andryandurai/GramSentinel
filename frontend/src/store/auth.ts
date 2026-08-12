import { create } from 'zustand'

import { api, login as apiLogin, tokens } from '@/services/api'
import type { User } from '@/types'

interface AuthState {
  user: User | null
  status: 'idle' | 'loading' | 'ready'
  error: string | null
  signIn: (username: string, password: string) => Promise<User>
  signOut: () => void
  restore: () => Promise<void>
  clearError: () => void
}

export const useAuth = create<AuthState>((set) => ({
  user: null,
  status: 'idle',
  error: null,

  async signIn(username, password) {
    set({ status: 'loading', error: null })
    try {
      const data = await apiLogin(username, password)
      set({ user: data.user, status: 'ready', error: null })
      return data.user as User
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Sign-in failed.'
      set({ status: 'ready', error: message })
      throw error
    }
  },

  signOut() {
    tokens.clear()
    set({ user: null, status: 'ready', error: null })
  },

  async restore() {
    if (!tokens.access()) {
      set({ status: 'ready', user: null })
      return
    }
    set({ status: 'loading' })
    try {
      const data = await api.get<{ user: User }>('/auth/me/')
      set({ user: data.user, status: 'ready' })
    } catch {
      tokens.clear()
      set({ user: null, status: 'ready' })
    }
  },

  clearError: () => set({ error: null }),
}))

export const homeRouteFor = (user: User | null): string => {
  if (!user) return '/login'
  switch (user.role) {
    case 'HEALTH_OFFICER':
      return '/officer/dashboard'
    case 'PATIENT':
      return '/patient/dashboard'
    // An administrator still has access to the officer and worker portals
    // (see RequireRole's allowAdmin); the platform overview is simply the
    // more useful landing page now that it exists.
    case 'ADMIN':
      return '/admin/dashboard'
    default:
      return '/worker/dashboard'
  }
}
