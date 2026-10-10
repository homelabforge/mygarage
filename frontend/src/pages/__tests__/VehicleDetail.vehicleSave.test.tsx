/**
 * Every vehicle save on the vehicle page goes through one handler (#172).
 *
 * Each of the five sidecars hands VehicleDetail the server's fresh row, which
 * can carry an odometer unit changed on another device. That row must reach
 * the offline copy and the Quick Entry list, or the NEXT form opens in the old
 * unit. And a unit change must remount the scoped page, so no open form can
 * outlive the unit it opened with.
 *
 * The sidecars and the overview tab are replaced by buttons that call their
 * save callback with the vehicle they were given plus `writer.next`, and the
 * odometer tab by a probe holding local state. The REAL `useUnitPreference`
 * runs (only `AuthContext` is mocked), so the probe reads the true scope.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { METRIC_UNITS } from '../../__tests__/factories'

const writer = vi.hoisted(() => ({
  next: { distance_unit: 'mi' as 'km' | 'mi' | null, nickname: 'Test Car' },
}))

type WriterProps = {
  vehicle: Record<string, unknown>
  onUpdated?: (v: unknown) => void
  onVehicleUpdated?: (v: unknown) => void
  onUploadWindowSticker?: () => void
}

// What the page handed the sticker upload last time it rendered.
type StickerProps = { hasExistingSticker?: boolean; onClose: (uploaded: boolean) => void }
const sticker = vi.hoisted(() => ({ props: null as StickerProps | null }))

vi.mock('../../components/vehicle-detail/EquipmentDrawer', () => ({
  default: (p: WriterProps) => (
    <button onClick={() => p.onUpdated?.({ ...p.vehicle, ...writer.next })}>save-equipment</button>
  ),
}))
vi.mock('../../components/vehicle-detail/PricingDrawer', () => ({
  default: (p: WriterProps) => (
    <button onClick={() => p.onUpdated?.({ ...p.vehicle, ...writer.next })}>save-pricing</button>
  ),
}))
vi.mock('../../components/vehicle-detail/VehicleFieldsDrawer', () => ({
  default: (p: WriterProps) => (
    <button onClick={() => p.onUpdated?.({ ...p.vehicle, ...writer.next })}>save-fields</button>
  ),
}))
vi.mock('../../components/vehicle-detail/VehicleEditDrawer', () => ({
  default: (p: WriterProps) => (
    <>
      <button onClick={() => p.onUpdated?.({ ...p.vehicle, ...writer.next })}>save-edit</button>
      <button onClick={() => p.onUploadWindowSticker?.()}>open-sticker</button>
    </>
  ),
}))
vi.mock('../../components/vehicle-detail/VehicleOverviewTab', () => ({
  default: (p: WriterProps) => (
    <button onClick={() => p.onVehicleUpdated?.({ ...p.vehicle, ...writer.next })}>save-specs</button>
  ),
}))
vi.mock('../../components/tabs/OdometerTab', async () => {
  const { useState } = await import('react')
  const { useUnitPreference } = await import('../../hooks/useUnitPreference')
  return {
    default: function OdometerProbe() {
      const [count, setCount] = useState(0)
      const unit = useUnitPreference().units.distance
      return (
        <div>
          <span data-testid="probe-unit">{unit}</span>
          <span data-testid="probe-count">{count}</span>
          <button onClick={() => setCount((n) => n + 1)}>bump</button>
        </div>
      )
    },
  }
})

vi.mock('../../components/tabs/ServiceTab', () => ({ default: () => <div>ServiceTab</div> }))
vi.mock('../../components/tabs/FuelTab', () => ({ default: () => <div>FuelTab</div> }))
vi.mock('../../components/tabs/HoursTab', () => ({ default: () => <div>HoursTab</div> }))
vi.mock('../../components/tabs/PhotosTab', () => ({ default: () => <div>PhotosTab</div> }))
vi.mock('../../components/tabs/DocumentsTab', () => ({ default: () => <div>DocumentsTab</div> }))
vi.mock('../../components/tabs/NotesTab', () => ({ default: () => <div>NotesTab</div> }))
vi.mock('../../components/tabs/WarrantiesTab', () => ({ default: () => <div>WarrantiesTab</div> }))
vi.mock('../../components/tabs/InsuranceTab', () => ({ default: () => <div>InsuranceTab</div> }))
vi.mock('../../components/tabs/ReportsTab', () => ({ default: () => <div>ReportsTab</div> }))
vi.mock('../../components/tabs/TollsTab', () => ({ default: () => <div>TollsTab</div> }))
vi.mock('../../components/tabs/SafetyTab', () => ({ default: () => <div>SafetyTab</div> }))
vi.mock('../../components/tabs/SpotRentalsTab', () => ({ default: () => <div>SpotRentalsTab</div> }))
vi.mock('../../components/tabs/PropaneTab', () => ({ default: () => <div>PropaneTab</div> }))
vi.mock('../../components/tabs/DEFTab', () => ({ default: () => <div>DEFTab</div> }))
vi.mock('../../components/ReminderList', () => ({ default: () => <div>ReminderList</div> }))
vi.mock('../../components/tabs/LiveLinkLiveTab', () => ({ default: () => <div>LiveLinkLiveTab</div> }))
vi.mock('../../components/tabs/LiveLinkDTCsTab', () => ({ default: () => <div>LiveLinkDTCsTab</div> }))
vi.mock('../../components/tabs/LiveLinkSessionsTab', () => ({ default: () => <div>LiveLinkSessionsTab</div> }))
vi.mock('../../components/tabs/LiveLinkChartsTab', () => ({ default: () => <div>LiveLinkChartsTab</div> }))
vi.mock('../../components/TaxRecordList', () => ({ default: () => <div>TaxRecordList</div> }))
vi.mock('../../components/WindowStickerUpload', () => ({
  default: (p: StickerProps) => {
    sticker.props = p
    return <div>WindowStickerUpload</div>
  },
}))
vi.mock('../../components/modals/VehicleRemoveModal', () => ({ default: () => null }))
vi.mock('../../components/modals/VehicleTransferWizard', () => ({ default: () => null }))
vi.mock('../../components/modals/VehicleSharingModal', () => ({ default: () => null }))
vi.mock('../../components/TransferHistorySection', () => ({ default: () => <div>TransferHistory</div> }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../../services/vehicleService', () => ({
  default: {
    get: vi.fn(),
    getDetailStats: vi.fn(),
    list: vi.fn().mockResolvedValue({ vehicles: [] }),
    getTrailerDetails: vi.fn().mockResolvedValue({}),
    listTowedTrailers: vi.fn().mockResolvedValue([]),
  },
}))
vi.mock('../../services/livelinkService', () => ({
  livelinkService: { getVehicleStatus: vi.fn() },
}))
vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: {} }),
    post: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    defaults: { headers: { common: {} } },
  },
}))
vi.mock('../../hooks/useOnlineStatus', () => ({ useOnlineStatus: vi.fn(() => true) }))
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: vi.fn(() => ({
    user: { id: 1, unit_preference: 'metric', show_both_units: false, resolved_units: METRIC_UNITS },
    isAuthenticated: true,
    isAdmin: false,
    defaultUnitPrefs: null,
    householdTimeZone: null,
    refreshUser: vi.fn(),
    refreshPublicSettings: vi.fn(),
  })),
}))

import vehicleService from '../../services/vehicleService'
import { livelinkService } from '../../services/livelinkService'
import type { Vehicle, VehicleType } from '../../types/vehicle'
import type { QuickEntryVehicle } from '../../hooks/queries/useQuickEntryVehicles'
import { readCachedVehicle } from '../../utils/vehicleCache'
import VehicleDetail from '../VehicleDetail'

const VIN = 'TEST12345678901234'
const vehicle: Vehicle = {
  vin: VIN,
  nickname: 'Test Car',
  vehicle_type: 'Car' as VehicleType,
  usage_unit: 'distance',
  secondary_usage_enabled: false,
  created_at: '2024-01-15T00:00:00Z',
  archived_visible: true,
  location_tracking_enabled: true,
  distance_unit: null,
}

const qeRow = (vin: string): QuickEntryVehicle => ({
  vin,
  nickname: vin,
  year: null,
  make: null,
  model: null,
  vehicle_type: 'Car',
  usage_unit: 'distance',
  secondary_usage_enabled: false,
  thumbnail_url: null,
  distance_unit: null,
})

function renderPage(client: QueryClient, path = `/vehicles/${VIN}`) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/vehicles/:vin" element={<VehicleDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  sticker.props = null
  writer.next = { distance_unit: 'mi', nickname: 'Test Car' }
  vi.mocked(vehicleService.get).mockResolvedValue(vehicle)
  vi.mocked(vehicleService.getDetailStats).mockRejectedValue(new Error('no stats'))
  vi.mocked(livelinkService.getVehicleStatus).mockResolvedValue({
    vin: VIN,
    device_id: null,
    capabilities: [],
    device_status: 'offline',
    online: false,
    ecu_status: 'unknown',
    latest_values: [],
  } as never)
})

describe('one save handler for every vehicle writer', () => {
  it.each(['equipment', 'pricing', 'fields', 'edit', 'specs'])(
    'a %s save refreshes the offline copy and the Quick Entry row',
    async (name) => {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
      client.setQueryData<QuickEntryVehicle[]>(['quickEntryVehicles'], [qeRow(VIN), qeRow('OTHERVIN000000001')])
      renderPage(client)

      fireEvent.click(await screen.findByText(`save-${name}`))

      await waitFor(() => expect(readCachedVehicle(VIN)?.distance_unit).toBe('mi'))
      const rows = client.getQueryData<QuickEntryVehicle[]>(['quickEntryVehicles'])!
      expect(rows.find((r) => r.vin === VIN)?.distance_unit).toBe('mi')
      expect(rows.find((r) => r.vin === 'OTHERVIN000000001')?.distance_unit).toBeNull()
    },
  )

  it('never creates a Quick Entry list that was not cached', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    renderPage(client)

    fireEvent.click(await screen.findByText('save-edit'))

    await waitFor(() => expect(readCachedVehicle(VIN)?.distance_unit).toBe('mi'))
    expect(client.getQueryData(['quickEntryVehicles'])).toBeUndefined()
  })
})

describe('a unit change remounts the scoped page', () => {
  it('an open tab re-reads the new unit with fresh state; a same-unit save keeps its state', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    renderPage(client, `/vehicles/${VIN}?tab=odometer`)

    expect(await screen.findByTestId('probe-unit')).toHaveTextContent('km')
    fireEvent.click(screen.getByText('bump'))
    expect(screen.getByTestId('probe-count')).toHaveTextContent('1')

    // A save that lands with a new unit: remount, so no form outlives its unit.
    fireEvent.click(screen.getByText('save-edit'))
    await waitFor(() => expect(screen.getByTestId('probe-unit')).toHaveTextContent('mi'))
    expect(screen.getByTestId('probe-count')).toHaveTextContent('0')

    // A save that keeps the unit remounts nothing.
    fireEvent.click(screen.getByText('bump'))
    writer.next = { distance_unit: 'mi', nickname: 'Renamed' }
    fireEvent.click(screen.getByText('save-edit'))
    await waitFor(() => expect(readCachedVehicle(VIN)?.nickname).toBe('Renamed'))
    expect(screen.getByTestId('probe-count')).toHaveTextContent('1')
  })
})

describe('the window sticker upload', () => {
  const openSticker = async (): Promise<StickerProps> => {
    fireEvent.click(await screen.findByText('open-sticker'))
    await screen.findByText('WindowStickerUpload')
    return sticker.props!
  }

  it('is told a sticker is on file when the vehicle has one', async () => {
    vi.mocked(vehicleService.get).mockResolvedValue({
      ...vehicle,
      window_sticker_file_path: '/data/documents/TEST/window_sticker_a.pdf',
    })
    renderPage(new QueryClient({ defaultOptions: { queries: { retry: false } } }))

    expect((await openSticker()).hasExistingSticker).toBe(true)
  })

  it('is told there is none when the vehicle has no sticker path', async () => {
    renderPage(new QueryClient({ defaultOptions: { queries: { retry: false } } }))

    expect((await openSticker()).hasExistingSticker).toBe(false)
  })

  it('reloads the vehicle on a close after an upload, and only then', async () => {
    renderPage(new QueryClient({ defaultOptions: { queries: { retry: false } } }))

    const first = await openSticker()
    act(() => first.onClose(false))
    await waitFor(() => expect(screen.queryByText('WindowStickerUpload')).not.toBeInTheDocument())
    expect(vehicleService.get).toHaveBeenCalledTimes(1)

    // The upload committed before the review, so the page has to catch up.
    const second = await openSticker()
    act(() => second.onClose(true))
    await waitFor(() => expect(vehicleService.get).toHaveBeenCalledTimes(2))
    expect(screen.queryByText('WindowStickerUpload')).not.toBeInTheDocument()
  })
})
