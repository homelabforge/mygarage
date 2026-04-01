/**
 * Syncs i18n language with the authenticated user's DB preference.
 *
 * Precedence:
 * 1. Authenticated user DB preference (user.language from /auth/me)
 * 2. localStorage ('i18nextLng') — for unauthenticated or pre-auth render
 * 3. Browser navigator.language — first-visit detection only
 * 4. Fallback: 'en'
 *
 * Mount this in App.tsx under AuthProvider so ALL routes (including auth/OIDC)
 * share one language source of truth.
 */
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../contexts/AuthContext'

export function useLanguageSync(): void {
  const { i18n } = useTranslation()
  const { user } = useAuth()

  useEffect(() => {
    // Rule 1: authenticated user's DB preference takes precedence
    if (user?.language && user.language !== i18n.language) {
      console.log(`[i18n-debug] useLanguageSync: changing ${i18n.language} -> ${user.language}`)
      i18n.changeLanguage(user.language)
    }
  }, [user?.language, i18n])

  // Keep <html lang="..."> in sync and tell SW to proactively cache translations
  useEffect(() => {
    document.documentElement.lang = i18n.language

    // Ask service worker to pre-cache translation files for offline use
    if (i18n.language !== 'en' && navigator.serviceWorker?.controller) {
      navigator.serviceWorker.controller.postMessage({
        type: 'CACHE_LANGUAGE',
        lang: i18n.language,
        version: typeof APP_VERSION !== 'undefined' ? APP_VERSION : '0',
      })
    }
  }, [i18n.language])
}

declare const APP_VERSION: string
