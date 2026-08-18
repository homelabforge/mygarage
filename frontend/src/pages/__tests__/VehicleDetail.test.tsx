import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom'

// Mock all tab components to avoid deep dependency trees
vi.mock('../../components/tabs/ServiceTab', () => ({ default: () => <div>ServiceTab</div> }))
vi.mock('../../components/tabs/FuelTab', () => ({ default: () => <div>FuelTab</div> }))
vi.mock('../../components/tabs/OdometerTab', () => ({ default: () => <div>OdometerTab</div> }))
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
vi.mock('../../components/WindowStickerUpload', () => ({ default: () => <div>WindowStickerUpload</div> }))
vi.mock('../../components/modals/VehicleRemoveModal', () => ({ default: () => null }))
vi.mock('../../components/modals/VehicleTransferWizard', () => ({ default: () => null }))
vi.mock('../../components/modals/VehicleSharingModal', () => ({ default: () => null }))
vi.mock('../../components/TransferHistorySection', () => ({ default: () => <div>TransferHistory</div> }))
vi.mock('../../components/SubTabNav', () => ({
  // `visible` filtering matches the real Tabs component (ui/Tabs.tsx) so
  // gating tests (Task 16a: Hours vs Odometer) exercise the actual config,
  // not an unfiltered list.
  default: ({ tabs, activeTab, onTabChange }: { tabs: { id: string; label: string; visible?: boolean }[]; activeTab: string; onTabChange: (id: string) => void }) => (
    <div data-testid="sub-tab-nav">
      {tabs.filter((tab) => tab.visible !== false).map((tab: { id: string; label: string }) => (
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
    getDetailStats: vi.fn(),
    // TrailerTowPanel loads on mount. Without these the effect threw
    // "listTowedTrailers is not a function" as an unhandled rejection: every
    // test still passed, but vitest failed the run on 25 unhandled errors.
    list: vi.fn().mockResolvedValue({ vehicles: [] }),
    getTrailerDetails: vi.fn().mockResolvedValue({}),
    listTowedTrailers: vi.fn().mockResolvedValue([]),
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
vi.mock('../../hooks/useUnitPreference', () => ({
  useUnitPreference: () => ({ system: 'imperial' }),
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
import type { Vehicle, VehicleDetailStats, VehicleType } from '../../types/vehicle'
import { UnitFormatter } from '../../utils/units'
import VehicleDetail from '../VehicleDetail'

const mockedVehicleService = vi.mocked(vehicleService)
const mockedLivelinkService = vi.mocked(livelinkService)
const mockedUseAuth = vi.mocked(useAuth)

const mockVehicle: Vehicle = {
  vin: 'TEST12345678901234',
  nickname: 'Test Car',
  vehicle_type: 'Car' as VehicleType,
  usage_unit: 'distance',
  secondary_usage_enabled: false,
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

describe('VehicleDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    mockedVehicleService.get.mockResolvedValue(mockVehicle)
    mockedVehicleService.getDetailStats.mockRejectedValue(new Error('no stats'))
    mockedLivelinkService.hasLinkedDevice.mockResolvedValue(false)
  })

  // --- Loading & Error States ---

  it('shows loading spinner initially', () => {
    mockedVehicleService.get.mockReturnValue(new Promise(() => {}))

    renderVehicleDetail()

    expect(screen.getByRole('status', { name: 'detail.loading' })).toBeInTheDocument()
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
      expect(screen.getByText('Failed to {{action}}. {{message}}')).toBeInTheDocument()
    })
    expect(screen.getByText('detail.backToDashboard')).toBeInTheDocument()
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
      expect(screen.getByText('Failed to {{action}}. {{message}}')).toBeInTheDocument()
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

    // Click the Maintenance primary tab (first match — mobile grid renders before desktop bar)
    // With i18n mock, t() returns translation keys
    fireEvent.click(screen.getAllByText('detail.tabs.maintenance')[0])

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

  // --- Fuel Primary Tab (#116) ---

  it('shows Fuel as a primary tab defaulting to the Fuel sub-tab (diesel: strip shows Fuel + DEF, Fuel selected)', async () => {
    // The strip only renders with 2+ visible sub-tabs, so use a diesel vehicle
    // (adds DEF). The default selection is still Fuel, not DEF.
    mockedVehicleService.get.mockResolvedValue({ ...mockVehicle, fuel_type: 'diesel' })
    renderVehicleDetail()

    await waitFor(() => {
      expect(screen.getByText('Test Car')).toBeInTheDocument()
    })

    // Click the Fuel primary tab (mobile grid renders before desktop bar)
    fireEvent.click(screen.getAllByText('detail.tabs.fuel')[0])

    // Sub-tab nav appears with Fuel selected as the default sub-tab, DEF alongside
    await waitFor(() => {
      const subNav = screen.getByTestId('sub-tab-nav')
      expect(subNav).toBeInTheDocument()
      expect(within(subNav).getByRole('tab', { name: 'detail.tabs.fuel' })).toHaveAttribute(
        'aria-selected',
        'true',
      )
      expect(within(subNav).getByRole('tab', { name: 'DEF' })).toBeInTheDocument()
    })
  })

  it('activates the Fuel primary tab from ?tab=fuel deep-link', async () => {
    renderVehicleDetail('/vehicles/TEST12345678901234?tab=fuel')

    await waitFor(() => {
      expect(screen.getByText('Test Car')).toBeInTheDocument()
    })

    // fuel now maps to { primary: 'fuel', sub: 'fuel' } — the Fuel primary tab is selected
    await waitFor(() => {
      const fuelPrimary = screen.getAllByRole('tab', { name: 'detail.tabs.fuel' })
      expect(fuelPrimary.some((el) => el.getAttribute('aria-selected') === 'true')).toBe(true)
    })
  })

  it('suppresses the sub-tab strip when only one sub-tab is visible (gasoline Fuel group) — content still renders', async () => {
    // Default mockVehicle: motorized gasoline Car -> the Fuel group has only the
    // lone 'fuel' sub-tab visible (no DEF/Propane). A one-item strip would just
    // duplicate its parent tab, so it is hidden; the FuelTab content still shows.
    renderVehicleDetail()
    await waitFor(() => expect(screen.getByText('Test Car')).toBeInTheDocument())

    fireEvent.click(screen.getAllByText('detail.tabs.fuel')[0])

    expect(await screen.findByText('FuelTab')).toBeInTheDocument()
    expect(screen.queryByTestId('sub-tab-nav')).not.toBeInTheDocument()
  })

  it('no longer lists Fuel as a sub-tab under Maintenance', async () => {
    renderVehicleDetail()

    await waitFor(() => {
      expect(screen.getByText('Test Car')).toBeInTheDocument()
    })

    fireEvent.click(screen.getAllByText('detail.tabs.maintenance')[0])

    await waitFor(() => {
      expect(screen.getByTestId('sub-tab-nav')).toBeInTheDocument()
    })
    // Fuel moved to its own primary tab; Maintenance keeps Service/Odometer/Recalls.
    // Scoped to the sub-tab nav: the Fuel PRIMARY tab legitimately still exists.
    const subNav = screen.getByTestId('sub-tab-nav')
    expect(within(subNav).queryByRole('tab', { name: 'detail.tabs.fuel' })).not.toBeInTheDocument()
  })

  // --- Hours/Odometer Sub-tab Visibility (Task 16a) ---

  it('shows Odometer (not Hours) under Maintenance for a distance-tracking vehicle', async () => {
    // mockVehicle defaults to usage_unit: 'distance', secondary_usage_enabled: false.
    renderVehicleDetail()
    await waitFor(() => expect(screen.getByText('Test Car')).toBeInTheDocument())

    fireEvent.click(screen.getAllByText('detail.tabs.maintenance')[0])
    await waitFor(() => expect(screen.getByTestId('sub-tab-nav')).toBeInTheDocument())

    const subNav = screen.getByTestId('sub-tab-nav')
    expect(within(subNav).getByRole('tab', { name: 'detail.misc.odometer' })).toBeInTheDocument()
    expect(within(subNav).queryByRole('tab', { name: 'common:engineHours' })).not.toBeInTheDocument()
  })

  it('shows Hours (not Odometer) under Maintenance for an hours-tracking vehicle', async () => {
    mockedVehicleService.get.mockResolvedValue({
      ...mockVehicle, usage_unit: 'hours', secondary_usage_enabled: false,
    })
    renderVehicleDetail()
    await waitFor(() => expect(screen.getByText('Test Car')).toBeInTheDocument())

    fireEvent.click(screen.getAllByText('detail.tabs.maintenance')[0])
    await waitFor(() => expect(screen.getByTestId('sub-tab-nav')).toBeInTheDocument())

    const subNav = screen.getByTestId('sub-tab-nav')
    expect(within(subNav).getByRole('tab', { name: 'common:engineHours' })).toBeInTheDocument()
    expect(within(subNav).queryByRole('tab', { name: 'detail.misc.odometer' })).not.toBeInTheDocument()
  })

  it('shows BOTH Odometer and Hours under Maintenance for a dual-tracking vehicle', async () => {
    mockedVehicleService.get.mockResolvedValue({
      ...mockVehicle, usage_unit: 'distance', secondary_usage_enabled: true,
    })
    renderVehicleDetail()
    await waitFor(() => expect(screen.getByText('Test Car')).toBeInTheDocument())

    fireEvent.click(screen.getAllByText('detail.tabs.maintenance')[0])
    await waitFor(() => expect(screen.getByTestId('sub-tab-nav')).toBeInTheDocument())

    const subNav = screen.getByTestId('sub-tab-nav')
    expect(within(subNav).getByRole('tab', { name: 'detail.misc.odometer' })).toBeInTheDocument()
    expect(within(subNav).getByRole('tab', { name: 'common:engineHours' })).toBeInTheDocument()
  })

  it('mounts HoursTab when the Hours sub-tab is selected (reachability: HoursTab is imported and rendered from VehicleDetail)', async () => {
    mockedVehicleService.get.mockResolvedValue({
      ...mockVehicle, usage_unit: 'hours', secondary_usage_enabled: false,
    })
    renderVehicleDetail()
    await waitFor(() => expect(screen.getByText('Test Car')).toBeInTheDocument())

    fireEvent.click(screen.getAllByText('detail.tabs.maintenance')[0])
    const hoursTab = await screen.findByRole('tab', { name: 'common:engineHours' })
    fireEvent.click(hoursTab)

    expect(await screen.findByText('HoursTab')).toBeInTheDocument()
  })

  // --- LiveLink Tab Visibility ---

  it('shows LiveLink tab when device is linked', async () => {
    mockedLivelinkService.hasLinkedDevice.mockResolvedValue(true)

    renderVehicleDetail()

    await waitFor(() => {
      expect(screen.getByText('Test Car')).toBeInTheDocument()
    })

    await waitFor(() => {
      // Both mobile grid and desktop bar render the tab, so multiple matches are expected
      expect(screen.getAllByText('LiveLink').length).toBeGreaterThan(0)
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

    expect(screen.getByTitle('detail.misc.transferTooltip')).toBeInTheDocument()
  })

  // --- Detail-stats fetch (P5 Task 3) ---

  it('fetches detail-stats for the current vin', async () => {
    renderVehicleDetail()
    await waitFor(() => expect(screen.getByText('Test Car')).toBeInTheDocument())
    expect(mockedVehicleService.getDetailStats).toHaveBeenCalledWith('TEST12345678901234')
  })

  it('does not let a stale A response overwrite B after navigating A->B (B3)', async () => {
    // Distinguish A vs B by HERO-visible status only (both rendered in THIS task):
    // A is overdue, B is upcoming. Under the key-returning t() mock the badge text
    // is the i18n key, so A shows 'vehicleStats.overdue' and B shows
    // 'vehicleStats.upcoming' — no key-facts strip (Task 5), no unit/currency
    // formatting. A resolves LATE (deferred); B resolves immediately; B must win.
    let resolveA: (value: VehicleDetailStats) => void = () => {}
    const A_STATS: VehicleDetailStats = {
      overdue_count: 3, upcoming_count: 0,
      usage_unit: 'distance', current_hours: null,
      latest_hours: null, average_l_per_hr: null, average_cost_per_hr: null,
      secondary_usage_enabled: false,
      latest_odometer_km: null, latest_odometer_date: null,
      last_service_date: null, last_fillup_date: null,
      spent_this_year: '0.00', year: 2026,
    }
    const B_STATS: VehicleDetailStats = { ...A_STATS, overdue_count: 0, upcoming_count: 4 }
    mockedVehicleService.getDetailStats.mockImplementation((vin: string) =>
      vin === 'AAAAAAAAAAAAAAAAA'
        ? new Promise<VehicleDetailStats>((res) => { resolveA = res })
        : Promise.resolve(B_STATS),
    )
    render(
      <MemoryRouter initialEntries={['/vehicles/AAAAAAAAAAAAAAAAA']}>
        <Routes>
          <Route path="/vehicles/:vin" element={<VehicleDetail />} />
        </Routes>
        <Link to="/vehicles/BBBBBBBBBBBBBBBBB">go B</Link>
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText('Test Car')).toBeInTheDocument())
    // Navigate A -> B (same route element, useParams changes -> [vin] effect re-runs).
    fireEvent.click(screen.getByText('go B'))
    // B rendered: hero shows the UPCOMING badge (overdue 0), never overdue.
    await waitFor(() => expect(screen.getByText('vehicleStats.upcoming')).toBeInTheDocument())
    expect(screen.queryByText('vehicleStats.overdue')).not.toBeInTheDocument()
    // The stale A response now arrives; the cancelled guard must swallow it.
    resolveA(A_STATS)
    // Meaningful flush: awaiting waitFor yields to the microtask queue so A's
    // .then() runs (and no-ops under the guard). B's upcoming badge must still
    // stand and A's overdue badge must never appear. Without the guard, A would
    // overwrite B here -> the upcoming badge vanishes and this waitFor throws.
    await waitFor(() => expect(screen.getByText('vehicleStats.upcoming')).toBeInTheDocument())
    expect(screen.queryByText('vehicleStats.overdue')).not.toBeInTheDocument()
  })

  it('renders fetched nonzero stats end-to-end: hero badge + reading + key facts (B4)', async () => {
    // Successful NONZERO page integration: fetch -> page state -> props ->
    // mounted VehicleHero AND VehicleKeyFacts. A broken page mount, an omitted
    // detailStats prop, or a missing VehicleKeyFacts mount all fail here.
    mockedVehicleService.getDetailStats.mockResolvedValue({
      overdue_count: 3, upcoming_count: 2,
      usage_unit: 'distance', current_hours: null,
      latest_hours: null, average_l_per_hr: null, average_cost_per_hr: null,
      secondary_usage_enabled: false,
      latest_odometer_km: '160000.00', latest_odometer_date: '2026-07-01',
      last_service_date: '2026-06-15', last_fillup_date: '2026-07-10',
      spent_this_year: '1234.50', year: 2026,
    })
    renderVehicleDetail()
    await waitFor(() => expect(screen.getByText('Test Car')).toBeInTheDocument())

    // Hero: overdue badge (overdue 3 > 0) + the boundary-converted odometer
    // reading chip + the reading date. `Jul 1, 2026` is hero-only (the strip
    // renders Jun 15 / Jul 10).
    expect(await screen.findByText('vehicleStats.overdue')).toBeInTheDocument()
    expect(screen.getByText('detail.misc.odometer')).toBeInTheDocument()
    // R3-B2: assert the CONVERTED odometer VALUE, not just its label — computed
    // from the SAME UnitFormatter the hero uses, with the file-pinned imperial
    // system, so it renders in the hero's `<Mono>{reading}</Mono>` node. This fails
    // if the boundary conversion is removed or raw km leaks to the UI.
    const expectedOdometer = UnitFormatter.formatDistance(160000, 'imperial')
    expect(screen.getByText(expectedOdometer)).toBeInTheDocument()
    expect(screen.getByText(/Jul 1, 2026/)).toBeInTheDocument()

    // Key-facts strip mounted + label-bound (role="group" makes it swap-proof):
    const service = screen.getByRole('group', { name: 'vehicleStats.lastService' })
    expect(within(service).getByText(/Jun 15, 2026/)).toBeInTheDocument()
    const fillup = screen.getByRole('group', { name: 'vehicleStats.lastFillUp' })
    expect(within(fillup).getByText(/Jul 10, 2026/)).toBeInTheDocument()
    const spent = screen.getByRole('group', { name: 'detail.keyFacts.spent' })
    expect(within(spent).getByText(/1,234\.50/)).toBeInTheDocument()
    const upcoming = screen.getByRole('group', { name: 'detail.keyFacts.upcoming' })
    expect(within(upcoming).getByText('2')).toBeInTheDocument()  // upcoming_count, not overdue
  })

  // --- Actions row + equipment expand (P5 Task 4) ---

  it('Log Service switches to Maintenance/service (SDQ-1)', async () => {
    renderVehicleDetail()
    await waitFor(() => expect(screen.getByText('Test Car')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'detail.hero.logService' }))
    expect(await screen.findByText('ServiceTab')).toBeInTheDocument()
  })

  it('Add Fuel on a motorized car opens Fuel/fuel (SDQ-1)', async () => {
    renderVehicleDetail()
    await waitFor(() => expect(screen.getByText('Test Car')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'detail.hero.addFuel' }))
    expect(await screen.findByText('FuelTab')).toBeInTheDocument()
  })

  it('Add Fuel on a fifth-wheel with DEF+propane opens DEF, not Propane (B6)', async () => {
    // Non-motorized (FifthWheel) + diesel -> hasDEF && hasPropane. First visible
    // fuel sub-tab is DEF (config order Fuel->DEF->Propane). Buggy propane-first
    // ordering would render PropaneTab instead.
    mockedVehicleService.get.mockResolvedValue({
      ...mockVehicle, vehicle_type: 'FifthWheel', fuel_type: 'diesel',
    })
    renderVehicleDetail()
    await waitFor(() => expect(screen.getByText('Test Car')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'detail.hero.addFuel' }))
    expect(await screen.findByText('DEFTab')).toBeInTheDocument()
    expect(screen.queryByText('PropaneTab')).not.toBeInTheDocument()
  })

  it('Reminder switches the active primary tab to Tracking (SDQ-1)', async () => {
    renderVehicleDetail()
    await waitFor(() => expect(screen.getByText('Test Car')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'detail.hero.reminder' }))
    await waitFor(() =>
      expect(
        screen.getAllByRole('tab', { name: 'detail.tabs.tracking' })
          .some((el) => el.getAttribute('aria-selected') === 'true'),
      ).toBe(true),
    )
  })

  it('Standard/Optional open the equipment editor sidecar with the current items (SDQ-2)', async () => {
    mockedVehicleService.get.mockResolvedValue({
      ...mockVehicle,
      standard_equipment: { items: ['ABS', 'Airbags'] },
      optional_equipment: { items: ['Sunroof'] },
    })
    renderVehicleDetail()
    await waitFor(() => expect(screen.getByText('Test Car')).toBeInTheDocument())

    // The read-only dropdown is gone; the Standard pill opens the editor drawer
    // (labelled with the list) showing the current items + the edit subtitle.
    fireEvent.click(screen.getByRole('button', { name: 'detail.hero.standard' }))
    const standardDialog = await screen.findByRole('dialog', { name: 'detail.standardEquipment' })
    expect(within(standardDialog).getByText('detail.equipment.editSubtitle')).toBeInTheDocument()
    expect(within(standardDialog).getByText('ABS')).toBeInTheDocument()
    expect(within(standardDialog).getByText('Airbags')).toBeInTheDocument()

    // The Optional pill switches the same drawer to the optional list.
    fireEvent.click(screen.getByRole('button', { name: 'detail.hero.optional' }))
    const optionalDialog = await screen.findByRole('dialog', { name: 'detail.optionalEquipment' })
    expect(within(optionalDialog).getByText('Sunroof')).toBeInTheDocument()
    expect(within(optionalDialog).queryByText('ABS')).not.toBeInTheDocument()
  })

  it('with only optional equipment: Standard button hidden, Optional opens the editor (B7)', async () => {
    mockedVehicleService.get.mockResolvedValue({
      ...mockVehicle,
      standard_equipment: null,
      optional_equipment: { items: ['Sunroof'] },
    })
    renderVehicleDetail()
    await waitFor(() => expect(screen.getByText('Test Car')).toBeInTheDocument())
    // No standard list -> no Standard button; Optional present and functional.
    expect(screen.queryByRole('button', { name: 'detail.hero.standard' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'detail.hero.optional' }))
    const dialog = await screen.findByRole('dialog', { name: 'detail.optionalEquipment' })
    expect(within(dialog).getByText('Sunroof')).toBeInTheDocument()
  })
})
