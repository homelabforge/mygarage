import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '../../__tests__/test-utils'
import { fireEvent } from '@testing-library/react'
import { makeUnitFormat } from '../../utils/unitFormat'
import { METRIC_UNITS } from '../../__tests__/factories'
import type { WarrantyRecord } from '../../types/warranty'

const useWarrantyRecordsMock = vi.fn()
const deleteMutate = vi.fn()
vi.mock('../../hooks/queries/useWarrantyRecords', () => ({
  useWarrantyRecords: () => useWarrantyRecordsMock(),
  useDeleteWarrantyRecord: () => ({ mutate: deleteMutate, isPending: false, variables: undefined }),
}))
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({
    system: 'metric',
    showBoth: false,
    gallonStandard: 'us',
    // The RESOLVED set, not just the collapsed system: this component reads
    // its distance through `useUnitFormat()`, which closes over `units`.
    units: METRIC_UNITS,
  }),
}))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))
vi.mock('../../hooks/useCurrencyPreference', () => ({ useCurrencyPreference: () => ({ currencyCode: 'USD', locale: 'en-US' }) }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import WarrantyList from '../WarrantyList'

// end_date lexicographically < today ⇒ expired; > today ⇒ active (isExpired uses
// formatDateForInput() = today's local YYYY-MM-DD — real, unmocked, deterministic).
const activeWarranty = {
  id: 1, warranty_type: 'Manufacturer', provider: 'Toyota',
  start_date: '2020-01-01', end_date: '2099-12-31',
  mileage_limit_km: '96561', policy_number: 'W-1', coverage_details: '', notes: '',
} as unknown as WarrantyRecord
const expiredWarranty = { ...activeWarranty, id: 2, end_date: '2000-01-01' } as unknown as WarrantyRecord

const onAddClick = vi.fn()
const onEditClick = vi.fn()
const PROPS = { vin: 'V1', onAddClick, onEditClick }

beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  useWarrantyRecordsMock.mockReturnValue({ data: [activeWarranty], isLoading: false, error: null })
})

describe('WarrantyList — rendering + row actions', () => {
  it('renders the warranty type + provider + the mileage limit via the REAL distance formatter (fails if the header content is dropped or the mileage renders raw canonical km instead of the formatted value)', () => {
    render(<WarrantyList {...PROPS} />)
    expect(screen.getByText('Manufacturer')).toBeInTheDocument()
    expect(screen.getByText('Toyota')).toBeInTheDocument()
    // M2: the mileage cell is a load-bearing display conversion — assert the EXACT
    // formatter output (96561 km, metric → "96,561 km"), a value DISTINCT from every
    // other cell (dates 2020/2099, policy# W-1) so it can't cross-match.
    expect(
      screen.getByText(makeUnitFormat(METRIC_UNITS).distance.format(96561))
    ).toBeInTheDocument()
  })

  it('clicking row Edit calls onEditClick with THE WHOLE warranty (fails if edit is unwired, passes the wrong row, or a truncated object)', () => {
    render(<WarrantyList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:edit' }))
    expect(onEditClick).toHaveBeenCalledWith(activeWarranty)
  })

  it('clicking row Delete (confirm accepted) calls the delete mutation with the warranty id (fails if delete is unwired or the confirm gate is dropped)', () => {
    render(<WarrantyList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:delete' }))
    expect(window.confirm).toHaveBeenCalled()
    expect(deleteMutate).toHaveBeenCalledWith(1, expect.anything())
  })

  it('the row Edit/Delete expose a real aria-label (IconButton), not a bare title (fails if IconButton regresses to a title-only <button>)', () => {
    render(<WarrantyList {...PROPS} />)
    expect(screen.getByRole('button', { name: 'common:edit' })).toHaveAttribute('aria-label', 'common:edit')
    expect(screen.getByRole('button', { name: 'common:delete' })).toHaveAttribute('aria-label', 'common:delete')
  })
})

describe('WarrantyList — expired status (both ways) + empty state', () => {
  it('an expired warranty shows the Expired label (fails if the expired flag stops rendering)', () => {
    useWarrantyRecordsMock.mockReturnValue({ data: [expiredWarranty], isLoading: false, error: null })
    render(<WarrantyList {...PROPS} />)
    expect(screen.getByText('warrantyList.expired')).toBeInTheDocument()
  })

  it('an active warranty does NOT show the Expired label (fails if isExpired is inverted or always-on)', () => {
    render(<WarrantyList {...PROPS} />)
    expect(screen.queryByText('warrantyList.expired')).not.toBeInTheDocument()
  })

  it('with zero warranties, the empty-state CTA fires onAddClick (fails if the CTA is unwired or the title text changes)', () => {
    useWarrantyRecordsMock.mockReturnValue({ data: [], isLoading: false, error: null })
    render(<WarrantyList {...PROPS} />)
    expect(screen.getByText('warrantyList.noRecords')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'warrantyList.addFirstWarranty' }))
    expect(onAddClick).toHaveBeenCalled()
  })
})

describe('WarrantyList: what was done under it', () => {
  it('lists each linked item under "Used on" with its date, description and cost, linked to the item', () => {
    useWarrantyRecordsMock.mockReturnValue({
      data: [
        // One nothing used yet, so "Used on" shows once.
        { ...activeWarranty, id: 3, linked_items: [] },
        {
          ...activeWarranty,
          linked_items: [
            { visit_id: 77, line_item_id: 502, date: '2026-11-03', description: 'Water pump', cost: '412.50' },
            { visit_id: 40, line_item_id: 310, date: '2025-06-14', description: 'Thermostat', cost: null },
          ],
        },
      ],
      isLoading: false,
      error: null,
    })
    render(<WarrantyList {...PROPS} />)

    expect(screen.getAllByText('warrantyList.usedOn')).toHaveLength(1)
    const rows = screen.getAllByRole('listitem')
    expect(rows).toHaveLength(2)
    // Newest first, as the server sends them.
    expect(rows[0]).toHaveTextContent('Nov 3, 2026')
    expect(rows[0]).toHaveTextContent('Water pump')
    expect(rows[0]).toHaveTextContent('$412.50')
    expect(rows[1]).toHaveTextContent('Jun 14, 2025')
    expect(rows[1]).toHaveTextContent('Thermostat')
    const link = rows[0].querySelector('a') as HTMLAnchorElement
    expect(link.getAttribute('href')).toMatch(/\?tab=service&visit=77&item=502$/)
  })
})
