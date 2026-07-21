import React, { createContext, useContext, useEffect, useState, useCallback } from 'react'
import { useTheme } from './ThemeContext'
import {
  ACCENT_KEYS,
  DEFAULT_ACCENT,
  accentCssVars,
  type AccentKey,
} from '../constants/accents'

interface AccentContextType {
  accent: AccentKey
  setAccent: (accent: AccentKey) => void
}

const AccentContext = createContext<AccentContextType | undefined>(undefined)

export const useAccent = (): AccentContextType => {
  const context = useContext(AccentContext)
  if (!context) {
    throw new Error('useAccent must be used within an AccentProvider')
  }
  return context
}

const STORAGE_KEY = 'accent'

function readStoredAccent(): AccentKey {
  const stored = localStorage.getItem(STORAGE_KEY)
  return ACCENT_KEYS.includes(stored as AccentKey) ? (stored as AccentKey) : DEFAULT_ACCENT
}

/**
 * Accent state.
 *
 * Persistence is localStorage-only (design D13): the `settings` table is keyed
 * on `key` alone with no user_id, its writes are admin-gated, and pre-login
 * reads require membership in a hardcoded public whitelist — so there is no
 * per-user preference mechanism to persist to. Per-account accent is deferred
 * to a follow-up spec.
 *
 * The custom properties go on document.documentElement and nowhere else. @theme
 * resolves `--color-primary: var(--accent)` against :root, so a descendant
 * carrier element cannot re-resolve it: the ~589 *-primary utilities would stay
 * blue while the raw --accent* consumers (focus rings, glows) switched
 * correctly — a silent, partial failure.
 */
export const AccentProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { theme } = useTheme()
  const [accent, setAccentState] = useState<AccentKey>(readStoredAccent)

  const apply = useCallback((next: AccentKey, currentTheme: 'light' | 'dark') => {
    const style = document.documentElement.style
    for (const [prop, value] of Object.entries(accentCssVars(next, currentTheme))) {
      style.setProperty(prop, value)
    }
  }, [])

  // Re-apply on accent change AND on theme change: --accent-fg differs per theme.
  useEffect(() => {
    apply(accent, theme)
  }, [accent, theme, apply])

  const setAccent = useCallback((next: AccentKey) => {
    setAccentState(next)
    localStorage.setItem(STORAGE_KEY, next)
  }, [])

  return (
    <AccentContext.Provider value={{ accent, setAccent }}>
      {children}
    </AccentContext.Provider>
  )
}
