/**
 * i18next initialization — single source of truth for language configuration.
 *
 * English is bundled inline (zero network request for default language).
 * Non-English loaded lazily via i18next-http-backend with cache-busting.
 */
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
import HttpBackend from 'i18next-http-backend'

// Canonical English translations — bundled at build time via Vite import
import commonEn from './locales/en/common.json'
import navEn from './locales/en/nav.json'
import settingsEn from './locales/en/settings.json'

declare const APP_VERSION: string

i18n
  .use(HttpBackend)
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    // Bundled English — no network request needed
    resources: {
      en: {
        common: commonEn,
        nav: navEn,
        settings: settingsEn,
      },
    },

    // Only load base language tags (pl, not pl-PL)
    load: 'languageOnly',
    supportedLngs: ['en', 'pl', 'uk', 'ru'],
    fallbackLng: 'en',
    defaultNS: 'common',
    ns: ['common', 'nav', 'settings'],

    // Detection: localStorage first, then browser language
    detection: {
      order: ['localStorage', 'navigator'],
      lookupLocalStorage: 'i18nextLng',
      caches: ['localStorage'],
    },

    // Non-English: load via HTTP with cache-busting version
    backend: {
      loadPath: `/locales/{{lng}}/{{ns}}.json?v=${typeof APP_VERSION !== 'undefined' ? APP_VERSION : '0'}`,
    },

    // Only use backend for non-English (English is bundled inline)
    partialBundledLanguages: true,

    react: {
      useSuspense: true,
    },

    interpolation: {
      escapeValue: false, // React already escapes
    },
  })

export default i18n
