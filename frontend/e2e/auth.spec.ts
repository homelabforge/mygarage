import { test, expect } from './helpers/fixtures'
import { ADMIN } from './helpers/selectors'

test.describe('Authentication', () => {
  // Use fresh context with no stored auth state
  test.use({ storageState: { cookies: [], origins: [] } })

  test('redirects unauthenticated user to login page', async ({ page }) => {
    await page.goto('/settings')
    await page.waitForURL(/\/login/, { timeout: 15000 })
    expect(page.url()).toContain('/login')
  })

  test('login with valid credentials', async ({ page }) => {
    await page.goto('/login')
    await expect(page.locator('#username')).toBeVisible({ timeout: 10000 })

    await page.locator('#username').fill(ADMIN.username)
    await page.locator('#password').fill(ADMIN.password)
    await page.getByRole('button', { name: 'Sign In' }).click()

    await expect(page).toHaveURL('/', { timeout: 15000 })
    await expect(page.getByRole('link', { name: 'Dashboard' })).toBeVisible()
  })

  test('login with invalid credentials shows error', async ({ page }) => {
    await page.goto('/login')
    await expect(page.locator('#username')).toBeVisible({ timeout: 10000 })

    await page.locator('#username').fill('wronguser')
    await page.locator('#password').fill('WrongPass!1')
    await page.getByRole('button', { name: 'Sign In' }).click()

    // Should stay on login page with inline error message
    await expect(page).toHaveURL(/\/login/, { timeout: 5000 })
    await expect(page.getByText(/incorrect|failed|invalid/i)).toBeVisible({ timeout: 5000 })
  })
})

// Playwright's clicks are real (trusted) input, which jsdom can't fake, so this
// is where the "a person asked for the fill" check runs for real. The fill
// itself is what a password manager does: set the value behind React's back,
// then fire input and change.
test.describe('a login filled in by a password manager', () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
      const fillOne = (selector: string, value: string): void => {
        const input = document.querySelector<HTMLInputElement>(selector)
        if (!input || !setValue) throw new Error(`no ${selector} to fill`)
        setValue.call(input, value)
        input.dispatchEvent(new Event('input', { bubbles: true }))
        input.dispatchEvent(new Event('change', { bubbles: true }))
      }
      ;(window as unknown as { __managerFill: (u: string, p: string) => void }).__managerFill = (u, p) => {
        fillOne('#username', u)
        fillOne('#password', p)
      }
    })
  })

  const managerFill = (page: import('@playwright/test').Page): Promise<void> =>
    page.evaluate(
      ([u, p]) => (window as unknown as { __managerFill: (u: string, p: string) => void }).__managerFill(u, p),
      [ADMIN.username, ADMIN.password],
    )

  const countLogins = (page: import('@playwright/test').Page): (() => number) => {
    let count = 0
    page.on('request', (request) => {
      if (request.method() === 'POST' && request.url().includes('/api/auth/login')) count += 1
    })
    return () => count
  }

  test('a fill after clicking the username field signs in', async ({ page }) => {
    await page.goto('/login')
    await expect(page.locator('#username')).toBeVisible({ timeout: 10000 })

    await page.locator('#username').click()
    // A person picks the login from the list a moment after the click. The hook
    // only arms a task after the click, and evaluate() can beat that task.
    await page.waitForTimeout(200)
    await managerFill(page)

    await expect(page).toHaveURL('/', { timeout: 15000 })
  })

  test('a fill nobody asked for waits', async ({ page }) => {
    const logins = countLogins(page)
    await page.goto('/login')
    await expect(page.locator('#username')).toBeVisible({ timeout: 10000 })

    await managerFill(page)
    await page.waitForTimeout(1000)

    await expect(page).toHaveURL(/\/login/)
    expect(logins()).toBe(0)
  })

  test("a fill inside the click's own task waits", async ({ page }) => {
    const logins = countLogins(page)
    await page.goto('/login')
    await expect(page.locator('#username')).toBeVisible({ timeout: 10000 })

    // On the field itself, so it runs after the hook's listener on the document.
    await page.evaluate(() => {
      const fill = (window as unknown as { __managerFill: (u: string, p: string) => void }).__managerFill
      document.querySelector('#username')?.addEventListener(
        'pointerdown',
        () => fill('e2e-admin', 'E2eTest!ng123'),
        { once: true },
      )
    })
    await page.locator('#username').click()
    await page.waitForTimeout(1000)

    await expect(page).toHaveURL(/\/login/)
    expect(logins()).toBe(0)
  })
})
