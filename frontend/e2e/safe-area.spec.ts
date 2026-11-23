import type { Locator, Page } from '@playwright/test'
import { test, expect } from './helpers/fixtures'
import { TEST_VEHICLE } from './helpers/selectors'

/**
 * iOS safe-area insets (#305, #308). The installed iPhone PWA draws under the
 * status bar (viewport-fit=cover + black-translucent), so the headers, the
 * drawer's Close and Save, and toasts all need the --spacing-safe-* insets.
 *
 * Desktop Chromium's env(safe-area-inset-*) is 0, so a computed-style check on
 * its own can't tell working padding from none. Each test measures twice: once
 * as is, which must equal the padding these elements had before the insets
 * (so a utility that REPLACED padding fails on desktop and Android, where the
 * inset is 0), and once with fake nonzero insets injected on :root, which must
 * grow it by exactly the inset. The four sides get different values so a
 * crossed side shows up too.
 *
 * The real gate is still the iPhone (T8): no desktop engine emulates the notch.
 */

const INSET = { top: 40, right: 10, bottom: 30, left: 20 } as const

interface Sides {
  top: number
  right: number
  bottom: number
  left: number
}

const PHONE = { width: 390, height: 844 }
const DESKTOP = { width: 1280, height: 800 }

/** Fake the device insets. Inline on <html> beats Tailwind's :root theme layer. */
async function injectInsets(page: Page): Promise<void> {
  await page.evaluate((inset) => {
    const root = document.documentElement.style
    root.setProperty('--spacing-safe-top', `${inset.top}px`)
    root.setProperty('--spacing-safe-right', `${inset.right}px`)
    root.setProperty('--spacing-safe-bottom', `${inset.bottom}px`)
    root.setProperty('--spacing-safe-left', `${inset.left}px`)
  }, INSET)
}

async function padding(el: Locator): Promise<Sides> {
  return el.evaluate((node) => {
    const s = getComputedStyle(node)
    return {
      top: Number.parseFloat(s.paddingTop),
      right: Number.parseFloat(s.paddingRight),
      bottom: Number.parseFloat(s.paddingBottom),
      left: Number.parseFloat(s.paddingLeft),
    }
  })
}

/** `base` plus the injected inset on the named sides. */
function grown(base: Sides, sides: (keyof Sides)[]): Sides {
  const out = { ...base }
  for (const side of sides) out[side] = base[side] + INSET[side]
  return out
}

async function openQuickEntryServiceDrawer(page: Page): Promise<Locator> {
  await page.goto(`/quick-entry?action=service&vin=${TEST_VEHICLE.vin}`)
  const drawer = page.getByTestId('drawer')
  await expect(drawer).toBeVisible({ timeout: 15000 })
  // Wait out the slide-in so boxes are measured where they land.
  await expect(drawer).toHaveClass(/translate-x-0/)
  return drawer
}

test.describe('iOS safe-area insets (#305, #308)', () => {
  test('TopNav pads its bar below the status bar and clear of the side insets', async ({ page }) => {
    await page.setViewportSize(DESKTOP)
    await page.goto('/supplies')
    const header = page.getByRole('banner')
    await expect(header).toBeVisible({ timeout: 15000 })
    const before = await header.boundingBox()

    // No padding of its own (the 62px row inside carries the gutters).
    expect(await padding(header)).toEqual({ top: 0, right: 0, bottom: 0, left: 0 })

    await injectInsets(page)
    expect(await padding(header)).toEqual({ top: INSET.top, right: INSET.right, bottom: 0, left: INSET.left })
    const after = await header.boundingBox()
    expect(after?.height).toBe((before?.height ?? 0) + INSET.top)
  })

  test('Quick Entry header adds the insets to its own padding', async ({ page }) => {
    await page.setViewportSize(PHONE)
    await page.goto('/quick-entry')
    const header = page.getByRole('banner')
    await expect(header.getByRole('link', { name: 'Dashboard' })).toBeVisible({ timeout: 15000 })

    // px-4 py-3, unchanged where the inset is 0 (desktop, Android).
    const base = { top: 12, right: 16, bottom: 12, left: 16 }
    expect(await padding(header)).toEqual(base)

    await injectInsets(page)
    expect(await padding(header)).toEqual(grown(base, ['top', 'right', 'left']))
  })

  test('Drawer header and Close clear the status bar; the footer clears the home indicator', async ({ page }) => {
    await page.setViewportSize(PHONE)
    const drawer = await openQuickEntryServiceDrawer(page)
    const close = drawer.locator('> header').getByRole('button', { name: 'Close' })
    const footer = drawer.locator('> footer')
    await expect(footer).toBeVisible()

    const closeOffset = async (): Promise<number> => {
      const [panelBox, closeBox] = await Promise.all([drawer.boundingBox(), close.boundingBox()])
      return (closeBox?.y ?? 0) - (panelBox?.y ?? 0)
    }

    // The panel has no padding of its own; the footer is px-6 py-4.
    expect(await padding(drawer)).toEqual({ top: 0, right: 0, bottom: 0, left: 0 })
    const footerBase = { top: 16, right: 24, bottom: 16, left: 24 }
    expect(await padding(footer)).toEqual(footerBase)
    // Above a footer, the body keeps py-5 either way.
    const body = drawer.locator('> div')
    const bodyBase = { top: 20, right: 24, bottom: 20, left: 24 }
    expect(await padding(body)).toEqual(bodyBase)
    const closeBefore = await closeOffset()

    await injectInsets(page)
    expect(await padding(drawer)).toEqual({ top: INSET.top, right: INSET.right, bottom: 0, left: INSET.left })
    expect(await padding(footer)).toEqual(grown(footerBase, ['bottom']))
    expect(await padding(body)).toEqual(bodyBase)
    expect(await closeOffset()).toBe(closeBefore + INSET.top)
  })

  test('a drawer without a footer pads its body clear of the home indicator', async ({ page }) => {
    await page.setViewportSize(PHONE)
    await page.goto('/supplies')
    await page.getByRole('button', { name: 'Quick settings' }).click()
    const drawer = page.getByTestId('drawer')
    await expect(drawer).toHaveClass(/translate-x-0/)
    await expect(drawer.locator('> footer')).toHaveCount(0)
    const body = drawer.locator('> div')

    // px-6 py-5. The body is the panel's last child here, so it takes the inset.
    const base = { top: 20, right: 24, bottom: 20, left: 24 }
    expect(await padding(body)).toEqual(base)

    await injectInsets(page)
    expect(await padding(body)).toEqual(grown(base, ['bottom']))
  })

  for (const { name, viewport, offset } of [
    { name: 'phone', viewport: PHONE, offset: 16 },
    { name: 'desktop', viewport: DESKTOP, offset: 24 },
  ]) {
    test(`a toast raised inside an open drawer clears the status bar (${name})`, async ({ page }) => {
      await page.setViewportSize(viewport)
      const drawer = await openQuickEntryServiceDrawer(page)

      // Removing the only line item is refused with an error toast, and the
      // drawer stays open: a toast raised from inside a drawer, no record saved.
      await drawer.getByTitle('Remove line item').first().click()
      const toaster = page.locator('[data-sonner-toaster]')
      await expect(page.locator('[data-sonner-toast][data-type="error"]')).toBeVisible()
      await expect(toaster).toHaveAttribute('data-y-position', 'top')

      const top = (): Promise<number> => toaster.evaluate((el) => Number.parseFloat(getComputedStyle(el).top))
      expect(await top()).toBe(offset)

      await injectInsets(page)
      expect(await top()).toBe(offset + INSET.top)
    })
  }
})
