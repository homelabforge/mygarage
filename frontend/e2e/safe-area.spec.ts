import type { Locator, Page } from '@playwright/test'
import { test, expect } from './helpers/fixtures'
import { TEST_VEHICLE } from './helpers/selectors'

/**
 * iOS safe-area insets (#305, #308). The installed iPhone PWA draws under the
 * status bar (viewport-fit=cover + black-translucent), so the headers, the
 * drawer's Close and Save, toasts and the old centred modals all need the
 * --spacing-safe-* insets.
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
async function injectInsets(page: Page, insets: Sides = INSET): Promise<void> {
  await page.evaluate((inset) => {
    const root = document.documentElement.style
    root.setProperty('--spacing-safe-top', `${inset.top}px`)
    root.setProperty('--spacing-safe-right', `${inset.right}px`)
    root.setProperty('--spacing-safe-bottom', `${inset.bottom}px`)
    root.setProperty('--spacing-safe-left', `${inset.left}px`)
  }, insets)
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

/**
 * A right-anchored drawer only reaches the left inset when it starts inside it,
 * so its extra left padding is just the overlap: the inset minus the gap
 * between the screen's left edge and the panel.
 */
/**
 * The slide-in class flips at once and the panel takes a moment to land
 * (Tailwind v4 animates `translate`, not `transform`). Settled means no
 * animation left and the right edge on the viewport's.
 */
async function settled(drawer: Locator): Promise<void> {
  await expect(drawer).toHaveClass(/translate-x-0/)
  await expect
    .poll(() =>
      drawer.evaluate((el) => ({
        running: el.getAnimations().length,
        gap: Math.round(document.documentElement.clientWidth - el.getBoundingClientRect().right),
      })),
    )
    .toEqual({ running: 0, gap: 0 })
}

async function expectLeftOverlapOnly(drawer: Locator, inset: number): Promise<number> {
  const box = await drawer.boundingBox()
  expect(box).not.toBeNull()
  const overlap = Math.max(0, inset - (box?.x ?? 0))
  expect((await padding(drawer)).left).toBeCloseTo(overlap, 1)
  return overlap
}

async function openQuickEntryServiceDrawer(page: Page): Promise<Locator> {
  await page.goto(`/quick-entry?action=service&vin=${TEST_VEHICLE.vin}`)
  const drawer = page.getByTestId('drawer')
  await expect(drawer).toBeVisible({ timeout: 15000 })
  // Wait out the slide-in so boxes are measured where they land.
  await settled(drawer)
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
    const panel = await padding(drawer)
    expect({ top: panel.top, right: panel.right, bottom: panel.bottom }).toEqual({
      top: INSET.top,
      right: INSET.right,
      bottom: 0,
    })
    // lg is 96vw here, so the panel starts 15.6px in and only 4.4px of the 20px inset is under it.
    expect(await expectLeftOverlapOnly(drawer, INSET.left)).toBeCloseTo(4.4, 1)
    expect(await padding(footer)).toEqual(grown(footerBase, ['bottom']))
    expect(await padding(body)).toEqual(bodyBase)
    expect(await closeOffset()).toBe(closeBefore + INSET.top)
  })

  test('landscape: a drawer takes only the part of the left inset it overlaps', async ({ page }) => {
    // Landscape iPhone: the notch side's inset is ~47px and the drawer is anchored right.
    await page.setViewportSize({ width: 844, height: 390 })
    const landscape = { top: 0, right: 47, bottom: 21, left: 47 }

    // md is min(600px, 96vw): it starts 244px in, well clear of the inset.
    await page.goto('/supplies')
    await page.getByRole('button', { name: 'Add Supply' }).first().click()
    const md = page.getByRole('dialog', { name: 'Add Supply' })
    await settled(md)
    expect((await padding(md)).left).toBe(0)
    await injectInsets(page, landscape)
    expect(await expectLeftOverlapOnly(md, landscape.left)).toBe(0)

    // xl is min(820px, 97vw): it starts 25.3px in, so 21.7px of the inset is under it.
    await page.goto(`/vehicles/${TEST_VEHICLE.vin}`)
    await expect(page.getByRole('heading', { name: TEST_VEHICLE.nickname })).toBeVisible({ timeout: 15000 })
    await page.getByRole('button', { name: 'Edit', exact: true }).click()
    await page.getByRole('button', { name: 'Upload Window Sticker' }).click()
    const xl = page.getByRole('dialog', { name: 'Upload Window Sticker' })
    await settled(xl)
    expect((await padding(xl)).left).toBe(0)
    await injectInsets(page, landscape)
    expect(await expectLeftOverlapOnly(xl, landscape.left)).toBeCloseTo(47 - 844 * 0.03, 1)
  })

  test('a drawer without a footer pads its body clear of the home indicator', async ({ page }) => {
    await page.setViewportSize(PHONE)
    await page.goto('/supplies')
    await page.getByRole('button', { name: 'Quick settings' }).click()
    const drawer = page.getByTestId('drawer')
    await settled(drawer)
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

  test('a legacy centred modal is centred inside the safe box', async ({ page }) => {
    // Short enough that the modal's content overflows and the cap is what sets
    // its box, so its edges land on the overlay's padding exactly.
    const viewport = { width: 1280, height: 360 }
    await page.setViewportSize(viewport)
    await page.goto(`/vehicles/${TEST_VEHICLE.vin}`)
    await expect(page.getByRole('heading', { name: TEST_VEHICLE.nickname })).toBeVisible({ timeout: 15000 })
    await page.getByRole('button', { name: 'Remove', exact: true }).click()

    const overlay = page
      .locator('div.fixed.inset-0')
      .filter({ has: page.getByRole('heading', { name: 'Remove Vehicle' }) })
    await expect(overlay).toBeVisible()
    const box = overlay.locator('> div')

    // p-4, unchanged where the inset is 0.
    const base = { top: 16, right: 16, bottom: 16, left: 16 }
    expect(await padding(overlay)).toEqual(base)
    expect(await box.boundingBox()).toMatchObject({ y: base.top, height: viewport.height - base.top - base.bottom })

    await injectInsets(page)
    const inset = grown(base, ['top', 'right', 'bottom', 'left'])
    expect(await padding(overlay)).toEqual(inset)
    expect(await box.boundingBox()).toMatchObject({ y: inset.top, height: viewport.height - inset.top - inset.bottom })
  })
})
