import { afterEach, beforeAll, vi } from 'vitest'
import { cleanup } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import i18next from 'i18next'
import commonEn from '../locales/en/common.json'
import navEn from '../locales/en/nav.json'
import settingsEn from '../locales/en/settings.json'
import vehiclesEn from '../locales/en/vehicles.json'
import formsEn from '../locales/en/forms.json'
import analyticsEn from '../locales/en/analytics.json'

// Real i18next singleton, en only. Code outside React (httpErrorHandler,
// ErrorBoundary) calls it directly, and uninitialised it hands back the raw
// "Failed to {{action}}" template, so no test could see which action went in.
// It runs in beforeAll, after the test file's imports, so a file that imports
// the app's own src/i18n.ts keeps that config instead of getting this one
// layered under it (i18next merges a re-init over the old options).
beforeAll(() => {
  if (i18next.isInitialized || i18next.isInitializing) return
  void i18next.init({
    lng: 'en',
    fallbackLng: 'en',
    ns: ['common', 'nav', 'settings', 'vehicles', 'forms', 'analytics'],
    defaultNS: 'common',
    resources: {
      en: {
        common: commonEn,
        nav: navEn,
        settings: settingsEn,
        vehicles: vehiclesEn,
        forms: formsEn,
        analytics: analyticsEn,
      },
    },
    interpolation: { escapeValue: false },
    initAsync: false,
  })
})

// Mock react-i18next globally for all tests.
//
// t and i18n MUST keep a stable identity across renders, exactly as the real
// react-i18next does (it memoizes them per language). If a fresh t is handed
// out on every render, any effect that correctly lists t in its dependency
// array — a pervasive, idiomatic pattern in this codebase, e.g.
// VehicleTransferWizard / VehicleSharingModal's recipient loader — re-fires on
// every render. That loops the data fetch and remounts children mid-interaction,
// which surfaced as a CI-only flake where a click landed on a remounting node
// and the selection was lost. Hoisting these to module scope fixes it at the
// source for every such component.
const mockT = (key: string) => key
const mockI18n = { language: 'en', changeLanguage: () => Promise.resolve() }
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT, i18n: mockI18n }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}))

// Mock axios before any imports that might use it
vi.mock('axios', () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mockAxios: any = {
    get: vi.fn(() => Promise.resolve({ data: {} })),
    post: vi.fn(() => Promise.resolve({ data: {} })),
    put: vi.fn(() => Promise.resolve({ data: {} })),
    patch: vi.fn(() => Promise.resolve({ data: {} })),
    delete: vi.fn(() => Promise.resolve({ data: {} })),
    interceptors: {
      request: {
        use: vi.fn(),
        eject: vi.fn(),
      },
      response: {
        use: vi.fn(),
        eject: vi.fn(),
      },
    },
    defaults: {
      headers: {
        common: {},
      },
    },
  }
  mockAxios.create = vi.fn(() => mockAxios)
  return { default: mockAxios }
})

// Cleanup after each test
afterEach(() => {
  cleanup()
})

// Mock window.matchMedia (for responsive components)
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(), // Deprecated but some libs still use
    removeListener: vi.fn(), // Deprecated
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// Mock IntersectionObserver (for lazy loading/visibility detection)
globalThis.IntersectionObserver = class IntersectionObserver {
  constructor() {}
  disconnect() {}
  observe() {}
  takeRecords() {
    return []
  }
  unobserve() {}
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
} as any

// Mock ResizeObserver (for responsive components)
globalThis.ResizeObserver = class ResizeObserver {
  constructor() {}
  disconnect() {}
  observe() {}
  unobserve() {}
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
} as any
