/**
 * A line item can link a recall and a warranty, so each side shows the other:
 * the visit list has recall/warranty chips, the Recalls tab has the visit that
 * fixed it, the Warranties tab what was done under it. A write on either side
 * has to mark the other family stale, or the tab you switch to shows the old
 * link (R1-M1). Every case seeds all three families first, so a missing
 * invalidation reads as a stale entry and not as a never-fetched one.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import {
  useCreateServiceVisit,
  useDeleteServiceVisit,
  useUpdateServiceVisit,
} from '../useServiceVisits'
import {
  useCheckNHTSA,
  useCheckRecalls,
  useCreateRecallRecord,
  useDeleteRecallRecord,
  useToggleRecallResolved,
  useUpdateRecallRecord,
} from '../useRecallRecords'
import {
  useCreateWarrantyRecord,
  useDeleteWarrantyRecord,
  useUpdateWarrantyRecord,
} from '../useWarrantyRecords'
import api from '@/services/api'

vi.mock('@/services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

const VIN = 'VIN1'
const OTHER = 'VIN2'

const VISITS = ['serviceVisits', VIN] as const
const VISIT_PAGES = ['serviceVisits', VIN, 'pages'] as const
const RECALLS = ['recalls', VIN, 'all'] as const
const WARRANTIES = ['warranties', VIN] as const

function seededClient(): QueryClient {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  for (const vin of [VIN, OTHER]) {
    qc.setQueryData(['serviceVisits', vin], { visits: [], total: 0 })
    qc.setQueryData(['serviceVisits', vin, 'pages'], { pages: [], pageParams: [] })
    qc.setQueryData(['recalls', vin, 'all'], { recalls: [], total: 0, active_count: 0, resolved_count: 0 })
    qc.setQueryData(['warranties', vin], [])
  }
  return qc
}

function stale(qc: QueryClient, key: readonly unknown[]): boolean | undefined {
  return qc.getQueryState(key)?.isInvalidated
}

/** Runs one mutation on a seeded cache and hands the cache back. */
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

describe('a visit write marks the recalls and warranties stale', () => {
  const cases: [string, () => { mutateAsync: (vars: never) => Promise<unknown> }, unknown][] = [
    ['create', () => useCreateServiceVisit(VIN), { date: '2026-11-03', line_items: [] }],
    ['update', () => useUpdateServiceVisit(VIN), { id: 1, date: '2026-11-03' }],
    ['delete', () => useDeleteServiceVisit(VIN), 1],
  ]

  it.each(cases)('%s', async (_name, hook, vars) => {
    const qc = await run(hook, vars as never)

    expect(stale(qc, RECALLS)).toBe(true)
    expect(stale(qc, WARRANTIES)).toBe(true)
    // Scoped to this vehicle.
    expect(stale(qc, ['recalls', OTHER, 'all'])).toBe(false)
    expect(stale(qc, ['warranties', OTHER])).toBe(false)
  })
})

describe('a recall write marks the service visits stale', () => {
  const cases: [string, () => { mutateAsync: (vars: never) => Promise<unknown> }, unknown][] = [
    ['create', () => useCreateRecallRecord(VIN), { component: 'Air bags', summary: 'x' }],
    ['update', () => useUpdateRecallRecord(VIN), { id: 1, component: 'Air bags' }],
    ['delete', () => useDeleteRecallRecord(VIN), 1],
    ['toggle', () => useToggleRecallResolved(VIN), { recallId: 1, isResolved: false }],
    ['NHTSA check', () => useCheckNHTSA(VIN), undefined],
    ['every-source check', () => useCheckRecalls(VIN), undefined],
  ]

  it.each(cases)('%s', async (_name, hook, vars) => {
    const qc = await run(hook, vars as never)

    expect(stale(qc, VISITS)).toBe(true)
    expect(stale(qc, VISIT_PAGES)).toBe(true)
    expect(stale(qc, RECALLS)).toBe(true)
    expect(stale(qc, ['serviceVisits', OTHER])).toBe(false)
  })
})

describe('a warranty write marks the service visits stale', () => {
  const cases: [string, () => { mutateAsync: (vars: never) => Promise<unknown> }, unknown][] = [
    ['create', () => useCreateWarrantyRecord(VIN), { warranty_type: 'Powertrain', start_date: '2026-01-01' }],
    ['update', () => useUpdateWarrantyRecord(VIN), { id: 1, provider: 'Toyota' }],
    ['delete', () => useDeleteWarrantyRecord(VIN), 1],
  ]

  it.each(cases)('%s', async (_name, hook, vars) => {
    const qc = await run(hook, vars as never)

    expect(stale(qc, VISITS)).toBe(true)
    expect(stale(qc, VISIT_PAGES)).toBe(true)
    expect(stale(qc, WARRANTIES)).toBe(true)
    expect(stale(qc, ['serviceVisits', OTHER])).toBe(false)
  })
})

describe('a refused Mark active still refreshes the recall', () => {
  it('a 409 marks the recalls and visits stale, so the card comes back linked', async () => {
    vi.mocked(api.put).mockRejectedValueOnce({ isAxiosError: true, response: { status: 409, data: { detail: 'linked' } } })
    const qc = seededClient()
    const { result } = renderHook(() => useToggleRecallResolved(VIN), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={qc}>{children}</QueryClientProvider>
      ),
    })

    await expect(result.current.mutateAsync({ recallId: 1, isResolved: false })).rejects.toBeTruthy()

    expect(stale(qc, RECALLS)).toBe(true)
    expect(stale(qc, VISITS)).toBe(true)
  })
})
