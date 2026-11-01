import { request as apiRequest, type APIRequestContext, type Locator, type Page } from '@playwright/test'

import { test, expect } from './helpers/fixtures'
import { adminSessionFromStorageState, randomVin, seedLedger, type SeedLedger } from './helpers/seed'

/**
 * Card text you can select, in a real browser (#179).
 *
 * The vitest suites pin the STRUCTURE: the handler on the card, nothing
 * stretched over it, the guard on a click that ends a selection. They can't pin
 * STACKING, because jsdom has no layout, so `elementFromPoint` there answers
 * nothing useful and a long-press doesn't exist. That's the half that regressed
 * twice, a transparent button or a stretched `::after` lying over the very VIN
 * people wanted to copy, and it's what this file checks.
 *
 * Per value: the value is the top element at its own centre (what a long-press
 * or a drag lands on), a drag across it selects it without firing the card, and
 * a plain click still does what the card does. Then a control inside a card
 * does its own thing only, and the same hit tests at phone size.
 */

const ROOT_BASE_URL = 'http://localhost:3000'
const API_BASE = `${ROOT_BASE_URL}/api`
const AUTH_FILE = './e2e/.auth/user.json'

/** Distinctive make and model, so no other spec's text matcher sees these cards. */
const CAR = {
  nickname: 'E2E Select Car',
  vehicle_type: 'Car',
  year: 2001,
  make: 'SelectRigMake',
  model: 'SelectRigModel',
}
const TRAILER = {
  nickname: 'E2E Select Trailer',
  vehicle_type: 'Trailer',
  year: 2002,
  make: 'SelectRigMake',
  model: 'SelectRigTrailer',
}
const TIRE = { brand: 'E2E SelectTire', dot: 'DOT4B9XE2E1225', corner: 'Front Left' }
const CONTACT = {
  business_name: 'E2E Selectable Garage',
  address: '4821 Selectable Way',
  city: 'Testville',
  state: 'TX',
  phone: '555-0179',
}
/** A one-off reminder with notes, so the Calendar's upcoming list shows a Notes button on it. */
const REMINDER = { title: 'E2E Select Reminder', notes: 'Bring the torque wrench.' }

let api: APIRequestContext
let ledger: SeedLedger
let carVin = ''
let trailerVin = ''

test.beforeAll(async () => {
  api = await apiRequest.newContext({ baseURL: ROOT_BASE_URL })
  const admin = await adminSessionFromStorageState(api, API_BASE, AUTH_FILE)
  ledger = seedLedger(api, API_BASE, admin.headers)

  carVin = await ledger.vehicle({ vin: randomVin('SELC'), ...CAR })
  trailerVin = await ledger.vehicle({ vin: randomVin('SELT'), ...TRAILER })
  await ledger.post(`/vehicles/${carVin}/tires/create-and-mount`, {
    vin: carVin,
    position: 'FL',
    brand: TIRE.brand,
    dot_code: TIRE.dot,
    tread_depth_mm: 8,
    mounted_on: '2026-04-01',
    mounted_odometer_km: 1000,
  })
  await ledger.post(`/vehicles/${trailerVin}/trailer`, { vin: trailerVin, tow_vehicle_vin: carVin })
  await ledger.addressBookEntry(CONTACT)
  // Five days out sits inside the upcoming list's 30 days in any household timezone.
  const dueDate = new Date(Date.now() + 5 * 86_400_000).toISOString().split('T')[0]
  await ledger.post(`/vehicles/${carVin}/reminders`, {
    title: REMINDER.title,
    reminder_type: 'date',
    due_date: dueDate,
    notes: REMINDER.notes,
  })
})

test.afterAll(async () => {
  // A beforeAll that threw leaves these unassigned (the types say otherwise), so
  // ?. keeps its real error from being buried under a TypeError.
  try {
    await ledger?.cleanup()
  } finally {
    await api?.dispose()
  }
})

/** Where a value's own text sits on screen, in viewport pixels. */
interface TextBox {
  left: number
  right: number
  top: number
  bottom: number
}

/**
 * Scroll the value to the middle of the viewport and measure its TEXT.
 *
 * The text, not the element: the tire DOT and the Overview VIN are block
 * elements as wide as their column, and the middle of that box can be blank
 * space past the end of the value.
 */
async function textBox(value: Locator): Promise<TextBox> {
  await expect(value).toBeVisible({ timeout: 15000 })
  return value.evaluate((element) => {
    element.scrollIntoView({ block: 'center', inline: 'center' })
    const range = document.createRange()
    range.selectNodeContents(element)
    const rect = range.getBoundingClientRect()
    return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom }
  })
}

/**
 * What `elementFromPoint` finds at the centre of the value's text.
 *
 * This is the check jsdom can't make. A long-press or a drag starts on whatever
 * is on top there, so if that's an overlay the text can't be selected at all.
 */
async function topElementAtCentre(value: Locator): Promise<{ onTop: boolean; found: string }> {
  await textBox(value)
  return value.evaluate((element) => {
    const range = document.createRange()
    range.selectNodeContents(element)
    const rect = range.getBoundingClientRect()
    const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)
    const found =
      hit === null
        ? 'nothing'
        : `<${hit.tagName.toLowerCase()} aria-label="${hit.getAttribute('aria-label') ?? ''}" class="${hit.getAttribute('class') ?? ''}">`
    return { onTop: hit !== null && element.contains(hit), found }
  })
}

/**
 * Start hearing every dialog the page mounts.
 *
 * "No drawer opened" read once can run before a slow drawer mounts or after a
 * quick one has gone, so this records each mount by its label instead.
 */
async function recordDialogs(page: Page): Promise<void> {
  await page.evaluate(() => {
    const seen: string[] = []
    ;(window as unknown as { __e2eDialogs: string[] }).__e2eDialogs = seen
    new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (!(node instanceof Element)) continue
          const dialogs = node.matches('[role="dialog"]')
            ? [node]
            : Array.from(node.querySelectorAll('[role="dialog"]'))
          for (const dialog of dialogs) seen.push(dialog.getAttribute('aria-label') ?? '')
        }
      }
    }).observe(document.body, { childList: true, subtree: true })
  })
}

/** The labels of every dialog mounted since `recordDialogs`. */
async function dialogsSeen(page: Page): Promise<string[]> {
  return page.evaluate(() => (window as unknown as { __e2eDialogs?: string[] }).__e2eDialogs ?? [])
}

/** Long enough for a click's drawer to mount or a navigation to commit. */
const SETTLE_MS = 500

/** Mouse down at the value's left edge, across to its right edge, up. */
async function dragAcross(page: Page, value: Locator): Promise<void> {
  const box = await textBox(value)
  const y = (box.top + box.bottom) / 2
  await page.mouse.move(box.left + 1, y)
  await page.mouse.down()
  await page.mouse.move(box.right - 1, y, { steps: 12 })
  await page.mouse.up()
}

/** A plain click at the middle of the value's text, wherever that lands. */
async function clickCentre(page: Page, value: Locator): Promise<void> {
  const box = await textBox(value)
  await page.mouse.click((box.left + box.right) / 2, (box.top + box.bottom) / 2)
}

/**
 * A mouse click at the middle of a control's box. The mouse, not
 * `locator.click()`: that one waits for whatever covers the control to move,
 * and something covering it is the thing under test.
 */
async function clickCentreOf(page: Page, control: Locator): Promise<void> {
  await control.scrollIntoViewIfNeeded()
  const box = await control.boundingBox()
  if (box === null) throw new Error('the control has no box, so it is not on screen')
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2)
}

/**
 * Open a vehicle page and wait for its last late block. The key-facts strip
 * mounts only once the detail stats land, and it pushes every card below it
 * down about 90px. A value measured before that moves before the mouse gets
 * there, so a drag lands on blank card and reads as a click (the one CI flake).
 */
async function openVehicle(page: Page, path: string): Promise<void> {
  await page.goto(path)
  await expect(page.getByRole('group', { name: 'Last Fill-up' })).toBeVisible({ timeout: 15000 })
}

/** What a plain click on a card does. */
type CardAction = { kind: 'drawer'; name: string } | { kind: 'navigate'; path: () => string } | { kind: 'nothing' }

/** One value people copy out of a card, and the card around it. */
interface Target {
  name: string
  /** Go where the value is. `phone` is true in the phone-size block. */
  open: (page: Page, phone: boolean) => Promise<void>
  value: (page: Page) => Locator
  text: () => string
  click: CardAction
  /**
   * The checks this target already passed before ClickableCard. Those are
   * guards, so each names the mutant that kills it. A check with no entry here
   * failed back then, on the bug itself.
   */
  guards: Partial<Record<'onTop' | 'drag' | 'click', string>>
}

/** Mark a test that passed before the fix as a guard, with the mutant that kills it. */
function markGuard(mutant: string | undefined): void {
  if (mutant !== undefined) test.info().annotations.push({ type: 'guard', description: mutant })
}

const NEVER_ACTIVATES = 'ClickableCard never calls onActivate'
const FULL_CARD_SPAN = "an `absolute inset-0 z-10` span back inside ClickableCard, over the card's text"
const HERO_POINTER_EVENTS = "`pointer-events-none` back on VehicleHero's text layer"
const DASHBOARD_UNLIFTED =
  "the dashboard card's name/VIN overlay loses `z-10`, so the footer button's stretched `::after` covers it"

const TARGETS: Target[] = [
  {
    name: 'tire card DOT',
    open: async (page) => {
      await openVehicle(page, `/vehicles/${carVin}?tab=tires`)
    },
    value: (page) =>
      page.locator('.rounded-card', { hasText: TIRE.brand }).getByText(TIRE.dot, { exact: true }),
    text: () => TIRE.dot,
    click: { kind: 'drawer', name: `History (${TIRE.corner})` },
    // The old full-card button opened the history too, so the click was never broken.
    guards: { click: NEVER_ACTIVATES },
  },
  {
    name: 'contact card address',
    open: async (page) => {
      await page.goto('/address-book')
    },
    value: (page) =>
      page
        .locator('.rounded-card', { hasText: CONTACT.business_name })
        .getByText(CONTACT.address, { exact: true }),
    text: () => CONTACT.address,
    click: { kind: 'drawer', name: 'Edit Contact' },
    // Same: the stretched `::after` opened the editor, it just sat over the address.
    guards: { click: NEVER_ACTIVATES },
  },
  {
    name: 'Overview VIN (EditableCard)',
    open: async (page) => {
      await openVehicle(page, `/vehicles/${carVin}`)
    },
    value: (page) =>
      page
        .locator('.rounded-card', { has: page.getByRole('heading', { name: 'Basic Information' }) })
        .getByText(carVin, { exact: true }),
    text: () => carVin,
    click: { kind: 'drawer', name: 'Edit Basic Information' },
    // EditableCard already had the card-level handler before ClickableCard, so all three are guards.
    guards: {
      onTop: FULL_CARD_SPAN,
      drag: 'ClickableCard drops its isSelectingText() check',
      click: NEVER_ACTIVATES,
    },
  },
  {
    name: 'hero VIN',
    open: async (page) => {
      await openVehicle(page, `/vehicles/${carVin}`)
    },
    value: (page) =>
      page
        .getByRole('heading', { level: 1, name: CAR.nickname })
        .locator('xpath=..')
        .getByText(carVin, { exact: true }),
    text: () => carVin,
    // VehicleHero has no click target at all, so a click there must do nothing.
    click: { kind: 'nothing' },
    // Fixed in an earlier pass on #179, so guards here.
    guards: {
      onTop: HERO_POINTER_EVENTS,
      drag: HERO_POINTER_EVENTS,
      click: 'VehicleHero grows a click handler that changes the URL',
    },
  },
  {
    name: 'dashboard card VIN',
    open: async (page, phone) => {
      if (!phone) {
        await page.goto('/')
        return
      }
      // A phone session lands on Quick Entry first; its Dashboard link is the
      // way back, and it marks the session so "/" stops redirecting.
      await page.goto('/quick-entry')
      await page.getByRole('link', { name: 'Dashboard' }).click()
      await expect(page).toHaveURL(/\/$/, { timeout: 10000 })
    },
    value: (page) => page.locator('article', { hasText: carVin }).getByText(carVin, { exact: true }),
    text: () => carVin,
    click: { kind: 'navigate', path: () => `/vehicles/${carVin}` },
    // Also fixed in an earlier pass on #179, so guards too.
    guards: {
      onTop: DASHBOARD_UNLIFTED,
      drag: 'the overlay calls handleClick without unlessSelectingText',
      click: 'the overlay loses its onClick',
    },
  },
]

test.describe('Card text stays selectable (#179)', () => {
  for (const target of TARGETS) {
    test(`${target.name}: the value is the top element at its own centre`, async ({ page }) => {
      markGuard(target.guards.onTop)
      await target.open(page, false)
      const hit = await topElementAtCentre(target.value(page))
      expect(hit.onTop, `elementFromPoint at the ${target.name} found ${hit.found}`).toBe(true)
    })

    test(`${target.name}: a drag across it selects it and fires nothing`, async ({ page }) => {
      markGuard(target.guards.drag)
      await target.open(page, false)
      const value = target.value(page)
      await textBox(value)
      await recordDialogs(page)
      const urlBefore = page.url()

      await dragAcross(page, value)
      await page.waitForTimeout(SETTLE_MS)

      // Soft, so one run reports the selection AND whatever the card did.
      const selected = await page.evaluate(() => window.getSelection()?.toString() ?? '')
      expect.soft(selected, 'the drag selected the value').toContain(target.text())
      expect.soft(await dialogsSeen(page), 'the drag opened a drawer').toEqual([])
      expect.soft(page.url(), 'the drag navigated').toBe(urlBefore)
    })

    test(`${target.name}: a plain click ${target.click.kind === 'nothing' ? 'does nothing' : 'still works the card'}`, async ({
      page,
    }) => {
      markGuard(target.guards.click)
      await target.open(page, false)
      const value = target.value(page)
      await textBox(value)
      await recordDialogs(page)
      const urlBefore = page.url()

      await clickCentre(page, value)

      const action = target.click
      if (action.kind === 'drawer') {
        await expect(page.getByRole('dialog', { name: action.name })).toBeVisible({ timeout: 5000 })
      } else if (action.kind === 'navigate') {
        await expect(page).toHaveURL(new RegExp(`${action.path()}$`), { timeout: 10000 })
      } else {
        await page.waitForTimeout(SETTLE_MS)
        expect(await dialogsSeen(page), 'the click opened a drawer').toEqual([])
        expect(page.url(), 'the click navigated').toBe(urlBefore)
      }
    })
  }

  /**
   * Guard: it passed before ClickableCard too, when Edit sat on `z-10` above a
   * sibling overlay that couldn't hear it. Killed by ClickableCard dropping its
   * cameFromNestedControl check, which lets the click bubble into the card.
   */
  test('tire card: Edit opens the editor and not the history', async ({ page }) => {
    markGuard('ClickableCard drops its cameFromNestedControl check')
    await openVehicle(page, `/vehicles/${carVin}?tab=tires`)
    const card = page.locator('.rounded-card', { hasText: TIRE.brand })
    await expect(card).toBeVisible({ timeout: 15000 })
    await recordDialogs(page)

    await card.getByRole('button', { name: 'Edit', exact: true }).click()

    const editor = `${TIRE.corner} Tire`
    await expect(page.getByRole('dialog', { name: editor })).toBeVisible({ timeout: 5000 })
    await page.waitForTimeout(SETTLE_MS)
    expect(await dialogsSeen(page)).toEqual([editor])
  })

  /**
   * Browser pass BP-1. Focused, the keyboard button shows as a chip in the
   * card's top-right corner, over the card's own Edit button, and it took the
   * mouse click meant for Edit. Seen after a History drawer opened from the
   * keyboard closed and handed focus back to that button.
   */
  test('tire card: with the keyboard button focused, a click on Edit opens the editor', async ({
    page,
  }) => {
    await openVehicle(page, `/vehicles/${carVin}?tab=tires`)
    const card = page.locator('.rounded-card', { hasText: TIRE.brand })
    await expect(card).toBeVisible({ timeout: 15000 })
    const keyboardButton = card.getByRole('button', { name: /^View reading history for/ })
    await keyboardButton.focus()
    await expect(keyboardButton).toBeFocused()
    await recordDialogs(page)

    await clickCentreOf(page, card.getByRole('button', { name: 'Edit', exact: true }))

    const editor = `${TIRE.corner} Tire`
    await expect(page.getByRole('dialog', { name: editor })).toBeVisible({ timeout: 5000 })
    await page.waitForTimeout(SETTLE_MS)
    expect(await dialogsSeen(page), 'the focus chip took the click').toEqual([editor])
  })

  /** The Calendar's upcoming list carries the same chip over its Notes button. */
  test('calendar item: with the keyboard button focused, a click on Notes shows the notes', async ({
    page,
  }) => {
    await page.goto('/calendar')
    const keyboardButton = page.getByRole('button', { name: `Open ${REMINDER.title}`, exact: true })
    await expect(keyboardButton).toBeAttached({ timeout: 15000 })
    // The keyboard button's chip wrapper, then the upcoming item it sits in.
    const item = keyboardButton.locator('xpath=../..')
    await keyboardButton.focus()
    await expect(keyboardButton).toBeFocused()
    const urlBefore = page.url()

    await clickCentreOf(page, item.getByRole('button', { name: 'View notes', exact: true }))

    await expect(page.getByRole('heading', { name: 'Event Notes' })).toBeVisible({ timeout: 5000 })
    await page.waitForTimeout(SETTLE_MS)
    expect(page.url(), 'the focus chip took the click and opened the event').toBe(urlBefore)
  })

  /**
   * Guard: the old card root had no handler and the link sat above the stretched
   * button, so this passed before ClickableCard too. Same mutant as Edit above.
   */
  test('contact card: the phone link dials and does not open the editor', async ({ page }) => {
    markGuard('ClickableCard drops its cameFromNestedControl check')
    await page.goto('/address-book')
    const card = page.locator('.rounded-card', { hasText: CONTACT.business_name })
    await expect(card).toBeVisible({ timeout: 15000 })
    await recordDialogs(page)
    // Heard on the window, after React's own handlers, then stopped there: the
    // dialler is the link's own thing, and headless Chromium has no dialler.
    await page.evaluate(() => {
      window.addEventListener('click', (event) => {
        const link = event.target instanceof Element ? event.target.closest('a[href^="tel:"]') : null
        if (link === null) return
        ;(window as unknown as { __e2eTel: unknown }).__e2eTel = {
          href: link.getAttribute('href'),
          defaultPrevented: event.defaultPrevented,
        }
        event.preventDefault()
      })
    })
    const urlBefore = page.url()

    await card.getByRole('link', { name: CONTACT.phone }).click()
    await page.waitForTimeout(SETTLE_MS)

    const tel = await page.evaluate(() => (window as unknown as { __e2eTel?: unknown }).__e2eTel)
    expect(tel, 'the click reached the link with its default intact').toEqual({
      href: `tel:${CONTACT.phone}`,
      defaultPrevented: false,
    })
    expect(await dialogsSeen(page), 'the phone link opened the editor').toEqual([])
    expect(page.url()).toBe(urlBefore)
  })

  /**
   * Before the nested-control rule the link's click bubbled into EditableCard's
   * handler, so the pairing editor mounted on the way out. Only the dialog
   * recorder sees that: the navigation tears it straight back down.
   */
  test('trailer card: the tow vehicle link navigates and does not open the editor', async ({
    page,
  }) => {
    await page.goto(`/vehicles/${trailerVin}`)
    const card = page.locator('.rounded-card', {
      has: page.getByRole('heading', { name: 'Trailer & Tow Vehicle' }),
    })
    const link = card.getByRole('link', { name: CAR.nickname })
    await expect(link).toBeVisible({ timeout: 15000 })
    await recordDialogs(page)

    await link.click()

    await expect(page).toHaveURL(new RegExp(`/vehicles/${carVin}$`), { timeout: 10000 })
    await expect(page.getByRole('heading', { level: 1, name: CAR.nickname })).toBeVisible({
      timeout: 15000,
    })
    await page.waitForTimeout(SETTLE_MS)
    expect(await dialogsSeen(page), 'the tow link also opened the pairing editor').toEqual([])
  })
})

test.describe('Card text stays selectable on a phone (#179)', () => {
  test.use({ hasTouch: true, isMobile: true, viewport: { width: 412, height: 915 } })

  for (const target of TARGETS) {
    test(`${target.name}: the value is the top element at its own centre`, async ({ page }) => {
      // The same stacking, so the same guards and mutants as the desktop check.
      markGuard(target.guards.onTop)
      await target.open(page, true)
      const hit = await topElementAtCentre(target.value(page))
      expect(hit.onTop, `elementFromPoint at the ${target.name} found ${hit.found}`).toBe(true)
    })
  }
})

test.describe('Window sticker test page (#179)', () => {
  test('Remove clears the chosen file and does not open the file picker', async ({ page }) => {
    await page.goto(`/vehicles/${carVin}/window-sticker-test`)
    await page.locator('input[type="file"]').setInputFiles({
      name: 'e2e-sticker.png',
      mimeType: 'image/png',
      buffer: Buffer.from('not really a png'),
    })
    await expect(page.getByText('e2e-sticker.png')).toBeVisible({ timeout: 10000 })

    const remove = page.getByRole('button', { name: 'Remove', exact: true })
    const hit = await topElementAtCentre(remove)
    expect.soft(hit.onTop, `elementFromPoint at Remove found ${hit.found}`).toBe(true)

    let pickerOpened = false
    page.on('filechooser', () => {
      pickerOpened = true
    })
    // At the button's spot rather than `remove.click()`, which would wait out
    // anything covering it instead of clicking what a person actually hits.
    await clickCentre(page, remove)
    await page.waitForTimeout(SETTLE_MS)

    expect.soft(pickerOpened, 'Remove opened the file picker').toBe(false)
    await expect(page.getByText('e2e-sticker.png')).toHaveCount(0)
  })
})
