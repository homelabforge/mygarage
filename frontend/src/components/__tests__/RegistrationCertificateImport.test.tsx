/**
 * The registration certificate import (#211): read-only before a vehicle
 * exists, store-and-apply on one, and the AI-off path that still leaves
 * everything typeable.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import RegistrationCertificateImport from '../RegistrationCertificateImport'
import type { RegistrationParseResponse } from '@/services/registrationCertificateService'

vi.mock('@/services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

// Keys only, with the interpolation options appended so a test can see them.
vi.mock('react-i18next', () => {
  const t = (key: string, options?: Record<string, unknown>) =>
    options && Object.keys(options).length > 0 ? `${key}|${JSON.stringify(options)}` : key
  return {
    useTranslation: () => ({ t, i18n: { language: 'en', changeLanguage: () => Promise.resolve() } }),
    Trans: ({ children }: { children: React.ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

import api from '@/services/api'

const mockedApi = vi.mocked(api)

const PARSE: RegistrationParseResponse = {
  source: 'text',
  country: 'FR',
  confidence: 100,
  fields: {
    plate: 'AB-123-CD',
    first_registration: '2023-03-12',
    make: 'RENAULT',
    commercial_name: 'CLIO',
    vin: 'VF1RFB00X56123456',
    energy_code: 'ES',
    taxes: { 'Y.1': '162.50' },
  },
  field_confidence: { plate: 'high', make: 'medium', vin: 'high' },
  vehicle_patch: {
    vin: 'VF1RFB00X56123456',
    license_plate: 'AB-123-CD',
    first_registration_date: '2023-03-12',
    make: 'RENAULT',
    model: 'CLIO',
    fuel_type: 'gasoline',
    registration_country: 'FR',
  },
  last_inspection_date: '2026-02-10',
  suggested_tax_records: [{ code: 'Y.1', tax_type: 'registration_tax', amount: '162.50', date: '2023-03-12' }],
  warnings: [],
  model: null,
  pages: 0,
}

function publicSettings(enabled: boolean) {
  return { data: { settings: [{ key: 'llm_document_reading_enabled', value: enabled ? 'true' : 'false' }] } }
}

function renderImport(props: Partial<React.ComponentProps<typeof RegistrationCertificateImport>> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={qc}>
      <RegistrationCertificateImport {...props} />
    </QueryClientProvider>,
  )
}

function pick(name: string, type: string): File {
  const file = new File(['%PDF-1.4 fake'], name, { type })
  fireEvent.change(screen.getByTestId('registration-certificate-file'), { target: { files: [file] } })
  return file
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('RegistrationCertificateImport', () => {
  it('reads a PDF before a vehicle exists and hands the result to the wizard', async () => {
    mockedApi.get.mockResolvedValue(publicSettings(false))
    mockedApi.post.mockResolvedValue({ data: PARSE })
    const onParsed = vi.fn()
    renderImport({ onParsed, country: 'FR' })

    expect(await screen.findByText('registrationImport.aiNotConfiguredHint')).toBeInTheDocument()
    const file = pick('carte-grise.pdf', 'application/pdf')
    expect(screen.getByTestId('registration-certificate-filename')).toHaveTextContent('carte-grise.pdf')
    // A PDF needs no model: the button is live even with AI off.
    const read = screen.getByRole('button', { name: 'registrationImport.read' })
    expect(read).not.toBeDisabled()
    fireEvent.click(read)

    await waitFor(() => expect(onParsed).toHaveBeenCalledWith(PARSE, file))
    const [url, body, config] = mockedApi.post.mock.calls[0] as [string, FormData, { params?: unknown }]
    expect(url).toBe('/registration-certificate/parse')
    expect(body.get('file')).toBe(file)
    expect(config.params).toEqual({ country: 'FR' })

    expect(screen.getByText('registrationImport.readFromPdf')).toBeInTheDocument()
    expect(screen.getByText('registrationImport.fields.plate')).toBeInTheDocument()
    expect(screen.getByText('AB-123-CD')).toBeInTheDocument()
    expect(screen.getByText('registrationImport.fields.taxes|{"code":"Y.1"}')).toBeInTheDocument()
    // The plate and the VIN are both sure; the make is only "check".
    expect(screen.getAllByText('registrationImport.confidenceLevel.high')).toHaveLength(2)
    expect(screen.getAllByText('registrationImport.confidenceLevel.medium')).toHaveLength(1)
  })

  it('a photo waits for AI document reading when it is off', async () => {
    mockedApi.get.mockResolvedValue(publicSettings(false))
    renderImport()
    await screen.findByText('registrationImport.aiNotConfiguredHint')

    pick('IMG_0001.jpg', 'image/jpeg')

    expect(screen.getByRole('button', { name: 'registrationImport.read' })).toBeDisabled()
    expect(screen.getByRole('status')).toHaveTextContent('registrationImport.aiNotConfigured')
    expect(mockedApi.post).not.toHaveBeenCalled()
  })

  it('a photo is read by the model when AI document reading is on', async () => {
    mockedApi.get.mockResolvedValue(publicSettings(true))
    mockedApi.post.mockResolvedValue({ data: { ...PARSE, source: 'llm', model: 'llava', pages: 1, warnings: ['E: dropped'] } })
    renderImport()
    expect(await screen.findByText('registrationImport.hint')).toBeInTheDocument()

    pick('IMG_0001.jpg', 'image/jpeg')
    const read = screen.getByRole('button', { name: 'registrationImport.read' })
    await waitFor(() => expect(read).not.toBeDisabled())
    fireEvent.click(read)

    expect(await screen.findByText('registrationImport.readByAi|{"model":"llava"}')).toBeInTheDocument()
    expect(screen.getByTestId('registration-certificate-warnings')).toHaveTextContent('E: dropped')
  })

  it("shows the server's own 409 as the AI hint, not as an error", async () => {
    mockedApi.get.mockResolvedValue(publicSettings(true))
    // The shape axios gives a rejected request; the class itself is mocked
    // away by the test setup, and the service never checks for it.
    mockedApi.post.mockRejectedValue({
      message: 'Request failed with status code 409',
      response: { status: 409, data: { detail: 'ai_reading_not_configured' } },
    })
    renderImport()
    await screen.findByText('registrationImport.hint')

    pick('scan.png', 'image/png')
    fireEvent.click(screen.getByRole('button', { name: 'registrationImport.read' }))

    expect(await screen.findByRole('status')).toHaveTextContent('registrationImport.aiNotConfigured')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('imports onto a vehicle, with the overwrite switch, and reports what was applied', async () => {
    mockedApi.get.mockResolvedValue(publicSettings(false))
    mockedApi.post.mockResolvedValue({
      data: {
        document: { id: 1, vin: 'VF1RFB00X56123456', title: 'Registration certificate (AB-123-CD)' },
        applied: ['license_plate', 'first_registration_date'],
        skipped: ['make'],
        inspection_recorded: true,
        parse: PARSE,
      },
    })
    const onImported = vi.fn()
    renderImport({ vin: 'VF1RFB00X56123456', onImported })
    await screen.findByText('registrationImport.aiNotConfiguredHint')

    fireEvent.click(screen.getByRole('checkbox', { name: /registrationImport.overwrite/ }))
    pick('carte-grise.pdf', 'application/pdf')
    fireEvent.click(screen.getByRole('button', { name: 'registrationImport.import' }))

    await waitFor(() => expect(onImported).toHaveBeenCalled())
    const [url, , config] = mockedApi.post.mock.calls[0] as [string, FormData, { params?: unknown }]
    expect(url).toBe('/vehicles/VF1RFB00X56123456/registration-certificate')
    expect(config.params).toEqual({ overwrite: true })
    expect(
      screen.getByText('registrationImport.appliedFields|{"fields":"edit.licensePlate, edit.firstRegistrationDate"}'),
    ).toBeInTheDocument()
    expect(screen.getByText('registrationImport.skippedFields|{"fields":"wizard.make"}')).toBeInTheDocument()
    expect(screen.getByText('registrationImport.recordedInspection|{"date":"2026-02-10"}')).toBeInTheDocument()
  })

  it('refuses a file of the wrong type or past the size limit before any request', async () => {
    mockedApi.get.mockResolvedValue(publicSettings(true))
    renderImport()
    await screen.findByText('registrationImport.hint')

    pick('notes.txt', 'text/plain')
    expect(screen.getByRole('alert')).toHaveTextContent('registrationImport.invalidFileType')
    expect(screen.getByRole('button', { name: 'registrationImport.read' })).toBeDisabled()

    const big = new File([new Uint8Array(1)], 'big.pdf', { type: 'application/pdf' })
    Object.defineProperty(big, 'size', { value: 26 * 1024 * 1024 })
    fireEvent.change(screen.getByTestId('registration-certificate-file'), { target: { files: [big] } })
    expect(screen.getByRole('alert')).toHaveTextContent('registrationImport.fileTooLarge')
    expect(mockedApi.post).not.toHaveBeenCalled()
  })
})
