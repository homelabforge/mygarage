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
    providers: vi.fn().mockResolvedValue({ available: ['nhtsa'], preferred: 'nhtsa' }),
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

  await waitFor(() => expect(mockedVinService.decode.mock.calls[0]?.[0]).toBe(TEST_VIN))

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

describe('VehicleWizard — duplicate-VIN warning (issue #69)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedVinService.validate.mockResolvedValue({ valid: true, vin: TEST_VIN })
  })

  it('warns as soon as a complete VIN matches an existing vehicle', async () => {
    mockedVinService.exists.mockResolvedValue(true)
    renderAndEnterVin()

    expect(await screen.findByText('vinInput.alreadyExists')).toBeInTheDocument()
    expect(mockedVinService.exists).toHaveBeenCalledWith(TEST_VIN)
  })
})

describe('VehicleWizard: every label names its control', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedVinService.validate.mockResolvedValue({ valid: true, vin: TEST_VIN })
    mockedVinService.exists.mockResolvedValue(false)
  })

  // Label (the i18n key under the test mock) -> the RHF field its control registers.
  const STEP_2_FIELDS: Array<[string | RegExp, string]> = [
    [/^wizard\.nickname/, 'nickname'],
    [/^edit\.vehicleType/, 'vehicle_type'],
    ['wizard.year', 'year'],
    ['wizard.make', 'make'],
    ['wizard.model', 'model'],
    ['wizard.color', 'color'],
    ['edit.licensePlate', 'license_plate'],
    ['edit.purchaseDate', 'purchase_date'],
    ['edit.purchasePrice', 'purchase_price'],
    ['wizard.trim', 'trim'],
    ['edit.bodyClass', 'body_class'],
    ['edit.driveType', 'drive_type'],
    ['edit.doors', 'doors'],
    ['edit.displacement', 'displacement_l'],
    ['edit.cylinders', 'cylinders'],
    ['wizard.fuelType', 'fuel_type'],
    ['edit.transmissionType', 'transmission_type'],
    ['edit.transmissionSpeeds', 'transmission_speeds'],
  ]

  it.each(STEP_2_FIELDS)('step 2: %s resolves to the %s control', async (label, field) => {
    await goToStep2()
    expect(screen.getByLabelText(label)).toHaveAttribute('name', field)
  })

  it('the four number fields are the NumberInputs, found by their labels', async () => {
    await goToStep2()
    for (const label of ['wizard.year', 'edit.purchasePrice', 'edit.doors', 'edit.cylinders']) {
      expect(screen.getByLabelText(label)).toHaveAttribute('inputMode', 'decimal')
    }
  })

  it('step 3: the photo picker is labelled', async () => {
    await goToStep2()
    fireEvent.change(screen.getByLabelText(/^wizard\.nickname/), { target: { value: 'Tow rig' } })
    fireEvent.click(screen.getByRole('button', { name: 'wizard.next' }))
    expect(await screen.findByLabelText('wizard.misc.uploadPhotos')).toHaveAttribute('type', 'file')
  })
})

// The certificate import (#211): its hook reads the public settings through
// react-query, which the shared render does not provide; the service is the
// seam the wizard talks to.
vi.mock('@/hooks/queries/useAiDocumentReading', () => ({
  useAiDocumentReading: () => ({ enabled: false, isLoading: false }),
}))
vi.mock('../../services/registrationCertificateService', () => {
  // One object behind both exports: the wizard imports the default, the
  // import component the named one, and the test programs `parse` once.
  const service = {
    parse: vi.fn(),
    importForVehicle: vi.fn(),
  }
  return {
  default: service,
  registrationCertificateService: service,
  AI_READING_NOT_CONFIGURED: 'ai_reading_not_configured',
  CERTIFICATE_ACCEPT: 'application/pdf',
  CERTIFICATE_MIME_TYPES: ['application/pdf'],
  CERTIFICATE_MAX_BYTES: 25 * 1024 * 1024,
  isAiNotConfigured: () => false,
  visionConsentHost: vi.fn(() => null),
  isPdf: (file: File) => file.type === 'application/pdf',
  }
})

import registrationCertificateService, { visionConsentHost } from '../../services/registrationCertificateService'
import vehicleService from '../../services/vehicleService'

describe('VehicleWizard — registration certificate (#211)', () => {
  const CERTIFICATE_VIN = 'VF1RFB00X56123456'
  const PARSE = {
    source: 'text',
    country: 'FR',
    confidence: 100,
    fields: { vin: CERTIFICATE_VIN, plate: 'AB-123-CD', taxes: {} },
    field_confidence: {},
    vehicle_patch: {
      vin: CERTIFICATE_VIN,
      license_plate: 'AB-123-CD',
      first_registration_date: '2023-03-12',
      make: 'RENAULT',
      model: 'CLIO',
      fuel_type: 'gasoline',
      vehicle_type: 'Car',
      registration_country: 'FR',
      power_kw: 74,
      fiscal_power: 5,
    },
    inspection_due_date: '2026-02-10',
    suggested_tax_records: [{ code: 'Y.1', tax_type: 'registration_tax', amount: '162.50', date: '2023-03-12' }],
    warnings: [],
    model: null,
    pages: 0,
  }

  it('fills the VIN and the step-2 fields from the certificate and moves on', async () => {
    vi.mocked(registrationCertificateService.parse).mockResolvedValue(PARSE as never)
    render(<VehicleWizard onClose={vi.fn()} />)

    const file = new File(['%PDF-1.4'], 'carte-grise.pdf', { type: 'application/pdf' })
    fireEvent.change(screen.getByTestId('registration-certificate-file'), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'registrationImport.read' }))

    // Step 2 opens with the notice to check the values…
    expect(await screen.findByText('registrationImport.checkFields')).toBeInTheDocument()
    // …and the certificate's values in the form, still editable.
    expect(screen.getByPlaceholderText('wizard.misc.licensePlatePlaceholder')).toHaveValue('AB-123-CD')
    expect(screen.getByPlaceholderText('wizard.misc.nicknamePlaceholder')).toHaveValue('2023 RENAULT CLIO')
    expect(screen.getByLabelText('wizard.fuelType')).toHaveValue('gasoline')
    // No country resolves here (no account, no instance default): the hint is absent.
    expect(registrationCertificateService.parse).toHaveBeenCalledWith(file, undefined, false)
  })

  it('files the certificate with the parse token and only the ticked taxes (B5)', async () => {
    vi.mocked(registrationCertificateService.parse).mockResolvedValue({
      ...PARSE,
      parse_token: 'tok-1',
      suggested_tax_records: [
        { code: 'Y.1', tax_type: 'registration_tax', amount: '162.50', date: '2023-03-12' },
        { code: 'Y.3', tax_type: 'co2_malus', amount: '50.00', date: '2023-03-12' },
      ],
    } as never)
    vi.mocked(vehicleService.create).mockResolvedValue({ vin: CERTIFICATE_VIN } as never)
    vi.mocked(registrationCertificateService.importForVehicle).mockResolvedValue({} as never)
    render(<VehicleWizard onClose={vi.fn()} />)

    const file = new File(['%PDF-1.4'], 'carte-grise.pdf', { type: 'application/pdf' })
    fireEvent.change(screen.getByTestId('registration-certificate-file'), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'registrationImport.read' }))
    await screen.findByText('registrationImport.checkFields')

    fireEvent.click(screen.getByRole('button', { name: 'wizard.next' }))
    await screen.findByLabelText('wizard.misc.uploadPhotos')
    fireEvent.click(screen.getByRole('button', { name: 'wizard.next' }))
    const review = await screen.findByTestId('wizard-certificate-review')
    const boxes = review.querySelectorAll('input[type="checkbox"]')
    expect(boxes).toHaveLength(2)
    fireEvent.click(boxes[0]) // untick Y.1
    fireEvent.click(screen.getByRole('button', { name: /wizard\.misc\.createVehicle/ }))

    await waitFor(() => expect(registrationCertificateService.importForVehicle).toHaveBeenCalled())
    expect(registrationCertificateService.importForVehicle).toHaveBeenCalledWith(CERTIFICATE_VIN, file, {
      parseToken: 'tok-1',
      allowExternalVision: false,
      taxCodes: ['Y.3'],
    })
  })

  it('forwards the consent given at the read to the import (FB-7)', async () => {
    // The read went to a model outside the network after a yes. Should the
    // import read the file again (an expired token), it must not ask again
    // with nobody left to answer: the wizard's toast would be all that shows.
    vi.mocked(visionConsentHost).mockReturnValueOnce('openrouter.ai')
    vi.mocked(registrationCertificateService.parse)
      .mockRejectedValueOnce(new Error('409'))
      .mockResolvedValueOnce({ ...PARSE, parse_token: 'tok-2' } as never)
    vi.mocked(vehicleService.create).mockResolvedValue({ vin: CERTIFICATE_VIN } as never)
    vi.mocked(registrationCertificateService.importForVehicle).mockResolvedValue({} as never)
    render(<VehicleWizard onClose={vi.fn()} />)

    const file = new File(['%PDF-1.4'], 'carte-grise.pdf', { type: 'application/pdf' })
    fireEvent.change(screen.getByTestId('registration-certificate-file'), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'registrationImport.read' }))
    fireEvent.click(await screen.findByRole('button', { name: 'visionConsent.send' }))
    await screen.findByText('registrationImport.checkFields')
    expect(registrationCertificateService.parse).toHaveBeenLastCalledWith(file, undefined, true)

    fireEvent.click(screen.getByRole('button', { name: 'wizard.next' }))
    await screen.findByLabelText('wizard.misc.uploadPhotos')
    fireEvent.click(screen.getByRole('button', { name: 'wizard.next' }))
    await screen.findByTestId('wizard-certificate-review')
    fireEvent.click(screen.getByRole('button', { name: /wizard\.misc\.createVehicle/ }))

    await waitFor(() => expect(registrationCertificateService.importForVehicle).toHaveBeenCalled())
    expect(registrationCertificateService.importForVehicle).toHaveBeenCalledWith(
      CERTIFICATE_VIN,
      file,
      expect.objectContaining({ parseToken: 'tok-2', allowExternalVision: true }),
    )
  })
})

describe('VehicleWizard: No VIN (#226)', () => {
  const Q_KEY = 'QABCDEFGH12345678'

  beforeEach(() => {
    vi.clearAllMocks()
    mockedVinService.validate.mockResolvedValue({ valid: true, vin: TEST_VIN })
    mockedVinService.exists.mockResolvedValue(false)
  })

  function chooseNoVin(): void {
    fireEvent.click(screen.getByRole('tab', { name: 'identifier.noVin' }))
  }

  it('gates step 1 on the identifier unless the type is none', async () => {
    render(<VehicleWizard onClose={vi.fn()} />)
    const next = screen.getByRole('button', { name: 'wizard.next' })
    expect(next).toBeDisabled()

    chooseNoVin()
    expect(screen.queryByPlaceholderText('vinInput.placeholder')).not.toBeInTheDocument()
    expect(screen.getByText('identifier.noVinHelp')).toBeInTheDocument()
    expect(next).toBeDisabled()

    const value = screen.getByLabelText(/^identifier\.valueLabel/)
    fireEvent.change(value, { target: { value: '   ' } })
    expect(next).toBeDisabled()
    fireEvent.change(value, { target: { value: 'BX23S-1' } })
    expect(next).not.toBeDisabled()

    fireEvent.change(value, { target: { value: '' } })
    expect(next).toBeDisabled()
    fireEvent.change(screen.getByLabelText('identifier.typeLabel'), { target: { value: 'none' } })
    expect(screen.queryByLabelText(/^identifier\.valueLabel/)).not.toBeInTheDocument()
    expect(next).not.toBeDisabled()

    // Back to VIN: the 17-character gate is back.
    fireEvent.click(screen.getByRole('tab', { name: 'identifier.hasVin' }))
    expect(screen.getByRole('button', { name: 'wizard.next' })).toBeDisabled()
  })

  it('offers the identifier types a vehicle without a VIN can have', () => {
    render(<VehicleWizard onClose={vi.fn()} />)
    chooseNoVin()
    const select = screen.getByLabelText('identifier.typeLabel') as HTMLSelectElement
    expect(Array.from(select.options).map((o) => o.value)).toEqual(['serial', 'hin', 'chassis', 'asset_tag', 'none'])
    expect(Array.from(select.options).map((o) => o.textContent)).toContain('vehicles:identifier.types.hin')
  })

  it('creates without a vin and uploads the photos under the key the server returns', async () => {
    vi.mocked(vehicleService.create).mockResolvedValue({ vin: Q_KEY } as never)
    vi.mocked(vehicleService.uploadPhoto).mockResolvedValue({ filename: 'a.jpg' } as never)
    vi.mocked(vehicleService.setMainPhoto).mockResolvedValue({} as never)
    const onSuccess = vi.fn()
    render(<VehicleWizard onClose={vi.fn()} onSuccess={onSuccess} />)

    chooseNoVin()
    fireEvent.change(screen.getByLabelText(/^identifier\.valueLabel/), { target: { value: '  BX23S-1 ' } })
    fireEvent.click(screen.getByRole('button', { name: 'wizard.next' }))

    await screen.findByText('edit.vehicleDetails')
    // Equipment types lead the type list when there's no VIN; the type itself is untouched.
    const typeSelect = screen.getByLabelText(/^edit\.vehicleType/) as HTMLSelectElement
    expect(typeSelect.value).toBe('Car')
    expect(Array.from(typeSelect.options).slice(0, 6).map((o) => o.value).sort()).toEqual(
      ['Attachment', 'Equipment', 'Generator', 'Mower', 'SmallEngine', 'Tractor'],
    )
    fireEvent.change(typeSelect, { target: { value: 'Tractor' } })
    fireEvent.change(screen.getByLabelText(/^wizard\.nickname/), { target: { value: 'Kubota' } })
    fireEvent.click(screen.getByRole('button', { name: 'wizard.next' }))

    const photo = new File(['jpg'], 'tractor.jpg', { type: 'image/jpeg' })
    fireEvent.change(await screen.findByLabelText('wizard.misc.uploadPhotos'), { target: { files: [photo] } })
    fireEvent.click(screen.getByRole('button', { name: 'wizard.next' }))

    const review = await screen.findByTestId('wizard-review-identifier')
    expect(review).toHaveTextContent('vehicles:identifier.types.serial')
    expect(review).toHaveTextContent('BX23S-1')
    fireEvent.click(screen.getByRole('button', { name: /wizard\.misc\.createVehicle/ }))

    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith(Q_KEY))
    const payload = vi.mocked(vehicleService.create).mock.calls[0][0]
    expect(payload).not.toHaveProperty('vin')
    expect(payload).toMatchObject({
      identifier_type: 'serial',
      identifier: 'BX23S-1',
      vehicle_type: 'Tractor',
      usage_unit: 'hours',
    })
    expect(vehicleService.uploadPhoto).toHaveBeenCalledWith(Q_KEY, photo)
    expect(vehicleService.setMainPhoto).toHaveBeenCalledWith(Q_KEY, 'a.jpg')
  })

  it('sends a null identifier for "none"', async () => {
    vi.mocked(vehicleService.create).mockResolvedValue({ vin: Q_KEY } as never)
    render(<VehicleWizard onClose={vi.fn()} onSuccess={vi.fn()} />)
    chooseNoVin()
    fireEvent.change(screen.getByLabelText('identifier.typeLabel'), { target: { value: 'none' } })
    fireEvent.click(screen.getByRole('button', { name: 'wizard.next' }))
    fireEvent.change(await screen.findByLabelText(/^wizard\.nickname/), { target: { value: 'Head' } })
    fireEvent.click(screen.getByRole('button', { name: 'wizard.next' }))
    fireEvent.click(await screen.findByRole('button', { name: 'wizard.next' }))
    expect(await screen.findByTestId('wizard-review-identifier')).toHaveTextContent(
      'vehicles:identifier.types.none',
    )
    fireEvent.click(screen.getByRole('button', { name: /wizard\.misc\.createVehicle/ }))
    await waitFor(() => expect(vehicleService.create).toHaveBeenCalled())
    const payload = vi.mocked(vehicleService.create).mock.calls[0][0]
    expect(payload).not.toHaveProperty('vin')
    expect(payload).toMatchObject({ identifier_type: 'none', identifier: null })
  })

  it('a certificate whose field E is short lands in No VIN with the chassis number', async () => {
    vi.mocked(registrationCertificateService.parse).mockResolvedValue({
      source: 'text',
      country: 'FR',
      confidence: 70,
      fields: { vin: null, chassis_number: '1121234567', plate: 'AB-123-CD', taxes: {} },
      field_confidence: { chassis_number: 'medium' },
      vehicle_patch: { license_plate: 'AB-123-CD', make: 'RENAULT', model: '4', registration_country: 'FR' },
      inspection_due_date: null,
      suggested_tax_records: [],
      warnings: ['E: not a 17-character VIN, read as the chassis number'],
      model: null,
      pages: 0,
      parse_token: 'tok-4l',
    } as never)
    vi.mocked(vehicleService.create).mockResolvedValue({ vin: Q_KEY } as never)
    vi.mocked(registrationCertificateService.importForVehicle).mockResolvedValue({} as never)
    render(<VehicleWizard onClose={vi.fn()} onSuccess={vi.fn()} />)

    const file = new File(['%PDF-1.4'], 'carte-grise.pdf', { type: 'application/pdf' })
    fireEvent.change(screen.getByTestId('registration-certificate-file'), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'registrationImport.read' }))

    expect(await screen.findByText('registrationImport.chassisRouted')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'wizard.misc.previous' }))
    expect(screen.getByRole('tab', { name: 'identifier.noVin' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByLabelText('identifier.typeLabel')).toHaveValue('chassis')
    expect(screen.getByLabelText(/^identifier\.valueLabel/)).toHaveValue('1121234567')

    fireEvent.click(screen.getByRole('button', { name: 'wizard.next' }))
    fireEvent.click(await screen.findByRole('button', { name: 'wizard.next' }))
    fireEvent.click(await screen.findByRole('button', { name: 'wizard.next' }))
    const review = await screen.findByTestId('wizard-review-identifier')
    expect(review).toHaveTextContent('vehicles:identifier.types.chassis')
    expect(review).toHaveTextContent('1121234567')
    fireEvent.click(screen.getByRole('button', { name: /wizard\.misc\.createVehicle/ }))

    await waitFor(() => expect(registrationCertificateService.importForVehicle).toHaveBeenCalled())
    const payload = vi.mocked(vehicleService.create).mock.calls[0][0]
    expect(payload).not.toHaveProperty('vin')
    expect(payload).toMatchObject({ identifier_type: 'chassis', identifier: '1121234567', make: 'RENAULT' })
    expect(registrationCertificateService.importForVehicle).toHaveBeenCalledWith(Q_KEY, file, {
      parseToken: 'tok-4l',
      allowExternalVision: false,
      taxCodes: [],
    })
  })
})
