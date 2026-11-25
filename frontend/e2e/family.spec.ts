import { request as apiRequest, type APIRequestContext, type Locator, type Page } from '@playwright/test'

import { test, expect } from './helpers/fixtures'
import { adminSessionFromStorageState } from './helpers/seed'

/**
 * Family is a drawer, and Add user and Delete user open as nested drawers over
 * it. jsdom can't see inert, so this types into the nested form for real and
 * checks its Save takes a real click.
 */

const ROOT_BASE_URL = 'http://localhost:3000'
const API_BASE = `${ROOT_BASE_URL}/api`
const AUTH_FILE = './e2e/.auth/user.json'

const SUFFIX = Date.now().toString(36)
const THROWAWAY = {
  username: `e2e-family-${SUFFIX}`,
  email: `e2e-family-${SUFFIX}@mygarage.dev`,
  full_name: `E2E Family ${SUFFIX}`,
  password: 'E2eTest!ng123',
}

let api: APIRequestContext
let headers: Record<string, string> = {}
// Whatever multi_user_enabled was before, so afterAll can put it back. Undefined means no row.
let priorMultiUser: string | undefined
let throwawayId: number | null = null

test.beforeAll(async () => {
  api = await apiRequest.newContext({ baseURL: ROOT_BASE_URL })
  headers = (await adminSessionFromStorageState(api, API_BASE, AUTH_FILE)).headers

  const settings = await api.get(`${API_BASE}/settings`, { headers })
  expect(settings.ok(), await settings.text()).toBe(true)
  const rows = (await settings.json()).settings as { key: string; value: string | null }[]
  priorMultiUser = rows.find((row) => row.key === 'multi_user_enabled')?.value ?? undefined

  // The backend refuses new users while multi-user is saved off.
  const on = await api.post(`${API_BASE}/settings/batch`, { headers, data: { settings: { multi_user_enabled: 'true' } } })
  expect(on.ok(), await on.text()).toBe(true)

  const created = await api.post(`${API_BASE}/auth/users`, { headers, data: THROWAWAY })
  expect(created.status(), await created.text()).toBe(201)
  throwawayId = (await created.json()).id
})

test.afterAll(async () => {
  try {
    try {
      if (throwawayId !== null) {
        const gone = await api.delete(`${API_BASE}/auth/users/${throwawayId}`, { headers })
        // 404 means the delete test already got it.
        expect([204, 200, 404]).toContain(gone.status())
      }
    } finally {
      // Its own finally, so a failed user cleanup still puts the setting back.
      const restored = priorMultiUser === undefined
        ? await api.delete(`${API_BASE}/settings/multi_user_enabled`, { headers })
        : await api.post(`${API_BASE}/settings/batch`, { headers, data: { settings: { multi_user_enabled: priorMultiUser } } })
      expect(restored.ok(), await restored.text()).toBeTruthy()
    }
  } finally {
    await api?.dispose()
  }
})

/** Whether a real click on the middle of this element would land on it. */
async function hitsItself(el: Locator): Promise<boolean> {
  return el.evaluate((node) => {
    const box = node.getBoundingClientRect()
    const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2)
    return hit !== null && node.contains(hit)
  })
}

/** Settings > System > Manage Family, and hands back the Family drawer. */
async function openFamily(page: Page): Promise<Locator> {
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Manage Family', exact: true }).click()
  const family = page.getByRole('dialog', { name: 'Family Management' })
  await expect(family).toBeVisible({ timeout: 15000 })
  await expect(family.getByText(THROWAWAY.full_name)).toBeVisible({ timeout: 15000 })
  return family
}

test.describe('Family drawers', () => {
  test('Add user is a live nested drawer, and Esc leaves Family open', async ({ page }) => {
    const family = await openFamily(page)
    await family.getByRole('button', { name: 'Add User' }).click()

    const addUser = page.getByRole('dialog', { name: 'Add User' })
    await expect(addUser).toBeVisible()
    await expect(family).toHaveAttribute('inert', '')

    // The username field is the first text input, and focus lands there.
    const username = addUser.locator('input[type="text"]').first()
    await username.click()
    await username.pressSequentially('typed-by-e2e', { delay: 20 })
    await expect(username).toHaveValue('typed-by-e2e')

    // The inert trap: out of #root, under no inert ancestor, and a real click lands on it.
    const save = addUser.getByRole('button', { name: 'Create', exact: true })
    const live = await save.evaluate((el) => ({
      outsideRoot: !document.getElementById('root')!.contains(el),
      notInert: el.closest('[inert]') === null,
    }))
    expect(live).toEqual({ outsideRoot: true, notInert: true })
    // Polled, since the drawer may still be sliding in. Something parked on top never lets it pass.
    await expect.poll(() => hitsItself(save), { message: 'a click on Save lands on something else' }).toBe(true)

    await page.keyboard.press('Escape')
    await expect(addUser).toBeHidden()
    await expect(family).toBeVisible()
    await expect(family).not.toHaveAttribute('inert')
  })

  test('a cancelled Add user is dead on its way out, and Family takes keys straight away', async ({ page }) => {
    // Slow the slide-out right down, so there's a window to poke at.
    await page.addStyleTag({ content: ':root { --duration-drawer: 2s !important }' })
    const family = await openFamily(page)
    const addButton = family.getByRole('button', { name: 'Add User' })
    await addButton.click()
    const addUser = page.getByRole('dialog', { name: 'Add User' })
    await expect(addUser).toBeVisible()
    const create = addUser.getByRole('button', { name: 'Create', exact: true })
    await expect.poll(() => hitsItself(create), { message: 'Add user never finished sliding in' }).toBe(true)
    const username = addUser.locator('input[type="text"]').first()
    await username.fill('half-typed')

    const panel = await addUser.elementHandle()
    const createBox = (await create.boundingBox())!
    await addUser.getByRole('button', { name: 'Cancel' }).click()

    // Still on screen and sliding, but nothing in it takes a click or focus.
    const exiting = await panel!.evaluate((el, box) => {
      const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2)
      return {
        stillThere: el.isConnected,
        inert: el.hasAttribute('inert'),
        createTakesClick: hit !== null && el.contains(hit),
        focusInside: el.contains(document.activeElement),
      }
    }, createBox)
    expect(exiting).toEqual({ stillThere: true, inert: true, createTakesClick: false, focusInside: false })

    // Focus is back on Family's Add User, and Enter there works mid-exit: it reopens the drawer.
    await expect(addButton).toBeFocused()
    expect(await panel!.evaluate((el) => el.isConnected), 'the exit already finished, so this proved nothing').toBe(true)
    await page.keyboard.press('Enter')
    await expect(addUser).not.toHaveAttribute('inert')
    await expect(family).toHaveAttribute('inert', '')
    await page.keyboard.press('Escape')
    await expect(addUser).toBeHidden()
    await expect(family).not.toHaveAttribute('inert')
  })

  test('Delete user takes the typed token and deletes the seeded user', async ({ page }) => {
    const family = await openFamily(page)
    await family.getByRole('button', { name: `Delete user: ${THROWAWAY.full_name}` }).click()

    const del = page.getByRole('dialog', { name: 'Delete User' })
    await expect(del).toBeVisible()
    await expect(del.getByText(THROWAWAY.email)).toBeVisible()
    const confirm = del.getByRole('button', { name: 'Delete User', exact: true })
    await expect(confirm).toBeDisabled()

    await del.getByPlaceholder('DELETE').fill('DELETE')
    await expect(confirm).toBeEnabled()
    await expect.poll(() => hitsItself(confirm), { message: 'a click on Delete lands on something else' }).toBe(true)
    await confirm.click()

    await expect(page.getByText('User deleted successfully')).toBeVisible()
    await expect(del).toBeHidden()
    await expect(family.getByText(THROWAWAY.full_name)).toBeHidden()
    throwawayId = null
  })
})
