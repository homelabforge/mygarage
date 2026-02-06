import type { Page } from '@playwright/test'

/** Navigation links in the top nav bar */
export const nav = {
  dashboard: (page: Page) => page.getByRole('link', { name: 'Dashboard' }),
  analytics: (page: Page) => page.getByRole('link', { name: 'Analytics' }),
  addressBook: (page: Page) => page.getByRole('link', { name: 'Address Book' }),
  poiFinder: (page: Page) => page.getByRole('link', { name: 'Find POI' }),
  calendar: (page: Page) => page.getByRole('link', { name: 'Calendar' }),
  settings: (page: Page) => page.getByRole('link', { name: /settings/i }).first(),
  logo: (page: Page) => page.getByRole('link', { name: /MyGarage/i }).first(),
}

/** Sonner toast selectors */
export const toast = {
  any: (page: Page) => page.locator('[data-sonner-toast]'),
  error: (page: Page) => page.locator('[data-sonner-toast][data-type="error"]'),
  success: (page: Page) => page.locator('[data-sonner-toast][data-type="success"]'),
}

/** Admin credentials used in global.setup.ts */
export const ADMIN = {
  username: 'e2e-admin',
  password: 'E2eTest!ng123',
}
