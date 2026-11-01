/**
 * Shared form-interaction helpers for Playwright E2E specs.
 *
 * Created in Phase 0.3 (rc2 test infrastructure) and populated as
 * Phase 3 (frontend bug fixes) lands. Keeping helpers here rather
 * than duplicating across specs makes the bug-specific specs short
 * and lets us evolve the form contracts in one place.
 */

import type { Page, Request } from '@playwright/test'

import { expect } from './fixtures'

/** Capture the next API request matching method + URL pattern.
 *
 * Used by tests that need to verify form submit posts the right
 * payload (Phase 3.3 address-book FK write, Phase 3.5 time field,
 * Phase 3.7 OBC HH:MM ingestion). Returns a promise that resolves
 * with the parsed JSON body. Call it before the click that sends it.
 *
 * A request that never goes out fails here, by name, after `timeoutMs`,
 * instead of hanging the test until its own timeout says nothing useful.
 */
export function captureApiRequest(
  page: Page,
  method: string,
  urlPattern: RegExp,
  timeoutMs = 10_000
): Promise<Record<string, unknown>> {
  return page
    .waitForRequest((request: Request) => request.method() === method && urlPattern.test(request.url()), {
      timeout: timeoutMs,
    })
    .then(
      (request) => JSON.parse(request.postData() ?? '{}') as Record<string, unknown>,
      (error: unknown) => {
        throw new Error(`captureApiRequest: no ${method} matching ${urlPattern} within ${timeoutMs} ms`, {
          cause: error,
        })
      }
    )
}

/** Open the "Add Fill-up" modal on a vehicle's fuel tab.
 *
 * Standardizes the entry point for fuel-form tests so individual
 * specs don't redo the navigation + button-click dance.
 */
export async function openFuelRecordForm(page: Page, vin: string): Promise<void> {
  await page.goto(`/vehicles/${vin}?tab=fuel`)
  await expect(page.getByText('Fuel History')).toBeVisible({ timeout: 10000 })
  await page.getByRole('button', { name: /add fill-up/i }).click()
  await expect(page.getByText('Add Fuel Record')).toBeVisible({ timeout: 5000 })
}
