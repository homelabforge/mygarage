import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import ServiceVisitForm from '../ServiceVisitForm'
import type { ServiceVisit } from '../../types/serviceVisit'

// Task 14 — service-visit form engine-hours usage tracking. Mirrors
// FuelRecordForm.hours coverage (Task 13, commit c7a87c1): hours-tracking
// vehicle shows the engine-hours reading input and hides odometer,
// distance-tracking the reverse, dual shows both; submit carries
// engine_hours; edit prefills it.

const drawerForm = (): HTMLFormElement =>
  screen.getByRole('dialog').querySelector('form') as HTMLFormElement

const mockedApiGet = vi.fn()
const mockedApiPost = vi.fn().mockResolvedValue({ data: {} })
const mockedApiPut = vi.fn().mockResolvedValue({ data: {} })

vi.mock('../../services/api', () => ({
  default: {
    get: (...args: unknown[]) => mockedApiGet(...args),
    post: (...args: unknown[]) => mockedApiPost(...args),
    put: (...args: unknown[]) => mockedApiPut(...args),
  },
}))

// Requires AuthProvider otherwise — same mock pattern as ServiceVisitForm.test.tsx.
vi.mock('../../hooks/useUnitPreference', async () => {
  const { METRIC_UNITS } = await import('@/__tests__/factories')
  return {
    useUnitPreference: () => ({
      system: 'metric',
      showBoth: false,
      units: METRIC_UNITS,
      gallonStandard: 'us',
    }),
  }
})
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({
    currencyCode: 'USD',
    locale: 'en-US',
    formatCurrency: () => '$0.00',
  }),
}))
// Empty supplies list — this suite doesn't exercise supplies_used, and an
// empty list keeps LineItemEditor's SupplyUsedPicker inert.
vi.mock('../../hooks/queries/useSupplies', () => ({
  useSupplies: () => ({
    data: { supplies: [], total: 0 },
    isSuccess: true,
    isLoading: false,
    isError: false,
  }),
}))
vi.mock('../VendorSearch', () => ({
  default: () => <div data-testid="vendor-search" />,
}))
vi.mock('../ServiceVisitAttachmentUpload', () => ({
  default: () => <div data-testid="attachment-upload" />,
}))
vi.mock('../ServiceVisitAttachmentList', () => ({
  default: () => <div data-testid="attachment-list" />,
}))
vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}))

const DEFAULT_PROPS = {
  vin: 'TEST12345678901234',
  onClose: vi.fn(),
  onSuccess: vi.fn(),
}

const odometerInput = () => document.getElementById('service-odometer') as HTMLInputElement | null
const engineHoursInput = () => document.getElementById('service-engine-hours') as HTMLInputElement | null

// LineItemEditor is the REAL component (not stubbed) so a create-mode submit
// test can satisfy the "every line item needs a description" gate the same
// way ServiceVisitForm.supplies.test.tsx does.
function fillRequiredDescription() {
  fireEvent.change(screen.getByPlaceholderText('lineItemEditor.misc.selectCategoryFirst'), {
    target: { value: 'Oil change' },
  })
}

describe('ServiceVisitForm — engine-hours usage tracking (Task 14)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedApiPost.mockResolvedValue({ data: {} })
    mockedApiPut.mockResolvedValue({ data: {} })
  })

  it('shows the engine-hours input (and hides odometer) for an hours-tracking vehicle', async () => {
    mockedApiGet.mockResolvedValue({ data: { usage_unit: 'hours', secondary_usage_enabled: false } })
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    await waitFor(() => expect(engineHoursInput()).toBeInTheDocument())

    expect(odometerInput()).not.toBeInTheDocument()
  })

  it('shows the odometer input (and hides engine-hours) for a distance-tracking vehicle', async () => {
    mockedApiGet.mockResolvedValue({ data: { usage_unit: 'distance', secondary_usage_enabled: false } })
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())

    expect(odometerInput()).toBeInTheDocument()
    expect(engineHoursInput()).not.toBeInTheDocument()
  })

  it('shows BOTH odometer and engine-hours inputs for a dual-tracking vehicle', async () => {
    mockedApiGet.mockResolvedValue({ data: { usage_unit: 'distance', secondary_usage_enabled: true } })
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    await waitFor(() => expect(engineHoursInput()).toBeInTheDocument())

    expect(odometerInput()).toBeInTheDocument()
  })

  it('defaults to the odometer input before the vehicle fetch resolves (no flash of the wrong field)', () => {
    mockedApiGet.mockReturnValue(new Promise(() => {})) // never resolves
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)

    expect(odometerInput()).toBeInTheDocument()
    expect(engineHoursInput()).not.toBeInTheDocument()
  })

  it('submits engine_hours in the create payload', async () => {
    mockedApiGet.mockResolvedValue({ data: { usage_unit: 'hours', secondary_usage_enabled: false } })
    render(<ServiceVisitForm {...DEFAULT_PROPS} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    await waitFor(() => expect(engineHoursInput()).toBeInTheDocument())

    fillRequiredDescription()
    fireEvent.change(engineHoursInput()!, { target: { value: '812.4' } })
    fireEvent.submit(drawerForm())

    await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
    const body = mockedApiPost.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(body.engine_hours).toBe(812.4)
  })

  it('prefills engine_hours from the visit on edit', async () => {
    mockedApiGet.mockResolvedValue({ data: { usage_unit: 'hours', secondary_usage_enabled: false } })
    const visit = {
      id: 900,
      vin: DEFAULT_PROPS.vin,
      date: '2026-07-01',
      created_at: '2026-07-01T00:00:00',
      calculated_total_cost: '0.00',
      has_failed_inspections: false,
      line_item_count: 1,
      subtotal: '0.00',
      vendor_id: null,
      odometer_km: null,
      engine_hours: '640.5',
      notes: null,
      insurance_claim_number: null,
      tax_amount: null,
      shop_supplies: null,
      misc_fees: null,
      service_category: null,
      total_cost: '0.00',
      updated_at: null,
      vendor: null,
      line_items: [
        {
          id: 501,
          visit_id: 900,
          description: 'Oil change',
          category: 'Maintenance',
          cost: null,
          created_at: '2026-07-01T00:00:00',
          is_failed_inspection: false,
          is_inspection: false,
          needs_followup: false,
          notes: null,
          triggered_by_inspection_id: null,
          supply_usages: [],
        },
      ],
    } as unknown as ServiceVisit

    render(<ServiceVisitForm {...DEFAULT_PROPS} visit={visit} />)
    await waitFor(() => expect(mockedApiGet).toHaveBeenCalled())
    await waitFor(() => expect(engineHoursInput()).toBeInTheDocument())

    expect(engineHoursInput()!.value).toBe('640.5')
  })
})

// Task 10 addendum — the coordinator flagged that 10a's catch-block rewrite
// (parseApiError(err).fieldErrors -> fieldErrors map, else setError(...))
// gained real branching with zero test coverage. This is the exact class of
// gap that hid a live bug in Task 7/9 (a non-422 failure showing NOTHING to
// the user) for two more tasks after a reviewer flagged it as Minor and it
// was deferred. Both branches are fenced here, on the REAL mutation path
// (api.put, via useUpdateServiceVisit — not a mocked mutateAsync), using
// edit mode so the pre-hydrated visit.line_items already satisfies the
// "every line item needs a description" guard without touching the (here
// real, unstubbed) LineItemEditor.
describe('ServiceVisitForm — server-side error wiring (Task 10 addendum)', () => {
  const axios422 = (detail: unknown): unknown => ({
    isAxiosError: true,
    message: 'Request failed with status code 422',
    response: { status: 422, data: { detail } },
  })

  function editableVisit(): ServiceVisit {
    return {
      id: 900,
      vin: DEFAULT_PROPS.vin,
      date: '2026-07-01',
      created_at: '2026-07-01T00:00:00',
      calculated_total_cost: '0.00',
      has_failed_inspections: false,
      line_item_count: 1,
      subtotal: '0.00',
      vendor_id: null,
      odometer_km: null,
      engine_hours: null,
      notes: null,
      insurance_claim_number: null,
      tax_amount: null,
      shop_supplies: null,
      misc_fees: null,
      service_category: null,
      total_cost: '0.00',
      updated_at: null,
      vendor: null,
      line_items: [
        {
          id: 501,
          visit_id: 900,
          description: 'Oil change',
          category: 'Maintenance',
          cost: null,
          created_at: '2026-07-01T00:00:00',
          is_failed_inspection: false,
          is_inspection: false,
          needs_followup: false,
          notes: null,
          triggered_by_inspection_id: null,
          supply_usages: [],
        },
      ],
    } as unknown as ServiceVisit
  }

  beforeEach(() => {
    vi.clearAllMocks()
    mockedApiPost.mockResolvedValue({ data: {} })
    mockedApiPut.mockResolvedValue({ data: {} })
    mockedApiGet.mockResolvedValue({ data: { usage_unit: 'distance', secondary_usage_enabled: false } })
  })

  it('a 422 naming "notes" lands its message on the notes field (fails if the fieldErrors map is not wired to the Field)', async () => {
    mockedApiPut.mockRejectedValueOnce(axios422([
      { type: 'string_too_long', loc: ['body', 'notes'], msg: 'Notes must be 5000 characters or fewer' },
    ]))
    render(<ServiceVisitForm {...DEFAULT_PROPS} visit={editableVisit()} />)
    await waitFor(() => expect(odometerInput()).toBeInTheDocument())

    fireEvent.submit(drawerForm())

    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Notes must be 5000 characters or fewer')
    expect(alert.id).toBe('visit-notes-error')
  })

  it('a non-422 failure (network error) still shows the fallback banner instead of staying silent (regression fence for the Task 7/9 silent-failure bug)', async () => {
    mockedApiPut.mockRejectedValueOnce(new Error('Network Error'))
    render(<ServiceVisitForm {...DEFAULT_PROPS} visit={editableVisit()} />)
    await waitFor(() => expect(odometerInput()).toBeInTheDocument())

    fireEvent.submit(drawerForm())

    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByText('Failed to {{action}}. {{message}}')).toBeInTheDocument())
  })

  // Final-review I4 regression fence: `vendor_id` has no fieldErrors-wired
  // Field (VendorSearch is mocked to a plain div here), so a 422 naming it
  // used to write to fieldErrors state, render nothing, and — under the old
  // `problems.length > 0 ? fieldErrors : setError(...)` gate — suppress the
  // banner entirely. applyControlledFieldErrors's attached/unhandled split
  // must still surface the banner when nothing attached.
  it('a 422 naming ONLY a field with no render target (vendor_id) shows the banner, not silence', async () => {
    mockedApiPut.mockRejectedValueOnce(axios422([
      { type: 'value_error', loc: ['body', 'vendor_id'], msg: 'Vendor not found' },
    ]))
    render(<ServiceVisitForm {...DEFAULT_PROPS} visit={editableVisit()} />)
    await waitFor(() => expect(odometerInput()).toBeInTheDocument())

    fireEvent.submit(drawerForm())

    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    expect(await screen.findByText('Failed to {{action}}. Please check your input.')).toBeInTheDocument()
  })

  it('a 422 with one mapped field and one unmapped field shows BOTH the field message and the banner', async () => {
    mockedApiPut.mockRejectedValueOnce(axios422([
      { type: 'string_too_long', loc: ['body', 'notes'], msg: 'Notes must be 5000 characters or fewer' },
      { type: 'value_error', loc: ['body', 'vendor_id'], msg: 'Vendor not found' },
    ]))
    render(<ServiceVisitForm {...DEFAULT_PROPS} visit={editableVisit()} />)
    await waitFor(() => expect(odometerInput()).toBeInTheDocument())

    fireEvent.submit(drawerForm())

    await waitFor(() => expect(mockedApiPut).toHaveBeenCalled())
    await waitFor(() =>
      expect(screen.getByText('Notes must be 5000 characters or fewer')).toBeInTheDocument()
    )
    expect(screen.getByText('Failed to {{action}}. Please check your input.')).toBeInTheDocument()
  })
})
