import { test as base } from '@playwright/test'

/**
 * Custom test fixture that pins the browser to English locale.
 *
 * i18next's LanguageDetector reads localStorage synchronously at module
 * import time. Playwright's storageState restoration may not complete
 * before the page JavaScript executes, causing the detector to fall
 * through to navigator detection (which resolves to Polish in CI).
 *
 * addInitScript runs BEFORE any page script on every navigation,
 * guaranteeing localStorage.i18nextLng is set when i18next reads it.
 */
export const test = base.extend({
  // eslint-disable-next-line react-hooks/rules-of-hooks
  page: async ({ page }, use) => {
    await page.addInitScript(() => {
      localStorage.setItem('i18nextLng', 'en')
    })
    await use(page)
  },
})

export { expect } from '@playwright/test'
