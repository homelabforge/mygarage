import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'

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
