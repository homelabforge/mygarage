import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import type { Recall } from '../../types/recall'

// The English bundle, so the sentences and their dates are what a user reads.
vi.mock('react-i18next', async () => (await import('@/__tests__/i18nEn')).reactI18nextEn())

const useRecallRecordsMock = vi.fn()
vi.mock('../../hooks/queries/useRecallRecords', () => ({
  useRecallRecords: (...a: unknown[]) => useRecallRecordsMock(...a),
  useDeleteRecallRecord: () => ({ mutate: vi.fn(), isPending: false, variables: undefined }),
  useCheckRecalls: () => ({ mutate: vi.fn(), isPending: false }),
  useToggleRecallResolved: () => ({ mutate: vi.fn(), isPending: false }),
}))
vi.mock('@tanstack/react-query', () => ({ useQueryClient: () => ({ invalidateQueries: vi.fn() }) }))
const apiGet = vi.hoisted(() => vi.fn())
vi.mock('../../services/api', () => ({ default: { get: apiGet } }))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() } }))

import RecallList from '../RecallList'

const base = {
  id: 1,
  vin: 'V1',
  component: 'Air Bags',
  nhtsa_campaign_number: '26V059000',
  summary: 'Inflator may rupture',
  consequence: '',
  remedy: '',
  notes: '',
  date_announced: '2026-02-01',
  is_resolved: false,
  resolved_at: null,
  resolved_via: null,
  linked_visit: null,
} as unknown as Recall

const LINK = { visit_id: 77, line_item_id: 501, date: '2026-11-03', vendor_name: 'EAG' }

function serve(recalls: Recall[]): void {
  useRecallRecordsMock.mockReturnValue({
    data: { recalls, total: recalls.length, active_count: 0, resolved_count: recalls.length },
    isLoading: false,
    error: null,
  })
}

function Where(): React.ReactElement {
  const location = useLocation()
  return <div data-testid="where">{location.pathname + location.search}</div>
}

function renderList(): void {
  render(
    <MemoryRouter initialEntries={['/vehicles/V1?tab=recalls']}>
      <Routes>
        <Route
          path="/vehicles/:vin"
          element={
            <>
              <RecallList vin="V1" onAddClick={vi.fn()} onEditClick={vi.fn()} />
              <Where />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  )
}

const markActive = (): HTMLElement => screen.getByRole('button', { name: 'Mark as active' })
const HINT = 'Unlink it on the service visit to reopen.'

beforeEach(() => {
  vi.clearAllMocks()
  apiGet.mockImplementation((url: string) =>
    url === '/vehicles/V1' ? Promise.resolve({ data: { vin: 'V1' } }) : Promise.reject({ response: { status: 403 } }),
  )
})

describe('RecallList: a recall a service visit fixed', () => {
  it('shows the visit date as a day, links to the item, and blocks Mark active with the hint', () => {
    serve([{ ...base, is_resolved: true, resolved_at: '2026-11-03T18:00:00', resolved_via: 'service_visit', linked_visit: LINK } as unknown as Recall])
    renderList()

    const link = screen.getByRole('link', { name: 'Resolved at the service visit on Nov 3, 2026 (EAG)' })
    expect(link).toHaveAttribute('href', '/vehicles/V1?tab=service&visit=77&item=501')
    expect(markActive()).toBeDisabled()
    expect(markActive()).toHaveAttribute('title', HINT)
    expect(screen.getByText(HINT)).toBeInTheDocument()
    expect(markActive()).toHaveAccessibleDescription(HINT)
  })

  it('without a vendor the sentence just ends at the date', () => {
    serve([{ ...base, is_resolved: true, resolved_at: '2026-11-03T18:00:00', resolved_via: 'service_visit', linked_visit: { ...LINK, vendor_name: null } } as unknown as Recall])
    renderList()

    expect(screen.getByRole('link', { name: 'Resolved at the service visit on Nov 3, 2026' })).toBeInTheDocument()
  })

  it('keys on the link, not resolved_via: a linked recall resolved by hand is still blocked', () => {
    serve([{ ...base, is_resolved: true, resolved_at: '2026-11-03T18:00:00', resolved_via: 'manual', linked_visit: LINK } as unknown as Recall])
    renderList()

    expect(screen.getByRole('link', { name: /Resolved at the service visit on Nov 3, 2026/ })).toBeInTheDocument()
    expect(markActive()).toBeDisabled()
  })

  it('beside it, an unlinked service_visit recall keeps its timestamp and can be reopened', () => {
    serve([
      { ...base, is_resolved: true, resolved_at: '2026-11-03T18:00:00', resolved_via: 'service_visit', linked_visit: LINK } as unknown as Recall,
      { ...base, id: 2, component: 'Brakes', is_resolved: true, resolved_at: '2026-03-01T12:00:00', resolved_via: 'service_visit', linked_visit: null } as unknown as Recall,
    ])
    renderList()

    const [linked, unlinked] = screen.getAllByRole('button', { name: 'Mark as active' })
    expect(linked).toBeDisabled()
    expect(unlinked).toBeEnabled()
    expect(screen.getByText('Mar 1, 2026')).toBeInTheDocument()
    expect(screen.getAllByText(/Resolved at the service visit/)).toHaveLength(1)
    expect(screen.getAllByText(HINT)).toHaveLength(1)
  })

  it('following the link lands on the service tab with the visit and item', async () => {
    serve([{ ...base, is_resolved: true, resolved_at: '2026-11-03T18:00:00', resolved_via: 'service_visit', linked_visit: LINK } as unknown as Recall])
    renderList()

    fireEvent.click(screen.getByRole('link', { name: /Resolved at the service visit/ }))
    await waitFor(() =>
      expect(screen.getByTestId('where')).toHaveTextContent('/vehicles/V1?tab=service&visit=77&item=501'),
    )
  })
})

describe('RecallList: a recall with no component or summary', () => {
  it('titles it "Unnamed recall" and drops its empty Summary block; a full one beside it keeps both', () => {
    serve([{ ...base, id: 2, component: null, summary: null } as unknown as Recall, base])
    renderList()

    const headings = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)
    expect(headings).toEqual(['Unnamed recall', 'Air Bags'])
    // One Summary label, the full recall's.
    expect(screen.getAllByText('Summary')).toHaveLength(1)
    expect(within(screen.getByText('Summary').parentElement as HTMLElement).getByText('Inflator may rupture')).toBeInTheDocument()
  })
})
