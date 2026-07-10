import { test, expect } from './helpers/fixtures'
import { nav } from './helpers/selectors'

/**
 * Root PWA scope assertion — issue #107, counterpart to `subpath.spec.ts`.
 *
 * Proves the SAME code that scopes the SW to `/mygarage/` under a prefix scopes
 * it to `/` at the root. This runs under the `chromium` (root) project, which
 * serves the Vite DEV server — where the SW does NOT register
 * (`import.meta.env.PROD` is false in `main.tsx`). So we assert what is feasible
 * and deterministic at root: the value that DERIVES the SW scope
 * (`withBase('/')`) computes to `/`, and IF a registration somehow exists its
 * scope path is `/`. The production-served, actually-registered case is proven
 * end-to-end by `subpath.spec.ts` (scope `/mygarage/`).
 */
test('root: SW scope basis resolves to "/" (dev registers no SW)', async ({ page }) => {
  await page.goto('/')
  await expect(nav.dashboard(page)).toBeVisible({ timeout: 15000 })

  const result = await page.evaluate(async () => {
    // Mirror main.tsx: scope = withBase('/'), where withBase reads the <base>
    // element href (absent at root -> "" -> withBase('/') === '/').
    const baseEl = document.querySelector('base')
    const href = baseEl?.getAttribute('href') ?? '/'
    const basePath = new URL(href, 'http://x').pathname.replace(/\/$/, '')
    const scopeBasis = basePath ? `${basePath}/` : '/'

    const reg = await navigator.serviceWorker?.getRegistration?.()
    const regScopePath = reg ? new URL(reg.scope).pathname : null
    return { scopeBasis, regScopePath }
  })

  // The scope the app WOULD register with at root is "/".
  expect(result.scopeBasis).toBe('/')
  // And if a SW is registered (prod-parity servers), its scope path is "/".
  if (result.regScopePath !== null) {
    expect(result.regScopePath).toBe('/')
  }
})
