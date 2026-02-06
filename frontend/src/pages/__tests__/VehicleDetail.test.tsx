import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

// Mock all tab components to avoid deep dependency trees
vi.mock('../../components/tabs/ServiceTab', () => ({ default: () => <div>ServiceTab</div> }))
vi.mock('../../components/tabs/FuelTab', () => ({ default: () => <div>FuelTab</div> }))
vi.mock('../../components/tabs/OdometerTab', () => ({ default: () => <div>OdometerTab</div> }))
vi.mock('../../components/tabs/PhotosTab', () => ({ default: () => <div>PhotosTab</div> }))
vi.mock('../../components/tabs/DocumentsTab', () => ({ default: () => <div>DocumentsTab</div> }))
vi.mock('../../components/tabs/RemindersTab', () => ({ default: () => <div>RemindersTab</div> }))
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
vi.mock('../../components/SubTabNav', () => ({
  default: ({ tabs, activeTab, onTabChange }: { tabs: { id: string; label: string }[]; activeTab: string; onTabChange: (id: string) => void }) => (
    <div data-testid="sub-tab-nav">
      {tabs.map((tab: { id: string; label: string }) => (
        <button
          key={tab.id}
          role="tab"
          aria-selected={activeTab === tab.id}
          onClick={() => onTabChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  ),
}))

// Mock sonner toast
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// Mock services
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

// Mock hooks
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

// Import after mocks
import vehicleService from '../../services/vehicleService'
import { livelinkService } from '../../services/livelinkService'
import { useAuth } from '../../contexts/AuthContext'
import type { VehicleType } from '../../types/vehicle'
import VehicleDetail from '../VehicleDetail'

const mockedVehicleService = vi.mocked(vehicleService)
const mockedLivelinkService = vi.mocked(livelinkService)
const mockedUseAuth = vi.mocked(useAuth)

const mockVehicle = {
  vin: 'TEST12345678901234',
  nickname: 'Test Car',
  vehicle_type: 'Car' as VehicleType,
  year: 2024,
  make: 'Toyota',
  model: 'Camry',
  license_plate: 'ABC123',
  color: 'Blue',
  purchase_date: '2024-01-15',
  purchase_price: 35000,
  created_at: '2024-01-15T00:00:00Z',
  main_photo: undefined,
  sold_date: undefined,
  has_propane: false,
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

describe('VehicleDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    mockedVehicleService.get.mockResolvedValue(mockVehicle)
    mockedLivelinkService.hasLinkedDevice.mockResolvedValue(false)
  })

  // --- Loading & Error States ---

  it('shows loading spinner initially', () => {
    mockedVehicleService.get.mockReturnValue(new Promise(() => {}))

    renderVehicleDetail()

    expect(screen.getByRole('status', { name: /loading vehicle/i })).toBeInTheDocument()
  })

  it('renders vehicle info after successful load', async () => {
    renderVehicleDetail()

    await waitFor(() => {
      expect(screen.getByText('Test Car')).toBeInTheDocument()
    })
    expect(screen.getByText('2024 Toyota Camry')).toBeInTheDocument()
    expect(screen.getAllByText('TEST12345678901234').length).toBeGreaterThanOrEqual(1)
  })

  it('shows error state when API fails and no cache available', async () => {
    mockedVehicleService.get.mockRejectedValue(new Error('Network Error'))

    renderVehicleDetail()

    await waitFor(() => {
      expect(screen.getByText('Network Error')).toBeInTheDocument()
    })
    expect(screen.getByText('Back to Dashboard')).toBeInTheDocument()
  })

  // --- Caching ---

  it('writes to localStorage cache on successful load', async () => {
    renderVehicleDetail()

    await waitFor(() => {
      expect(screen.getByText('Test Car')).toBeInTheDocument()
    })

    const cached = localStorage.getItem('vehicle-cache-TEST12345678901234')
    expect(cached).not.toBeNull()
    const parsed = JSON.parse(cached!)
    expect(parsed.data.vin).toBe('TEST12345678901234')
    expect(parsed.timestamp).toBeGreaterThan(0)
  })

  it('shows cached data with warning when offline', async () => {
    // Pre-populate cache
    localStorage.setItem(
      'vehicle-cache-TEST12345678901234',
      JSON.stringify({ timestamp: Date.now(), data: mockVehicle })
    )

    // navigator.onLine controls the cache fallback in loadVehicle
    const originalOnLine = navigator.onLine
    Object.defineProperty(navigator, 'onLine', { value: false, configurable: true })

    mockedVehicleService.get.mockRejectedValue(new Error('Network Error'))

    renderVehicleDetail()

    await waitFor(() => {
      expect(screen.getByText('Test Car')).toBeInTheDocument()
    })
    expect(screen.getByText(/offline.*cached/i)).toBeInTheDocument()
    // Should NOT show error page
    expect(screen.queryByText('Back to Dashboard')).not.toBeInTheDocument()

    Object.defineProperty(navigator, 'onLine', { value: originalOnLine, configurable: true })
  })

  it('shows error when offline and no cache exists', async () => {
    const originalOnLine = navigator.onLine
    Object.defineProperty(navigator, 'onLine', { value: false, configurable: true })

    mockedVehicleService.get.mockRejectedValue(new Error('Network Error'))

    renderVehicleDetail()

    await waitFor(() => {
      expect(screen.getByText('Network Error')).toBeInTheDocument()
    })

    Object.defineProperty(navigator, 'onLine', { value: originalOnLine, configurable: true })
  })

  // --- Tab Navigation ---

  it('defaults to overview tab showing vehicle details', async () => {
    renderVehicleDetail()

    await waitFor(() => {
      expect(screen.getByText('Test Car')).toBeInTheDocument()
    })

    // Overview tab should be active (no sub-tab nav shown for overview)
    expect(screen.queryByTestId('sub-tab-nav')).not.toBeInTheDocument()
  })

  it('switches to maintenance tab on click', async () => {
    renderVehicleDetail()

    await waitFor(() => {
      expect(screen.getByText('Test Car')).toBeInTheDocument()
    })

    // Click the Maintenance primary tab
    fireEvent.click(screen.getByText('Maintenance'))

    // SubTabNav should appear with Service as default sub-tab
    await waitFor(() => {
      expect(screen.getByTestId('sub-tab-nav')).toBeInTheDocument()
      expect(screen.getByRole('tab', { name: /service/i })).toHaveAttribute('aria-selected', 'true')
    })
  })

  it('navigates to correct sub-tab from URL param', async () => {
    renderVehicleDetail('/vehicles/TEST12345678901234?tab=insurance')

    await waitFor(() => {
      expect(screen.getByText('Test Car')).toBeInTheDocument()
    })

    // insurance maps to { primary: 'financial', sub: 'insurance' }
    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /insurance/i })).toHaveAttribute('aria-selected', 'true')
    })
  })

  // --- LiveLink Tab Visibility ---

  it('shows LiveLink tab when device is linked', async () => {
    mockedLivelinkService.hasLinkedDevice.mockResolvedValue(true)

    renderVehicleDetail()

    await waitFor(() => {
      expect(screen.getByText('Test Car')).toBeInTheDocument()
    })

    await waitFor(() => {
      expect(screen.getByText('LiveLink')).toBeInTheDocument()
    })
  })

  it('hides LiveLink tab when no device is linked', async () => {
    mockedLivelinkService.hasLinkedDevice.mockResolvedValue(false)

    renderVehicleDetail()

    await waitFor(() => {
      expect(screen.getByText('Test Car')).toBeInTheDocument()
    })

    expect(screen.queryByText('LiveLink')).not.toBeInTheDocument()
  })

  // --- Admin Features ---

  it('shows Transfer button only for admin users', async () => {
    mockedUseAuth.mockReturnValue({
      user: { id: 1, username: 'admin', email: 'admin@test.com', is_admin: true },
      token: null,
      isAuthenticated: true,
      isAdmin: true,
      loading: false,
      authMode: 'local',
      login: vi.fn(),
      register: vi.fn(),
      logout: vi.fn(),
      refreshUser: vi.fn(),
      setAuthToken: vi.fn(),
    })

    renderVehicleDetail()

    await waitFor(() => {
      expect(screen.getByText('Test Car')).toBeInTheDocument()
    })

    expect(screen.getByTitle('Transfer vehicle ownership')).toBeInTheDocument()
  })
})
