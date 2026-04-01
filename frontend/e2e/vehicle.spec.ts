import { test, expect } from './helpers/fixtures'
import { TEST_VEHICLE, toast } from './helpers/selectors'

test.describe('Vehicle Management', () => {
  test('add vehicle button opens wizard modal', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('button', { name: /add vehicle/i })).toBeVisible({
      timeout: 15000,
    })

    await page.getByRole('button', { name: /add vehicle/i }).click()

    // The add vehicle wizard should appear with a VIN input step
    await expect(page.getByText('Enter VIN')).toBeVisible({ timeout: 10000 })
  })

  test('vehicle detail page shows 404 for nonexistent VIN', async ({ page }) => {
    await page.goto('/vehicles/1G1YY22G965104385')

    // Should show error or not found state
    await expect(
      page.getByText(/not found|error|failed/i)
    ).toBeVisible({ timeout: 15000 })
  })

  test('seeded test vehicle appears on dashboard', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { name: /garage/i })).toBeVisible({
      timeout: 15000,
    })

    // The dashboard card shows year/make/model, not the nickname
    await expect(
      page.getByText(`${TEST_VEHICLE.year} ${TEST_VEHICLE.make} ${TEST_VEHICLE.model}`)
    ).toBeVisible({ timeout: 10000 })
  })

  test('clicking vehicle card navigates to detail page', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { name: /garage/i })).toBeVisible({
      timeout: 15000,
    })

    // Click the vehicle card (contains the VIN text)
    await page.getByText(TEST_VEHICLE.vin).click()

    // Should navigate to vehicle detail
    await expect(page).toHaveURL(`/vehicles/${TEST_VEHICLE.vin}`, { timeout: 10000 })
    await expect(
      page.getByRole('heading', { name: TEST_VEHICLE.nickname })
    ).toBeVisible({ timeout: 10000 })
  })

  test('vehicle detail page loads for seeded vehicle', async ({ page }) => {
    await page.goto(`/vehicles/${TEST_VEHICLE.vin}`)

    // Wait for vehicle detail header to load (nickname is the h1)
    await expect(
      page.getByRole('heading', { name: TEST_VEHICLE.nickname })
    ).toBeVisible({ timeout: 15000 })

    // VIN should be displayed in the header area (use first match to avoid strict-mode on the overview panel)
    await expect(page.getByText(TEST_VEHICLE.vin).first()).toBeVisible()

    // Year/make/model should appear in the subtitle area
    await expect(
      page.getByText(`${TEST_VEHICLE.year} ${TEST_VEHICLE.make} ${TEST_VEHICLE.model}`)
    ).toBeVisible()
  })
})

test.describe('Vehicle Lifecycle — Add via Wizard', () => {
  const WIZARD_VIN = 'JH4KA7561PC008843' // valid 17-char VIN (Honda Vigor)

  test('complete wizard flow: VIN -> Details -> skip photos -> review -> create', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('button', { name: /add vehicle/i })).toBeVisible({
      timeout: 15000,
    })

    // Open wizard
    await page.getByRole('button', { name: /add vehicle/i }).click()
    await expect(page.getByText('Enter VIN')).toBeVisible({ timeout: 10000 })

    // Step 1: Enter VIN
    const vinInput = page.getByPlaceholder('Enter 17-character VIN')
    await vinInput.fill(WIZARD_VIN)
    await expect(page.getByText('17/17 characters')).toBeVisible()

    // Wait for auto-validation to complete
    await page.waitForTimeout(2000)

    // Next -> Step 2 (Details)
    await page.getByRole('button', { name: /next/i }).click()
    await expect(page.getByText('Vehicle Details')).toBeVisible({ timeout: 5000 })

    // Fill required fields
    const nicknameInput = page.locator('input[name="nickname"]')
    await nicknameInput.clear()
    await nicknameInput.fill('E2E Wizard Car')

    // Vehicle type should default to "Car" — leave it

    // Next -> Step 3 (Photos — skip)
    await page.getByRole('button', { name: /next/i }).click()
    await expect(
      page.getByRole('heading', { name: /add photos/i })
    ).toBeVisible({ timeout: 5000 })

    // Next -> Step 4 (Review)
    await page.getByRole('button', { name: /next/i }).click()
    await expect(
      page.getByRole('heading', { name: /review/i })
    ).toBeVisible({ timeout: 5000 })

    // Verify review summary shows our data
    await expect(page.getByText(WIZARD_VIN)).toBeVisible()
    await expect(page.getByText('E2E Wizard Car')).toBeVisible()

    // Submit
    await page.getByRole('button', { name: /create vehicle/i }).click()

    // Should navigate to vehicle detail page or back to dashboard
    await expect(page).toHaveURL(new RegExp(`/vehicles/${WIZARD_VIN}|/$`), {
      timeout: 15000,
    })
  })
})

test.describe('Vehicle Archive & Restore', () => {
  // VIN must not contain I, O, or Q — use only valid VIN characters
  const ARCHIVE_VIN = 'TESTARCHV00000001'
  const ARCHIVE_NICKNAME = 'E2E Archive Target'

  test.beforeAll(async ({ request }) => {
    // Seed archive-test vehicle via API
    const loginResp = await request.post('http://localhost:8686/api/auth/login', {
      data: { username: 'e2e-admin', password: 'E2eTest!ng123' },
    })
    const loginData = await loginResp.json()
    const headers = {
      Cookie: `mygarage_token=${loginData.access_token}`,
      'X-CSRF-Token': loginData.csrf_token,
    }

    // Create or ignore if exists
    const resp = await request.post('http://localhost:8686/api/vehicles', {
      data: {
        vin: ARCHIVE_VIN,
        nickname: ARCHIVE_NICKNAME,
        vehicle_type: 'Car',
        year: 2020,
        make: 'ArchvMake',
        model: 'ArchvModel',
      },
      headers,
    })
    // 201 = created, 400/409/422 = already exists
    if (![201, 400, 409].includes(resp.status())) {
      console.error(`Archive vehicle seed failed: ${resp.status()} ${await resp.text()}`)
    }
  })

  test('archive vehicle via Remove modal', async ({ page }) => {
    await page.goto(`/vehicles/${ARCHIVE_VIN}`)
    await expect(
      page.getByRole('heading', { name: ARCHIVE_NICKNAME })
    ).toBeVisible({ timeout: 15000 })

    // Click "Remove" button (desktop) — the button contains a Trash2 icon + "Remove" text
    await page.locator('button:has-text("Remove")').click()

    // Remove modal opens — should see mode selection
    await expect(page.getByText('Remove Vehicle')).toBeVisible({ timeout: 5000 })

    // Choose "Archive (Recommended)"
    await page.getByText('Archive (Recommended)').click()

    // Archive form appears
    await expect(page.getByRole('heading', { name: 'Archive Vehicle' })).toBeVisible({ timeout: 5000 })

    // Click "Archive Vehicle" button to confirm
    await page.getByRole('button', { name: /archive vehicle/i }).click()

    // Should get success toast and navigate to dashboard
    await expect(toast.success(page)).toBeVisible({ timeout: 10000 })
    await expect(page).toHaveURL('/', { timeout: 10000 })
  })

  test('restore archived vehicle via API and verify it reappears', async ({ page, request }) => {
    // Restore via API
    const loginResp = await request.post('http://localhost:8686/api/auth/login', {
      data: { username: 'e2e-admin', password: 'E2eTest!ng123' },
    })
    const loginData = await loginResp.json()
    const headers = {
      Cookie: `mygarage_token=${loginData.access_token}`,
      'X-CSRF-Token': loginData.csrf_token,
    }

    const unarchiveResp = await request.post(
      `http://localhost:8686/api/vehicles/${ARCHIVE_VIN}/unarchive`,
      { headers }
    )
    expect(unarchiveResp.ok(), `Unarchive failed: ${unarchiveResp.status()}`).toBeTruthy()

    // Verify it appears on dashboard again (card shows year make model)
    await page.goto('/')
    await expect(page.getByText('2020 ArchvMake ArchvModel')).toBeVisible({ timeout: 15000 })
  })
})
