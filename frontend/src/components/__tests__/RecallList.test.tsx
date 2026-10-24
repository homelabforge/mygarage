import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import type { Recall } from '../../types/recall'

const useRecallRecordsMock = vi.fn()
const deleteMutate = vi.fn()
const toggleMutate = vi.fn()
const nhtsaMutate = vi.fn()
const invalidateQueries = vi.fn()

vi.mock('../../hooks/queries/useRecallRecords', () => ({
  useRecallRecords: (...a: unknown[]) => useRecallRecordsMock(...a),
  useDeleteRecallRecord: () => ({ mutate: deleteMutate, isPending: false, variables: undefined }),
  useCheckNHTSA: () => ({ mutate: nhtsaMutate, isPending: false }),
  useToggleRecallResolved: () => ({ mutate: toggleMutate, isPending: false }),
}))
vi.mock('@tanstack/react-query', () => ({ useQueryClient: () => ({ invalidateQueries }) }))
// Answers per URL: the vehicle for the CarComplaints link, and the public
// settings for the two switches. /settings is admin-only, so it refuses, as it
// does for a non-admin.
const apiGet = vi.hoisted(() => vi.fn())
vi.mock('../../services/api', () => ({ default: { get: apiGet } }))
vi.mock('../../hooks/useDateLocale', () => ({ useDateLocale: () => 'en-US' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import { toast } from 'sonner'
import RecallList from '../RecallList'

const VEHICLE = { vin: 'V1', year: 2020, make: 'Honda', model: 'Civic', vehicle_type: 'Car' }

/** Serves `public` as /settings/public (or fails it), the vehicle, and a 403 from /settings. */
function serve(publicSettings: { key: string; value: string }[] | Error = []): void {
  apiGet.mockImplementation((url: string) => {
    if (url === '/settings/public') {
      return publicSettings instanceof Error
        ? Promise.reject(publicSettings)
        : Promise.resolve({ data: { settings: publicSettings } })
    }
    if (url === '/vehicles/V1') return Promise.resolve({ data: VEHICLE })
    return Promise.reject({ response: { status: 403 } })
  })
}

const active = {
  id: 1, vin: 'V1', component: 'Airbag Inflator', nhtsa_campaign_number: '23V123000',
  summary: 'Inflator may rupture', consequence: '', remedy: '', notes: '',
  date_announced: '2026-02-01', is_resolved: false, resolved_at: null,
} as unknown as Recall

const onAddClick = vi.fn()
const onEditClick = vi.fn()
const PROPS = { vin: 'V1', onAddClick, onEditClick, onRefresh: vi.fn() }

beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  serve()
  useRecallRecordsMock.mockReturnValue({ data: { recalls: [active], total: 1, active_count: 1, resolved_count: 0 }, isLoading: false, error: null })
})

describe('RecallList — rendering + row actions', () => {
  it('renders the component title and the NHTSA campaign identifier (fails if the title or the Mono campaign chip is dropped)', () => {
    render(<RecallList {...PROPS} />)
    expect(screen.getByText('Airbag Inflator')).toBeInTheDocument()
    expect(screen.getByText('23V123000')).toBeInTheDocument()
  })

  it('clicking Edit calls onEditClick with THE WHOLE recall (fails if edit is unwired or passes a truncated object)', () => {
    render(<RecallList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:edit' }))
    expect(onEditClick).toHaveBeenCalledWith(active)
  })

  it('clicking Delete (confirm accepted) calls the delete mutation with the recall id (fails if delete is unwired or the confirm gate is dropped)', () => {
    render(<RecallList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'common:delete' }))
    expect(window.confirm).toHaveBeenCalled()
    expect(deleteMutate).toHaveBeenCalledWith(1, expect.anything())
  })
})

describe('RecallList — mark-resolved toggles BOTH directions (status true AND false)', () => {
  it('an ACTIVE recall offers markResolved → toggles to isResolved:true (fails if the toggle target is inverted)', () => {
    render(<RecallList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'recallList.markResolved' }))
    expect(toggleMutate).toHaveBeenCalledWith({ recallId: 1, isResolved: true }, expect.anything())
  })

  it('a RESOLVED recall offers markActive → toggles to isResolved:false (fails if the false branch is missing or swapped)', () => {
    useRecallRecordsMock.mockReturnValue({ data: { recalls: [{ ...active, is_resolved: true, resolved_at: '2026-03-01' }], total: 1, active_count: 0, resolved_count: 1 }, isLoading: false, error: null })
    render(<RecallList {...PROPS} />)
    fireEvent.click(screen.getByRole('button', { name: 'recallList.markActive' }))
    expect(toggleMutate).toHaveBeenCalledWith({ recallId: 1, isResolved: false }, expect.anything())
  })
})

describe('RecallList — status filter + empty state + refresh wiring', () => {
  it('changing the status filter re-queries with the selected filter (fails if the select is unwired)', () => {
    render(<RecallList {...PROPS} />)
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'active' } })
    expect(useRecallRecordsMock).toHaveBeenLastCalledWith('V1', 'active')
  })

  it('with zero recalls, the "add manual entry" CTA fires onAddClick (fails if the two-CTA empty state is unwired)', () => {
    useRecallRecordsMock.mockReturnValue({ data: { recalls: [], total: 0, active_count: 0, resolved_count: 0 }, isLoading: false, error: null })
    render(<RecallList {...PROPS} />)
    expect(screen.getByText('recallList.noRecords')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'recallList.addManualEntry' }))
    expect(onAddClick).toHaveBeenCalled()
  })

  it('a recalls-refresh window event invalidates the recalls query (fails if the restyle disturbs the event subscription)', async () => {
    render(<RecallList {...PROPS} />)
    window.dispatchEvent(new Event('recalls-refresh'))
    await waitFor(() => expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ['recalls', 'V1'] }))
  })
})

describe('RecallList — resolved timestamp', () => {
  it('renders the resolved date from the wire-shaped datetime (fails with "Invalid Date" if it is fed to the date-only formatter)', () => {
    // resolved_at is a backend datetime, serialised naive: no Z, no offset.
    useRecallRecordsMock.mockReturnValue({ data: { recalls: [{ ...active, is_resolved: true, resolved_at: '2026-03-01T12:00:00' }], total: 1, active_count: 0, resolved_count: 1 }, isLoading: false, error: null })
    render(<RecallList {...PROPS} />)
    expect(screen.getByText('Mar 1, 2026')).toBeInTheDocument()
    expect(screen.queryByText(/Invalid Date/)).toBeNull()
  })
})

describe('RecallList — the NHTSA and CarComplaints switches come from /settings/public', () => {
  const checkButton = (): HTMLElement => screen.getByRole('button', { name: 'recallList.checkNHTSA' })

  it('with nhtsa_enabled "false", Check NHTSA is disabled and a line says where to switch it on', async () => {
    serve([{ key: 'nhtsa_enabled', value: 'false' }])
    render(<RecallList {...PROPS} />)

    expect(await screen.findByText('recallList.nhtsaSwitchedOff')).toBeInTheDocument()
    expect(checkButton()).toBeDisabled()
  })

  it('with nhtsa_enabled off, the empty state\'s Check NHTSA is disabled too', async () => {
    useRecallRecordsMock.mockReturnValue({ data: { recalls: [], total: 0, active_count: 0, resolved_count: 0 }, isLoading: false, error: null })
    serve([{ key: 'nhtsa_enabled', value: 'off' }])
    render(<RecallList {...PROPS} />)

    await screen.findByText('recallList.nhtsaSwitchedOff')
    for (const button of screen.getAllByRole('button', { name: 'recallList.checkNHTSA' })) {
      expect(button).toBeDisabled()
    }
  })

  // The fallback (Fable F2-4): absent or unreadable reads as on, the backend's
  // default, so a failed read never takes the button away; the 409 rules.
  it.each([
    ['absent', []],
    ['unreadable', new Error('down')],
  ] as const)('with the switch %s, Check NHTSA stays enabled', async (_case, payload) => {
    serve(payload instanceof Error ? payload : [...payload])
    render(<RecallList {...PROPS} />)

    await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/settings/public'))
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/vehicles/V1'))
    expect(checkButton()).toBeEnabled()
    expect(screen.queryByText('recallList.nhtsaSwitchedOff')).not.toBeInTheDocument()
  })

  // Regression guard: getActionErrorMessage already shows a 409's detail. It
  // pins that the switched-off 409 reaches the user as the backend wrote it.
  it("a 409 from the check toasts the backend's detail", async () => {
    const detail = 'NHTSA recalls are switched off in Settings > Integrations'
    nhtsaMutate.mockImplementationOnce((_vars: unknown, opts: { onError: (e: unknown) => void }) =>
      opts.onError({ isAxiosError: true, message: 'Request failed', response: { status: 409, data: { detail } } }),
    )
    render(<RecallList {...PROPS} />)
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/vehicles/V1'))

    fireEvent.click(checkButton())

    expect(vi.mocked(toast.error)).toHaveBeenCalledWith(detail)
  })

  it('with carcomplaints_enabled "true" in the public payload, a non-admin gets the CarComplaints link', async () => {
    serve([{ key: 'carcomplaints_enabled', value: 'true' }])
    render(<RecallList {...PROPS} />)

    expect(await screen.findByText('recallList.viewOnCarComplaints')).toBeInTheDocument()
    expect(apiGet).not.toHaveBeenCalledWith('/settings')
  })

  // CarComplaints keeps its fallback (off) when the key is absent.
  it('with carcomplaints_enabled absent, there is no CarComplaints link', async () => {
    render(<RecallList {...PROPS} />)

    await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/vehicles/V1'))
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/settings/public'))
    expect(screen.queryByText('recallList.viewOnCarComplaints')).not.toBeInTheDocument()
  })
})
