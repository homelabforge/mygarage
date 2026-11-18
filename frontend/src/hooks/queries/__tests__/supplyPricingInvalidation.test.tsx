/**
 * A costed purchase prices the supply usages logged before the supply had a
 * cost, and a visit write prices its own (#301). So a purchase moves visit
 * totals, and a visit write moves the supply pages. Every case seeds the
 * caches first, so a missing invalidation reads as a stale entry and not as a
 * never-fetched one.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useAddPurchase } from '../useSupplies'
import {
  useCreateServiceVisit,
  useDeleteServiceVisit,
  useUpdateServiceVisit,
} from '../useServiceVisits'
import { useCompleteReminder } from '@/hooks/useReminders'
import api from '@/services/api'

vi.mock('@/services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))

const VIN = 'VIN1'
const OTHER_USAGES = ['vehicle-supply-usages', 'VIN2'] as const

const VISITS = ['serviceVisits', VIN] as const
const VISIT_PAGES = ['serviceVisits', VIN, 'pages'] as const
const USAGES = ['vehicle-supply-usages', VIN] as const
const STATS = ['vehicleDetailStats', VIN] as const
const SUPPLIES = ['supplies'] as const
const HISTORY = ['supply-history', 7] as const
const OTHER_HISTORY = ['supply-history', 8] as const

function seededClient(): QueryClient {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  qc.setQueryData(VISITS, { visits: [], total: 0 })
  qc.setQueryData(VISIT_PAGES, { pages: [], pageParams: [] })
  qc.setQueryData(USAGES, { usages: [], total: 0 })
  qc.setQueryData(OTHER_USAGES, { usages: [], total: 0 })
  qc.setQueryData(STATS, {})
  qc.setQueryData(SUPPLIES, [])
  qc.setQueryData(HISTORY, [])
  qc.setQueryData(OTHER_HISTORY, [])
  return qc
}

function stale(qc: QueryClient, key: readonly unknown[]): boolean | undefined {
  return qc.getQueryState(key)?.isInvalidated
}

async function run<T>(
  hook: () => { mutateAsync: (vars: T) => Promise<unknown> },
  vars: T,
): Promise<QueryClient> {
  const qc = seededClient()
  const { result } = renderHook(hook, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    ),
  })
  await result.current.mutateAsync(vars)
  return qc
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.post).mockResolvedValue({ data: {} })
  vi.mocked(api.put).mockResolvedValue({ data: {} })
  vi.mocked(api.delete).mockResolvedValue({ data: {} })
})

describe('a purchase marks the visits that use the supply stale', () => {
  it('visit lists, the usage tab and the vehicle stats', async () => {
    const qc = await run(() => useAddPurchase(7), {
      date: '2026-11-17',
      quantity: 5,
      total_cost: 37.45,
    } as never)

    expect(stale(qc, VISITS)).toBe(true)
    expect(stale(qc, VISIT_PAGES)).toBe(true)
    expect(stale(qc, USAGES)).toBe(true)
    expect(stale(qc, STATS)).toBe(true)
    expect(stale(qc, OTHER_USAGES)).toBe(true) // a supply spans vehicles
    // A visit it prices has its other supplies priced too.
    expect(stale(qc, OTHER_HISTORY)).toBe(true)
  })

  it('an uncosted purchase prices nothing, so leaves them alone', async () => {
    const qc = await run(() => useAddPurchase(7), { date: '2026-11-17', quantity: 5 } as never)

    expect(stale(qc, SUPPLIES)).toBe(true)
    expect(stale(qc, OTHER_HISTORY)).toBe(false)
    expect(stale(qc, VISITS)).toBe(false)
    expect(stale(qc, USAGES)).toBe(false)
    expect(stale(qc, STATS)).toBe(false)
  })
})

describe('a visit write marks the supply pages stale', () => {
  const cases: [string, () => { mutateAsync: (vars: never) => Promise<unknown> }, unknown][] = [
    ['create', () => useCreateServiceVisit(VIN), { date: '2026-11-17', line_items: [] }],
    ['update', () => useUpdateServiceVisit(VIN), { id: 1, date: '2026-11-17' }],
    ['delete', () => useDeleteServiceVisit(VIN), 1],
    [
      'reminder completed into a visit',
      () => useCompleteReminder(VIN),
      { id: 1, mode: 'link_visit', service_visit_id: 1, completed_date: '2026-11-17' },
    ],
  ]

  it.each(cases)('%s', async (_name, hook, vars) => {
    const qc = await run(hook, vars as never)

    expect(stale(qc, SUPPLIES)).toBe(true)
    expect(stale(qc, HISTORY)).toBe(true)
    expect(stale(qc, USAGES)).toBe(true)
    expect(stale(qc, OTHER_USAGES)).toBe(false) // pricing a visit touches its vehicle only
  })
})
