import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactNode } from 'react'
import { render, screen, waitFor, within } from '../../../__tests__/test-utils'
import { fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { VehicleDTC, VehicleDTCListResponse } from '../../../types/livelink'
import type { DTCListFilter } from '@/services/livelinkService'

// ─────────────────────────────────────────────────────────────────────────────
// Harness note (mirrors the Task-1 LiveLinkLiveTab precedent: assertions/fixtures
// are exactly the brief's, only the flush mechanism differs):
//
// `fetchDTCs` lists `t` in its `useCallback` deps and the mount effect depends on
// `fetchDTCs`. The GLOBAL react-i18next mock (src/__tests__/setup.ts) returns a
// FRESH `t` on every render, so `fetchDTCs` is a new reference every render and
// `useEffect([fetchDTCs])` re-fires after each data-commit re-render — an extra
// refetch loop that makes the exact `getVehicleDTCs.mock.calls` arrays this suite
// asserts (`[['V1', true], ['V1', false]]`) impossible. Real react-i18next
// memoizes `t`, so this loop is a TEST artifact, never a production behaviour.
// We override the mock LOCALLY with a STABLE module-level `t` (same key-echo
// shape as the global mock) so `fetchDTCs` is stable across renders — the fetch
// fires once per filter change, exactly as in production.
// ─────────────────────────────────────────────────────────────────────────────
vi.mock('react-i18next', () => {
  // A `{ code }` call shows its code, so a name can be told apart per DTC.
  const t = (key: string, opts?: { code?: string }) => (opts?.code !== undefined ? `${key} ${opts.code}` : key)
  return {
    useTranslation: () => ({
      t,
      i18n: { language: 'en', changeLanguage: () => Promise.resolve() },
    }),
    Trans: ({ children }: { children: ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

const getVehicleDTCs = vi.fn()
const clearVehicleDTC = vi.fn().mockResolvedValue({})
const updateVehicleDTC = vi.fn().mockResolvedValue({})
vi.mock('@/services/livelinkService', () => ({
  livelinkService: {
    getVehicleDTCs: (vin: string, filter: DTCListFilter) => getVehicleDTCs(vin, filter),
    clearVehicleDTC: (vin: string, id: number) => clearVehicleDTC(vin, id),
    updateVehicleDTC: (vin: string, id: number, update: unknown) => updateVehicleDTC(vin, id, update),
  },
}))
vi.mock('@/utils/parseAPITimestamp', () => ({ formatAPITimestamp: () => '2026-07-26' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import LiveLinkDTCsTab from '../LiveLinkDTCsTab'

// B2 + M1: three DISTINCT states so active-critical, active-info and cleared are never conflated —
// contract-valid typed builders (`satisfies VehicleDTC`, all required fields incl. `vin`/`device_id`/
// `created_at`) so schema drift fails at type-check, no `as unknown as`.
const activeCriticalDtc = {
  id: 42, vin: 'V1', device_id: 'DEV1', code: 'P0301', description: 'Cylinder 1 Misfire',
  severity: 'critical', is_active: true, is_emissions_related: true,
  first_seen: 'x', last_seen: 'x', created_at: 'x', cleared_at: null,
  category: 'Powertrain', user_notes: null,
} satisfies VehicleDTC
const activeInfoDtc = {
  id: 8, vin: 'V1', device_id: 'DEV1', code: 'P0420', description: 'Catalyst Efficiency',
  severity: 'info', is_active: true, is_emissions_related: false,
  first_seen: 'x', last_seen: 'x', created_at: 'x', cleared_at: null,
  category: null, user_notes: null,
} satisfies VehicleDTC
const clearedDtc = {
  id: 7, vin: 'V1', device_id: 'DEV1', code: 'P0100', description: 'MAF Circuit',
  severity: 'info', is_active: false, is_emissions_related: false,
  first_seen: 'x', last_seen: 'x', created_at: 'x', cleared_at: 'x',
  category: null, user_notes: null,
} satisfies VehicleDTC
const list = (over: Partial<VehicleDTCListResponse> = {}) =>
  ({ dtcs: [activeCriticalDtc], active_count: 1, critical_count: 1, total: 1, ...over }) satisfies VehicleDTCListResponse

beforeEach(() => {
  vi.clearAllMocks()
  getVehicleDTCs.mockResolvedValue(list())
})

describe('LiveLinkDTCsTab — rendering + status markers', () => {
  it('fetches active DTCs on mount and renders the code + description (fails if the default fetch or the list render breaks)', async () => {
    render(<LiveLinkDTCsTab vin="V1" />)
    await waitFor(() => expect(getVehicleDTCs.mock.calls).toStrictEqual([['V1', 'active']]))
    expect(await screen.findByText('P0301')).toBeInTheDocument()
    expect(screen.getByText('Cylinder 1 Misfire')).toBeInTheDocument()
  })

  it('distinguishes critical (triangle icon) from info (info icon) severity — both ACTIVE (fails if getSeverityIcon collapses to one icon)', async () => {
    // Both fixtures are is_active:true so the DEFAULT active filter renders each — severity is the only
    // difference. The severity icon (getSeverityIcon) is the structural discriminator: critical → lucide
    // AlertTriangle (svg.lucide-triangle-alert), info → lucide Info (svg.lucide-info). ★ R2-M1: scope BOTH
    // assertions to the DTC ROW (the `.flex.items-start.gap-3` ancestor of the code) — the critical fixture's
    // critical_count:1 renders a SUMMARY AlertTriangle in the header, so a container-wide query would let the
    // critical assertion pass even if the ROW severity icon were removed/changed.
    const critical = render(<LiveLinkDTCsTab vin="V1" />) // default list = activeCriticalDtc
    const criticalRow = (await critical.findByText('P0301')).closest('.flex.items-start.gap-3')!
    expect(criticalRow.querySelector('svg.lucide-triangle-alert')).toBeTruthy()
    expect(criticalRow.querySelector('svg.lucide-info')).toBeNull()
    critical.unmount()

    getVehicleDTCs.mockResolvedValue(list({ dtcs: [activeInfoDtc], active_count: 1, critical_count: 0, total: 1 }))
    const info = render(<LiveLinkDTCsTab vin="V1" />)
    const infoRow = (await info.findByText('P0420')).closest('.flex.items-start.gap-3')!
    expect(infoRow.querySelector('svg.lucide-info')).toBeTruthy()
    expect(infoRow.querySelector('svg.lucide-triangle-alert')).toBeNull()
  })

  it('shows the emissions + critical-count markers for an active emissions/critical DTC and not the cleared marker (status both ways)', async () => {
    render(<LiveLinkDTCsTab vin="V1" />) // default list = activeCriticalDtc (emissions + critical, active)
    expect(await screen.findByText('livelink.dtcs.emissions')).toBeInTheDocument()
    expect(screen.getByText('livelink.dtcs.criticalCount')).toBeInTheDocument()
    // an active/critical DTC is NOT "cleared"
    expect(screen.queryByText('livelink.dtcs.cleared')).not.toBeInTheDocument()
  })

  it('shows the cleared marker (and no emissions/critical) after switching to the Cleared filter (fails if the filter refetch or the cleared render breaks)', async () => {
    // B2: the component starts on the ACTIVE filter and locally drops is_active:false rows, so a cleared
    // DTC can only reach the DOM via the Cleared filter. CLICK filterCleared → the refetch is
    // getVehicleDTCs('V1', 'cleared'); mock THAT response to a cleared (is_active:false) DTC, then assert.
    render(<LiveLinkDTCsTab vin="V1" />)
    await screen.findByText('P0301') // initial active fetch rendered
    getVehicleDTCs.mockResolvedValue(list({ dtcs: [clearedDtc], active_count: 0, critical_count: 0, total: 1 }))
    fireEvent.click(screen.getByRole('button', { name: 'livelinkDtcs.filterCleared' }))
    await waitFor(() => expect(getVehicleDTCs.mock.calls).toStrictEqual([['V1', 'active'], ['V1', 'cleared']]))
    expect(await screen.findByText('livelink.dtcs.cleared')).toBeInTheDocument()
    expect(screen.queryByText('livelink.dtcs.emissions')).not.toBeInTheDocument()
    expect(screen.queryByText('livelink.dtcs.criticalCount')).not.toBeInTheDocument()
  })
})

describe('LiveLinkDTCsTab — clear DTC (native confirm, LD5)', () => {
  it('clear accepted → clearVehicleDTC(vin, id) fires (fails if the id is wrong or the mutation unwired)', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<LiveLinkDTCsTab vin="V1" />)
    await screen.findByText('P0301')
    fireEvent.click(screen.getByRole('button', { name: 'livelink.dtcs.markAsCleared' }))
    await waitFor(() => expect(clearVehicleDTC.mock.calls).toStrictEqual([['V1', 42]])) // M1: exact identity (vin, id)
  })

  it('clear rejected → clearVehicleDTC is NOT called (fails if the confirm gate is dropped, D16)', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<LiveLinkDTCsTab vin="V1" />)
    await screen.findByText('P0301')
    fireEvent.click(screen.getByRole('button', { name: 'livelink.dtcs.markAsCleared' }))
    expect(clearVehicleDTC.mock.calls).toStrictEqual([]) // M1: exact — NO call fired
  })
})

describe('LiveLinkDTCsTab — notes edit + filter + a11y', () => {
  it('saving notes calls updateVehicleDTC(vin, id, { user_notes }) with the typed text (fails if the notes value is dropped)', async () => {
    const user = userEvent.setup()
    render(<LiveLinkDTCsTab vin="V1" />)
    await screen.findByText('P0301')
    // trigger button reads the placeholder (no notes yet)
    fireEvent.click(screen.getByRole('button', { name: 'livelink.dtcs.addNotesFor P0301' }))
    await user.type(screen.getByPlaceholderText('livelink.dtcs.addNotesPlaceholder'), 'oil leak')
    fireEvent.click(screen.getByRole('button', { name: 'livelinkDtcs.saveNotes' }))
    await waitFor(() => expect(updateVehicleDTC.mock.calls).toStrictEqual([['V1', 42, { user_notes: 'oil leak' }]]))
  })

  it('switching to the Cleared filter refetches with the cleared filter (fails if the filter no longer drives the fetch)', async () => {
    render(<LiveLinkDTCsTab vin="V1" />)
    await waitFor(() => expect(getVehicleDTCs.mock.calls).toStrictEqual([['V1', 'active']]))
    fireEvent.click(screen.getByRole('button', { name: 'livelinkDtcs.filterCleared' }))
    await waitFor(() => expect(getVehicleDTCs.mock.calls).toStrictEqual([['V1', 'active'], ['V1', 'cleared']]))
  })

  it('the row action buttons expose aria-label (a11y gain from IconButton — genuine RED pre-restyle)', async () => {
    render(<LiveLinkDTCsTab vin="V1" />)
    await screen.findByText('P0301')
    expect(screen.getByRole('button', { name: 'livelink.dtcs.searchOnline' })).toHaveAttribute('aria-label', 'livelink.dtcs.searchOnline')
    expect(screen.getByRole('button', { name: 'livelink.dtcs.markAsCleared' })).toHaveAttribute('aria-label', 'livelink.dtcs.markAsCleared')
  })
})

describe('LiveLinkDTCsTab: the notes controls name their DTC (G2b-20)', () => {
  const twoCodes = () => list({ dtcs: [activeCriticalDtc, activeInfoDtc], active_count: 2, critical_count: 1, total: 2 })

  // An empty trigger read "Add notes... P0420"; it says "Add notes for P0420" now.
  it('each notes trigger names its code, so two empty ones sound different', async () => {
    getVehicleDTCs.mockResolvedValue(twoCodes())
    render(<LiveLinkDTCsTab vin="V1" />)
    await screen.findByText('P0301')
    expect(screen.getByRole('button', { name: 'livelink.dtcs.addNotesFor P0301' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'livelink.dtcs.addNotesFor P0420' })).toBeInTheDocument()
  })

  it('a trigger with notes reads the notes first, then the code', async () => {
    getVehicleDTCs.mockResolvedValue(list({ dtcs: [{ ...activeCriticalDtc, user_notes: 'oil leak' }] }))
    render(<LiveLinkDTCsTab vin="V1" />)
    expect(await screen.findByRole('button', { name: 'oil leak P0301' })).toBeInTheDocument()
  })

  it('the notes box is labelled with the code it belongs to', async () => {
    getVehicleDTCs.mockResolvedValue(twoCodes())
    render(<LiveLinkDTCsTab vin="V1" />)
    await screen.findByText('P0420')
    fireEvent.click(screen.getByRole('button', { name: 'livelink.dtcs.addNotesFor P0420' }))
    expect(screen.getByRole('textbox', { name: 'livelink.dtcs.notesFor P0420' })).toHaveFocus()
  })
})

describe('LiveLinkDTCsTab: card text for codes with no definition', () => {
  // The bundled definitions leave out the maker ranges, so a P1 code with no
  // description is expected, not unknown. A generic code still reads unknown.
  const noDescription = (id: number, code: string) =>
    ({
      ...activeInfoDtc, id, code, description: null,
    }) satisfies VehicleDTC

  it('a maker-range code says it is manufacturer-specific and a generic one stays unknown', async () => {
    getVehicleDTCs.mockResolvedValue(
      list({ dtcs: [noDescription(1, 'P1131'), noDescription(2, 'P0420')], active_count: 2, critical_count: 0, total: 2 }),
    )
    render(<LiveLinkDTCsTab vin="V1" />)
    const makerRow = (await screen.findByText('P1131')).closest('.flex.items-start.gap-3') as HTMLElement
    const genericRow = screen.getByText('P0420').closest('.flex.items-start.gap-3') as HTMLElement
    expect(within(makerRow).getByText('livelink.dtcs.manufacturerSpecific')).toBeInTheDocument()
    expect(within(makerRow).queryByText('livelink.dtcs.unknownCode')).not.toBeInTheDocument()
    expect(within(genericRow).getByText('livelink.dtcs.unknownCode')).toBeInTheDocument()
    expect(within(genericRow).queryByText('livelink.dtcs.manufacturerSpecific')).not.toBeInTheDocument()
  })

  it('the stored category goes through t()', async () => {
    getVehicleDTCs.mockResolvedValue(list({ dtcs: [{ ...activeInfoDtc, category: 'powertrain' }], critical_count: 0 }))
    render(<LiveLinkDTCsTab vin="V1" />)
    await screen.findByText('P0420')
    expect(screen.getByText(/livelink\.dtcs\.categories\.powertrain/)).toBeInTheDocument()
  })
})
