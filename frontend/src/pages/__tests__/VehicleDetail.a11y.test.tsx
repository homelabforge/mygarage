import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

/**
 * Regression coverage for the two-tablists-one-name defect (P1 task 18).
 *
 * VehicleDetail renders a primary tablist ("Vehicle sections") AND, whenever
 * the active primary tab has sub-tabs, a second tablist rendered by
 * SubTabNav. Before this fix both passed the identical accessible name,
 * so a screen-reader user could not tell the two regions apart, and any
 * getByRole('tablist', { name: 'Vehicle sections' }) query made while a
 * sub-tabbed section was active would be ambiguous.
 *
 * SubTabNav is deliberately NOT mocked here (unlike VehicleDetail.test.tsx)
 * — the defect lives inside the real <Tabs role="tablist" aria-label={label}>
 * markup that SubTabNav renders, and a mock that replaces it with a bare
 * <div> would hide the collision entirely.
 */

vi.mock('../../components/tabs/ServiceTab', () => ({ default: () => <div>ServiceTab</div> }))
vi.mock('../../components/tabs/FuelTab', () => ({ default: () => <div>FuelTab</div> }))
vi.mock('../../components/tabs/OdometerTab', () => ({ default: () => <div>OdometerTab</div> }))
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
vi.mock('../../components/tabs/LiveLinkLiveTab', () => ({ default: () => <div>LiveLinkLiveTab</div> }))
vi.mock('../../components/tabs/LiveLinkDTCsTab', () => ({ default: () => <div>LiveLinkDTCsTab</div> }))
vi.mock('../../components/tabs/LiveLinkSessionsTab', () => ({ default: () => <div>LiveLinkSessionsTab</div> }))
vi.mock('../../components/tabs/LiveLinkChartsTab', () => ({ default: () => <div>LiveLinkChartsTab</div> }))
vi.mock('../../components/TaxRecordList', () => ({ default: () => <div>TaxRecordList</div> }))
vi.mock('../../components/WindowStickerUpload', () => ({ default: () => <div>WindowStickerUpload</div> }))
vi.mock('../../components/modals/VehicleRemoveModal', () => ({ default: () => null }))
vi.mock('../../components/modals/VehicleTransferWizard', () => ({ default: () => null }))
vi.mock('../../components/modals/VehicleSharingModal', () => ({ default: () => null }))
vi.mock('../../components/TransferHistorySection', () => ({ default: () => <div>TransferHistory</div> }))

// Intentionally no mock for '../../components/SubTabNav' — see file header.

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('../../services/vehicleService', () => ({
  default: {
    get: vi.fn(),
  },
}))
vi.mock('../../services/livelinkService', () => ({
  livelinkService: {
    hasLinkedDevice: vi.fn(),
  },
}))
vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
    defaults: { headers: { common: {} } },
  },
}))

vi.mock('../../hooks/useOnlineStatus', () => ({
  useOnlineStatus: vi.fn(() => true),
}))
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: vi.fn(() => ({
    user: { id: 1, username: 'testuser', email: 'test@test.com', is_admin: false },
    token: null,
    isAuthenticated: true,
    isAdmin: false,
    loading: false,
    authMode: 'local',
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    refreshUser: vi.fn(),
    setAuthToken: vi.fn(),
  })),
}))

import vehicleService from '../../services/vehicleService'
import { livelinkService } from '../../services/livelinkService'
import type { Vehicle, VehicleType } from '../../types/vehicle'
import VehicleDetail from '../VehicleDetail'

const mockedVehicleService = vi.mocked(vehicleService)
const mockedLivelinkService = vi.mocked(livelinkService)

const mockVehicle: Vehicle = {
  vin: 'TEST12345678901234',
  nickname: 'Test Car',
  vehicle_type: 'Car' as VehicleType,
  year: 2024,
  make: 'Toyota',
  model: 'Camry',
  license_plate: 'ABC123',
  color: 'Blue',
  purchase_date: '2024-01-15',
  purchase_price: '35000',
  created_at: '2024-01-15T00:00:00Z',
  archived_visible: true,
  location_tracking_enabled: true,
}

function renderVehicleDetail(initialPath = '/vehicles/TEST12345678901234') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/vehicles/:vin" element={<VehicleDetail />} />
        <Route path="/" element={<div>Dashboard</div>} />
      </Routes>
    </MemoryRouter>
  )
}

describe('VehicleDetail — tablist accessible names', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    mockedVehicleService.get.mockResolvedValue(mockVehicle)
    mockedLivelinkService.hasLinkedDevice.mockResolvedValue(false)
  })

  it('gives the sub-tab tablist a different accessible name than the primary tablist', async () => {
    renderVehicleDetail()

    await waitFor(() => {
      expect(screen.getByText('Test Car')).toBeInTheDocument()
    })

    // Activate a primary tab that has sub-tabs (Maintenance -> Service/Odometer/Recalls).
    fireEvent.click(screen.getAllByText('detail.tabs.maintenance')[0])

    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /service/i })).toBeInTheDocument()
    })

    const tablists = screen.getAllByRole('tablist')
    const names = new Set(tablists.map((el) => el.getAttribute('aria-label')))

    // The primary tablist's name is frozen — e2e/vehicle-tabs.spec.ts:72 depends on it.
    expect(names.has('detail.misc.vehicleSections')).toBe(true)

    // The sub-tab tablist must NOT reuse that name. Before the fix, every
    // tablist on screen shared the same aria-label, so this set had size 1
    // even with both a primary and a sub-tab tablist mounted.
    expect(names.size).toBeGreaterThan(1)
  })
})
