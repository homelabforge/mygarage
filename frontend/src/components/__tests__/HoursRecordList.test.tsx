import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, fireEvent } from '@testing-library/react'
import type { HoursRecord } from '../../types/hours'

const useHoursRecordsMock = vi.fn()
const deleteMutate = vi.fn()

vi.mock('../../hooks/queries/useHoursRecords', () => ({
  useHoursRecords: () => useHoursRecordsMock(),
  useDeleteHoursRecord: () => ({ mutate: deleteMutate, isPending: false, variables: undefined }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import HoursRecordList from '../HoursRecordList'

const record = {
  id: 1, vin: 'V1', date: '2026-03-01', engine_hours: '812.4', notes: 'oil change',
  source: 'manual', fuel_record_id: null, service_visit_id: null, created_at: '2026-03-01T00:00:00',
} as unknown as HoursRecord
const fuelSourced = {
  id: 2, vin: 'V1', date: '2026-03-02', engine_hours: '820.0', notes: null,
  source: 'fuel', fuel_record_id: 9, service_visit_id: null, created_at: '2026-03-02T00:00:00',
} as unknown as HoursRecord
const onAddClick = vi.fn()
const onEditClick = vi.fn()
const PROPS = { vin: 'V1', onAddClick, onEditClick }
const table = () => screen.getByRole('table', { name: 'hoursList.tableCaption' })

beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  // latest (820.0) is deliberately DISTINCT from the single row (812.4) so the
  // hero test proves the hero binds to latest_engine_hours, not to a row value.
  useHoursRecordsMock.mockReturnValue({ data: { records: [record], latest_engine_hours: '820.0' }, isLoading: false, error: null })
})

describe('HoursRecordList — DataTable rows scoped to the named table', () => {
  it('renders the engine-hours cell INSIDE the named table, formatted as "{n} hr" (fails if the DataTable/caption is dropped or the column vanishes; scoping stops the hero tile from satisfying it)', () => {
    render(<HoursRecordList {...PROPS} />)
    expect(within(table()).getByText('812.4 hr')).toBeInTheDocument()
  })

  it('renders the EXACT latest-hours value inside the hero card, and the hero lives OUTSIDE the table (fails if the hero value is dropped, wrong, unformatted, or leaks into the table)', () => {
    render(<HoursRecordList {...PROPS} />)
    // The hero label <p> and its <Mono size="2xl"> value are siblings in one <div>;
    // scope to that container and assert the exact formatted LATEST (820.0 ≠ the
    // row's 812.4), proving the hero shows the latest value, not merely a label.
    const hero = screen.getByText('hoursList.latestReading').parentElement as HTMLElement
    expect(within(hero).getByText('820.0 hr')).toBeInTheDocument()
    // and the hero label never appears inside the table.
    expect(within(table()).queryByText('hoursList.latestReading')).not.toBeInTheDocument()
  })
})

describe('HoursRecordList — source column', () => {
  it('renders the translated source label per row (manual vs fuel), inside the table (fails if the source column is dropped or shows the raw untranslated string)', () => {
    useHoursRecordsMock.mockReturnValue({ data: { records: [record, fuelSourced], latest_engine_hours: '820.0' }, isLoading: false, error: null })
    render(<HoursRecordList {...PROPS} />)
    const manualRow = within(table()).getByText('oil change').closest('tr') as HTMLElement
    const fuelRow = within(table()).getByText('820.0 hr').closest('tr') as HTMLElement
    expect(within(manualRow).getByText('hoursList.sourceManual')).toBeInTheDocument()
    expect(within(fuelRow).getByText('hoursList.sourceFuel')).toBeInTheDocument()
  })
})

describe('HoursRecordList — row actions + empty state', () => {
  it('clicking row Edit calls onEditClick with THE WHOLE record (fails if edit is unwired or passes a truncated object)', () => {
    render(<HoursRecordList {...PROPS} />)
    fireEvent.click(within(table()).getByRole('button', { name: 'common:edit' }))
    expect(onEditClick).toHaveBeenCalledWith(record)
  })

  it('clicking row Delete (confirm accepted) calls the delete mutation with the record id (fails if delete is unwired or the confirm gate is dropped)', () => {
    render(<HoursRecordList {...PROPS} />)
    fireEvent.click(within(table()).getByRole('button', { name: 'common:delete' }))
    expect(window.confirm).toHaveBeenCalled()
    expect(deleteMutate).toHaveBeenCalledWith(1, expect.anything())
  })

  it('with zero records, the empty-state CTA fires onAddClick (fails if the CTA is unwired or the title text changes)', () => {
    useHoursRecordsMock.mockReturnValue({ data: { records: [], latest_engine_hours: null }, isLoading: false, error: null })
    render(<HoursRecordList {...PROPS} />)
    expect(screen.getByText('hoursList.noRecords')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'hoursList.addFirstReading' }))
    expect(onAddClick).toHaveBeenCalled()
  })
})

describe('HoursRecordList: rows a tire published (#217)', () => {
  it('calls a tire row a tire, not manual', () => {
    const tireRow = {
      ...record,
      id: 3,
      source: 'tire_mount',
      notes: '[AUTO-SYNC from tire_mount #7]',
    } as unknown as HoursRecord
    useHoursRecordsMock.mockReturnValue({
      data: { records: [tireRow], latest_engine_hours: '812.4' },
      isLoading: false,
      error: null,
    })
    render(<HoursRecordList {...PROPS} />)
    const row = within(table()).getByText('812.4 hr').closest('tr') as HTMLElement
    expect(within(row).getByText('hoursList.sourceTire')).toBeInTheDocument()
    expect(within(row).queryByText('hoursList.sourceManual')).toBeNull()
  })
})
