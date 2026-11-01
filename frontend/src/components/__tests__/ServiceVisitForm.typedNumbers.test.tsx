/**
 * The service form's numbers are typed text read in the user's language
 * (G5a-12). They used to be native number boxes read with parseFloat, so what
 * a German typed depended on the browser: "12,50" either came through or
 * read as blank and the cost was dropped.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import type { ReactNode } from 'react'
import { screen, fireEvent, waitFor } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import { setActiveLocale } from '@/constants/i18n'
import ServiceVisitForm from '../ServiceVisitForm'
import type { Supply } from '../../types/supplies'

const mockedApiGet = vi.fn()
const mockedApiPost = vi.fn().mockResolvedValue({ data: {} })

vi.mock('../../services/api', () => ({
  default: {
    get: (...args: unknown[]) => mockedApiGet(...args),
    post: (...args: unknown[]) => mockedApiPost(...args),
    put: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

vi.mock('../../hooks/useUnitPreference', async () => {
  const { METRIC_UNITS } = await import('@/__tests__/factories')
  const unitPreference = () => ({ system: 'metric', showBoth: false, units: METRIC_UNITS, gallonStandard: 'us' })
  return { useUnitPreference: unitPreference, useAccountUnitPreference: unitPreference }
})

// Keeps interpolated values, so a row's name can be checked for its supply.
vi.mock('react-i18next', () => {
  const t = (key: string, options?: Record<string, unknown>): string => {
    const values = Object.entries(options ?? {}).map(([name, value]) => `${name}=${String(value)}`)
    return values.length > 0 ? `${key}(${values.join(', ')})` : key
  }
  const i18n = { language: 'en', changeLanguage: () => Promise.resolve() }
  return {
    useTranslation: () => ({ t, i18n }),
    Trans: ({ children }: { children: ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

vi.mock('../../hooks/useReminders', () => ({
  useMaintenanceTypes: () => ({ data: [] }),
  invalidateMaintenanceQueries: () => {},
}))
vi.mock('../../hooks/useCurrencyPreference', () => ({
  useCurrencyPreference: () => ({ currencyCode: 'EUR', locale: 'de-DE', formatCurrency: () => '0,00 €' }),
}))

const OIL_FILTER: Supply = {
  id: 1, name: 'Oil Filter', unit_type: 'count', avg_unit_cost: '10.00', on_hand: '20', is_active: true,
  is_negative: false, created_at: '2026-01-01T00:00:00', category: null, notes: null, part_number: null,
  updated_at: null, vin: null,
}
const COOLANT: Supply = { ...OIL_FILTER, id: 2, name: 'Coolant', unit_type: 'volume', volume_unit: 'L' }

vi.mock('../../hooks/queries/useSupplies', () => ({
  useSupplies: () => ({ data: { supplies: [OIL_FILTER, COOLANT], total: 2 }, isSuccess: true, isLoading: false, isError: false }),
}))
vi.mock('../VendorSearch', () => ({ default: () => <div data-testid="vendor-search" /> }))
vi.mock('../ServiceVisitAttachmentUpload', () => ({ default: () => <div /> }))
vi.mock('../ServiceVisitAttachmentList', () => ({ default: () => <div /> }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const drawerForm = (): HTMLFormElement => screen.getByRole('dialog').querySelector('form') as HTMLFormElement
const type = (el: HTMLElement, value: string) => fireEvent.change(el, { target: { value } })
// By placeholder and by the box under the label text, so the parsing cases go
// red on main for the parsing and not for the missing label wiring.
const description = () => screen.getByPlaceholderText('lineItemEditor.misc.selectCategoryFirst')
const cost = () =>
  screen.getByText('lineItemEditor.cost').parentElement?.querySelector('input') as HTMLInputElement

type Posted = {
  odometer_km?: number
  engine_hours?: number
  tax_amount?: number
  shop_supplies?: number
  misc_fees?: number
  line_items: { cost?: number; supplies_used: { supply_id: number; quantity: number }[] }[]
}

async function submitAndRead(): Promise<Posted> {
  fireEvent.submit(drawerForm())
  await waitFor(() => expect(mockedApiPost).toHaveBeenCalled())
  return mockedApiPost.mock.calls.at(-1)?.[1] as Posted
}

beforeEach(() => {
  vi.clearAllMocks()
  // Dual-metered, so both the odometer and the hours box show.
  mockedApiGet.mockImplementation((url: string) =>
    Promise.resolve(
      url === '/vehicles/TEST123'
        ? { data: { vin: 'TEST123', usage_unit: 'distance', secondary_usage_enabled: true } }
        : { data: { items: [] } }
    )
  )
})

afterEach(() => setActiveLocale('en'))

describe('ServiceVisitForm: numbers read in the user language', () => {
  it('finds the line-item description and cost by their labels', () => {
    render(<ServiceVisitForm vin="TEST123" onClose={vi.fn()} onSuccess={vi.fn()} />)
    expect(screen.getByLabelText(/lineItemEditor\.misc\.descriptionLabel/)).toBe(description())
    expect(screen.getByLabelText('lineItemEditor.cost')).toHaveAttribute('inputmode', 'decimal')
  })

  it('de: a 12,50 line-item cost saves 12.5', async () => {
    setActiveLocale('de')
    render(<ServiceVisitForm vin="TEST123" onClose={vi.fn()} onSuccess={vi.fn()} />)
    type(description(), 'Ölwechsel')
    type(cost(), '12,50')
    const body = await submitAndRead()
    expect(body.line_items[0].cost).toBe(12.5)
  })

  it('a typed abc cost says the cost is not a number and posts nothing', async () => {
    render(<ServiceVisitForm vin="TEST123" onClose={vi.fn()} onSuccess={vi.fn()} />)
    type(description(), 'Oil change')
    type(cost(), 'abc')
    fireEvent.submit(drawerForm())
    expect(await screen.findByText('service.lineItemCostInvalid(number=1)')).toBeInTheDocument()
    expect(mockedApiPost).not.toHaveBeenCalled()
  })

  it('de: the visit odometer, hours, tax and fees read with a comma decimal', async () => {
    setActiveLocale('de')
    render(<ServiceVisitForm vin="TEST123" onClose={vi.fn()} onSuccess={vi.fn()} />)
    type(description(), 'Ölwechsel')
    // 72.420 is grouping in German, so 72420 km, not 72.42.
    type(screen.getByLabelText(/common:mileage/), '72.420')
    type(await screen.findByLabelText(/common:engineHours/), '812,4')
    type(screen.getByLabelText('service.tax'), '12,50')
    type(screen.getByLabelText('service.shopSupplies'), '3,25')
    type(screen.getByLabelText('service.miscFees'), '1,5')
    const body = await submitAndRead()
    expect(body.odometer_km).toBe(72420)
    expect(body.engine_hours).toBe(812.4)
    expect(body.tax_amount).toBe(12.5)
    expect(body.shop_supplies).toBe(3.25)
    expect(body.misc_fees).toBe(1.5)
  })

  it('a visit amount that is not a number is refused on the field', async () => {
    render(<ServiceVisitForm vin="TEST123" onClose={vi.fn()} onSuccess={vi.fn()} />)
    type(description(), 'Oil change')
    // A supply puts the fee breakdown on screen, which reads the NaN too and mustn't print it.
    fireEvent.click(screen.getByRole('button', { name: /suppliesAddRow/ }))
    type(screen.getByRole('textbox', { name: 'service.suppliesQuantityOf(supply=Oil Filter)' }), '1')
    type(screen.getByLabelText('service.tax'), 'abc')
    expect(screen.getByText('service.partsSupplies:')).toBeInTheDocument()
    expect(screen.getByRole('dialog').textContent).not.toContain('NaN')
    fireEvent.submit(drawerForm())
    expect(await screen.findByText('common:mustBeANumber')).toBeInTheDocument()
    expect(screen.getByLabelText('service.tax')).toHaveValue('abc')
    expect(mockedApiPost).not.toHaveBeenCalled()
  })

  it('each supply row names its quantity box and remove button after the supply', async () => {
    setActiveLocale('de')
    render(<ServiceVisitForm vin="TEST123" onClose={vi.fn()} onSuccess={vi.fn()} />)
    type(description(), 'Ölwechsel')
    fireEvent.click(screen.getByRole('button', { name: /suppliesAddRow/ }))
    fireEvent.click(screen.getByRole('button', { name: /suppliesAddRow/ }))
    const filter = screen.getByRole('textbox', { name: 'service.suppliesQuantityOf(supply=Oil Filter)' })
    const coolant = screen.getByRole('textbox', { name: 'service.suppliesQuantityOf(supply=Coolant)' })
    expect(screen.getByRole('button', { name: 'service.suppliesRemoveNamed(supply=Oil Filter)' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'service.suppliesRemoveNamed(supply=Coolant)' })).toBeInTheDocument()

    type(filter, '1')
    type(coolant, '1,5')
    const body = await submitAndRead()
    expect(body.line_items[0].supplies_used).toEqual([
      { supply_id: 1, quantity: 1 },
      { supply_id: 2, quantity: 1.5 },
    ])
  })

  it('removing a supply row keeps what the row below it holds', async () => {
    render(<ServiceVisitForm vin="TEST123" onClose={vi.fn()} onSuccess={vi.fn()} />)
    type(description(), 'Oil change')
    fireEvent.click(screen.getByRole('button', { name: /suppliesAddRow/ }))
    fireEvent.click(screen.getByRole('button', { name: /suppliesAddRow/ }))
    type(screen.getByRole('textbox', { name: 'service.suppliesQuantityOf(supply=Oil Filter)' }), '2')
    type(screen.getByRole('textbox', { name: 'service.suppliesQuantityOf(supply=Coolant)' }), '1.75')
    fireEvent.click(screen.getByRole('button', { name: 'service.suppliesRemoveNamed(supply=Oil Filter)' }))
    expect(screen.getByRole('textbox', { name: 'service.suppliesQuantityOf(supply=Coolant)' })).toHaveValue('1.75')
    const body = await submitAndRead()
    expect(body.line_items[0].supplies_used).toEqual([{ supply_id: 2, quantity: 1.75 }])
  })
})
