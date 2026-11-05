import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '../../__tests__/test-utils'
import { presetUnitsFor } from '../../types/units'
import type { ServiceVisit, ServiceLineItem } from '../../types/serviceVisit'

const unitMock = vi.hoisted(() => ({ system: 'metric' as 'metric' | 'imperial' }))
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: unitMock.system,
    showBoth: false,
    gallonStandard: 'us',
    units: presetUnitsFor(unitMock.system, 'us'),
  }),
}))
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { currency_code: 'USD' } }),
}))

import ServiceLineItemDetail from '../ServiceLineItemDetail'

const visit = {
  id: 1,
  vin: 'V1',
  date: '2026-10-11',
  odometer_km: '80467',
  engine_hours: '812.4',
} as unknown as ServiceVisit
const withUsage = (usage: Record<string, unknown>, cost: string | null = '40.00'): ServiceLineItem =>
  ({
    id: 10,
    description: 'Oil change',
    cost,
    supply_usages: [
      { id: 5, supply_id: 42, supply_name: 'Motor Oil', quantity: '4.732', cost_snapshot: '9.52', ...usage },
    ],
  }) as unknown as ServiceLineItem
const DISTANCE = { tracksDistance: true, tracksHours: false }

beforeEach(() => {
  unitMock.system = 'metric'
})

describe('ServiceLineItemDetail supplies used', () => {
  it('links each supply to its page on Supplies', () => {
    render(<ServiceLineItemDetail visit={visit} item={withUsage({ unit_type: 'count', quantity: '1' })} {...DISTANCE} onClose={vi.fn()} />)

    const link = screen.getByRole('link')
    expect(link).toHaveTextContent('Motor Oil')
    expect(link).toHaveAttribute('href', '/supplies?supply=42')
  })

  it("the link's name carries the quantity and cost, not just the supply", () => {
    // An aria-label here would replace the link's content for a screen reader,
    // so "5.00 qt" and the cost would never be announced.
    unitMock.system = 'imperial'
    render(<ServiceLineItemDetail visit={visit} item={withUsage({ unit_type: 'volume', volume_unit: null })} {...DISTANCE} onClose={vi.fn()} />)

    const link = screen.getByRole('link')
    expect(link).not.toHaveAttribute('aria-label')
    expect(link).toHaveAccessibleName(/5\.00 qt.*\$9\.52/)
  })

  it('a stored volume token wins over the account system', () => {
    render(<ServiceLineItemDetail visit={visit} item={withUsage({ unit_type: 'volume', volume_unit: 'fl_oz_us', quantity: '0.355' })} {...DISTANCE} onClose={vi.fn()} />)
    expect(screen.getByText('12.00 fl oz')).toBeInTheDocument()
  })

  it('a legacy usage with no token follows the account: qt for imperial, L for metric', () => {
    unitMock.system = 'imperial'
    const { unmount } = render(<ServiceLineItemDetail visit={visit} item={withUsage({ unit_type: 'volume', volume_unit: null })} {...DISTANCE} onClose={vi.fn()} />)
    expect(screen.getByText('5.00 qt')).toBeInTheDocument()
    unmount()

    unitMock.system = 'metric'
    render(<ServiceLineItemDetail visit={visit} item={withUsage({ unit_type: 'volume', volume_unit: null })} {...DISTANCE} onClose={vi.fn()} />)
    expect(screen.getByText('4.73 L')).toBeInTheDocument()
  })
})

describe('ServiceLineItemDetail cost', () => {
  it('total is labor plus the supplies used', () => {
    render(<ServiceLineItemDetail visit={visit} item={withUsage({ unit_type: 'count', quantity: '1' })} {...DISTANCE} onClose={vi.fn()} />)

    expect(screen.getByText('$40.00')).toBeInTheDocument()
    // Once in the parts row, once on the supply itself.
    expect(screen.getAllByText('$9.52')).toHaveLength(2)
    expect(screen.getByText('$49.52')).toBeInTheDocument()
  })
})

describe('ServiceLineItemDetail readings follow the vehicle the list resolved', () => {
  it('a distance vehicle shows the odometer and no hours', () => {
    render(<ServiceLineItemDetail visit={visit} item={withUsage({ unit_type: 'count', quantity: '1' })} {...DISTANCE} onClose={vi.fn()} />)
    expect(screen.getByText(/80,467/)).toBeInTheDocument()
    expect(screen.queryByText(/812\.4/)).not.toBeInTheDocument()
  })

  it('an hours vehicle shows its hours and no odometer', () => {
    render(<ServiceLineItemDetail visit={visit} item={withUsage({ unit_type: 'count', quantity: '1' })} tracksDistance={false} tracksHours onClose={vi.fn()} />)
    expect(screen.getByText('812.4 hr')).toBeInTheDocument()
    expect(screen.queryByText(/80,467/)).not.toBeInTheDocument()
  })
})

describe('ServiceLineItemDetail edit action', () => {
  const item = withUsage({ unit_type: 'count', quantity: '1' })

  it('has no edit button unless the caller passes onEdit', () => {
    render(<ServiceLineItemDetail visit={visit} item={item} {...DISTANCE} onClose={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'serviceList.detail.editVisit' })).not.toBeInTheDocument()
  })

  it('calls onEdit from the footer', () => {
    const onEdit = vi.fn()
    render(<ServiceLineItemDetail visit={visit} item={item} {...DISTANCE} onClose={vi.fn()} onEdit={onEdit} />)
    fireEvent.click(screen.getByRole('button', { name: 'serviceList.detail.editVisit' }))
    expect(onEdit).toHaveBeenCalledTimes(1)
  })
})
