import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '../../__tests__/test-utils'
import VehicleWizard from '../VehicleWizard'
import { FUEL_TYPE_VALUES } from '../../constants/fuel'
import type { VINDecodeResponse } from '../../types/vin'

// VIN decode/validate/duplicate-check network calls — mocked so the wizard's
// VINInput child never hits the real API.
vi.mock('@/services/vinService', () => ({
  vinService: {
    validate: vi.fn().mockResolvedValue({ valid: true, vin: '1HGCM82633A004352' }),
    decode: vi.fn(),
    exists: vi.fn().mockResolvedValue(false),
  },
}))

// The wizard's review step formats the purchase price via useCurrencyPreference(),
// which reads the signed-in user through useAuth(). The shared test render has no
// AuthProvider, so stub the context module out.
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: null }),
}))

// Not exercised by these tests (only hit on final submit), but the module is
// imported at the top of VehicleWizard.tsx.
vi.mock('../../services/vehicleService', () => ({
  default: {
    create: vi.fn(),
    uploadPhoto: vi.fn(),
    setMainPhoto: vi.fn(),
  },
}))

import { vinService } from '@/services/vinService'

const mockedVinService = vi.mocked(vinService)
const TEST_VIN = '1HGCM82633A004352'

function renderAndEnterVin(): void {
  render(<VehicleWizard onClose={vi.fn()} />)

  const vinInput = screen.getByPlaceholderText('vinInput.placeholder')
  fireEvent.change(vinInput, { target: { value: TEST_VIN } })
}

async function goToStep2(): Promise<void> {
  renderAndEnterVin()

  const nextButton = await screen.findByRole('button', { name: 'wizard.next' })
  await waitFor(() => expect(nextButton).not.toBeDisabled())
  fireEvent.click(nextButton)

  await screen.findByLabelText('wizard.fuelType')
}

async function decodeWithEngine(engine: VINDecodeResponse['engine']): Promise<void> {
  mockedVinService.decode.mockResolvedValue({
    vin: TEST_VIN,
    year: 2020,
    make: 'Ford',
    model: 'Escape',
    engine,
  })

  renderAndEnterVin()

  const decodeButton = await screen.findByRole('button', { name: 'vinInput.decode' })
  await waitFor(() => expect(decodeButton).not.toBeDisabled())
  fireEvent.click(decodeButton)

  await waitFor(() => expect(mockedVinService.decode).toHaveBeenCalledWith(TEST_VIN))

  const nextButton = await screen.findByRole('button', { name: 'wizard.next' })
  fireEvent.click(nextButton)

  await screen.findByLabelText('wizard.fuelType')
}

describe('VehicleWizard — canonical fuel-type select', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedVinService.validate.mockResolvedValue({ valid: true, vin: TEST_VIN })
    mockedVinService.exists.mockResolvedValue(false)
  })

  it('renders a select with the empty option plus all 10 canonical fuel types', async () => {
    await goToStep2()

    const select = screen.getByLabelText('wizard.fuelType') as HTMLSelectElement
    const options = Array.from(select.options)

    expect(options).toHaveLength(FUEL_TYPE_VALUES.length + 1)
    expect(options[0].value).toBe('')

    FUEL_TYPE_VALUES.forEach((value, index) => {
      const option = options[index + 1]
      expect(option.value).toBe(value)
      // The option label is rendered via t(`forms:fuel.fuelTypes.${value}`);
      // under the vitest i18n mock (t: key => key) that resolves to the key.
      expect(option.textContent).toBe(`forms:fuel.fuelTypes.${value}`)
    })
  })

  it('prefills fuel_type from the NHTSA-normalized value, not the raw string', async () => {
    await decodeWithEngine({
      displacement_l: '2.0',
      cylinders: 4,
      fuel_type: 'Gasoline/E85 (dual fuel)',
      fuel_type_normalized: 'e85',
    })

    const select = screen.getByLabelText('wizard.fuelType') as HTMLSelectElement
    expect(select.value).toBe('e85')
  })

  it('falls back to the empty selection when NHTSA normalization failed', async () => {
    await decodeWithEngine({
      displacement_l: '2.0',
      cylinders: 4,
      fuel_type: 'Not Applicable',
      fuel_type_normalized: null,
    })

    const select = screen.getByLabelText('wizard.fuelType') as HTMLSelectElement
    expect(select.value).toBe('')
  })

  it('renders as a Drawer with the step-progress subtitle and closes', () => {
    const onClose = vi.fn()
    render(<VehicleWizard onClose={onClose} />)

    // Drawer shell.
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    // First body row: the "Step X of 4" progress subtitle (key under the i18n mock).
    expect(screen.getByText('wizard.misc.stepProgress')).toBeInTheDocument()
    // The Drawer's built-in close button (aria-label = common:close) fires onClose.
    fireEvent.click(screen.getByRole('button', { name: 'common:close' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('advances to step 2 via the Next button lifted into the Drawer footer', async () => {
    renderAndEnterVin()

    const nextButton = await screen.findByRole('button', { name: 'wizard.next' })
    // Prove the control lives in the Drawer's <footer> slot, not the body.
    expect(nextButton.closest('footer')).not.toBeNull()

    await waitFor(() => expect(nextButton).not.toBeDisabled())
    fireEvent.click(nextButton)
    // Step 2 heading proves the footer click advanced the wizard.
    expect(await screen.findByText('edit.vehicleDetails')).toBeInTheDocument()
  })
})
