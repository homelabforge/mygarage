import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent } from '../../../__tests__/test-utils'
import type { VehicleLiveLinkStatus } from '../../../types/livelink'

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => mockNavigate }
})
vi.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: null, isAuthenticated: false }),
}))

// A parked (not running) device is the minimal status that makes the widget
// render its role="button" region — the running-only metrics grid isn't
// needed to exercise the keydown handler. Defined via vi.hoisted since
// vi.mock factories are hoisted above regular top-level const declarations
// (VIN lives inside the same hoisted block so the literal isn't repeated).
const { VIN, STATUS } = vi.hoisted(() => {
  const VIN = '1HGBH41JXMN109186'
  return {
    VIN,
    STATUS: {
      device_id: 'wican-1',
      // A WiCAN declares DRIVE_SESSION, which is what makes Running/Parked
      // meaningful. A telemetry-only source reports reachability instead.
      capabilities: ['telemetry', 'drive_session', 'location', 'dtc', 'odometer'],
      device_status: 'online',
      online: true,
      ecu_status: 'offline',
      vin: VIN,
      latest_values: [],
    } satisfies VehicleLiveLinkStatus,
  }
})

const getVehicleStatus = vi.fn()
vi.mock('@/services/livelinkService', () => ({
  livelinkService: { getVehicleStatus: () => getVehicleStatus() },
}))

import VehicleLiveLinkWidget from '../VehicleLiveLinkWidget'

// A RUNNING device, which is the only state that renders the metrics grid. The
// three figures below are the widget's whole numeric surface and nothing used
// to cover them, so the grid's rendering was unkillable by any mutation.
const RUNNING = {
  ...STATUS,
  ecu_status: 'online',
  latest_values: [
    { param_key: 'SPEED', value: 100, unit: 'km/h', display_name: 'Speed', in_warning: false, show_on_dashboard: true, timestamp: 'x' },
    { param_key: 'ENGINE_RPM', value: 3200, unit: 'rpm', display_name: 'RPM', in_warning: false, show_on_dashboard: true, timestamp: 'x' },
    { param_key: 'COOLANT_TMP', value: 90, unit: 'C', display_name: 'Coolant', in_warning: false, show_on_dashboard: true, timestamp: 'x' },
  ],
} satisfies VehicleLiveLinkStatus

describe('VehicleLiveLinkWidget keyboard activation (I12 a11y fix)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getVehicleStatus.mockResolvedValue(STATUS)
  })

  it('activates navigation on Enter and Space, and does not bubble to a parent handler', async () => {
    // The region is a sibling control inside a stretched-link card (see
    // VehicleStatisticsCard) — a parent onKeyDown proxies the card's own
    // whole-card handler, so this proves stopPropagation actually holds.
    const parentKeyDown = vi.fn()
    render(
      <div onKeyDown={parentKeyDown}>
        <VehicleLiveLinkWidget vin={VIN} />
      </div>,
    )

    const region = await screen.findByRole('button', { name: 'livelink.widget.title' })

    fireEvent.keyDown(region, { key: 'Enter' })
    expect(mockNavigate).toHaveBeenCalledTimes(1)
    expect(mockNavigate).toHaveBeenCalledWith(`/vehicles/${VIN}?tab=live`)

    fireEvent.keyDown(region, { key: ' ' })
    expect(mockNavigate).toHaveBeenCalledTimes(2)
    expect(mockNavigate).toHaveBeenLastCalledWith(`/vehicles/${VIN}?tab=live`)

    expect(parentKeyDown).not.toHaveBeenCalled()
  })

  it('renders the running metrics through the shared adapter, not through its own arithmetic', async () => {
    getVehicleStatus.mockResolvedValue(RUNNING)
    render(<VehicleLiveLinkWidget vin={VIN} />)
    // No account and no stored choice, so `useUnitPreference` lands on the
    // imperial preset. 100 km/h / 1.609344 = 62.13..., at the mph adapter's 0 dp.
    expect(await screen.findByText('62')).toBeInTheDocument()
    expect(screen.getByText('MPH')).toBeInTheDocument()
    // 90 C x 9/5 + 32 = 194, at the f adapter's 1 dp. It read "194\u00b0F" before,
    // because the widget rounded the number itself.
    expect(screen.getByText('194.0\u00b0F')).toBeInTheDocument()
    // RPM is outside the unit system, so it is not CONVERTED, but it is still
    // grouped for the locale by the same helper every other figure uses. It
    // read "3200" here and "3,200" on the LiveLink gauge, from one reading.
    expect(screen.getByText('3,200')).toBeInTheDocument()
  })

  it('shows a source with no status as connected while the server says it reports', async () => {
    // A sensor that hasn't sent a reading since the upgrade still says
    // 'unknown'. Read raw, the widget said Offline while Settings said online.
    getVehicleStatus.mockResolvedValue({
      ...STATUS,
      capabilities: ['telemetry'],
      device_status: 'unknown',
      ecu_status: 'unknown',
      online: true,
    } satisfies VehicleLiveLinkStatus)
    render(<VehicleLiveLinkWidget vin={VIN} />)

    expect(await screen.findByText('vehicleLiveLinkWidget.statusConnected')).toBeInTheDocument()
    expect(screen.queryByText('vehicleLiveLinkWidget.statusOffline')).not.toBeInTheDocument()
  })

  it('shows offline when the server says so, whatever device_status says', async () => {
    getVehicleStatus.mockResolvedValue({ ...STATUS, online: false } satisfies VehicleLiveLinkStatus)
    render(<VehicleLiveLinkWidget vin={VIN} />)

    expect(await screen.findByText('vehicleLiveLinkWidget.statusOffline')).toBeInTheDocument()
  })

  it('ignores other keys', async () => {
    render(<VehicleLiveLinkWidget vin={VIN} />)
    const region = await screen.findByRole('button', { name: 'livelink.widget.title' })

    fireEvent.keyDown(region, { key: 'Tab' })
    expect(mockNavigate).not.toHaveBeenCalled()
  })
})

/**
 * Selecting a reading (issue #179). jsdom pins the handler only: the click
 * that ends a selection neither navigates nor reaches the card around the
 * widget. Whether the text is selectable on a phone is the E2E half.
 */
describe('VehicleLiveLinkWidget text selection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getVehicleStatus.mockResolvedValue(RUNNING)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('ending a selection on a reading does not navigate', async () => {
    // RED today: handleClick navigates on any click, including the one that
    // lets go of a selection. The parent spy stands in for the vehicle card:
    // the widget still stops the click, so a card handler can't navigate
    // instead (mutant: return before stopPropagation).
    const parentClick = vi.fn()
    render(
      <div onClick={parentClick}>
        <VehicleLiveLinkWidget vin={VIN} />
      </div>,
    )
    const reading = await screen.findByText('3,200')
    vi.spyOn(window, 'getSelection').mockReturnValue({
      isCollapsed: false,
      toString: () => '3,200',
    } as unknown as Selection)

    fireEvent.click(reading)
    expect(mockNavigate).not.toHaveBeenCalled()
    expect(parentClick).not.toHaveBeenCalled()

    // Selection gone, a plain click still opens the Live tab.
    vi.mocked(window.getSelection).mockRestore()
    fireEvent.click(reading)
    expect(mockNavigate).toHaveBeenCalledTimes(1)
    expect(mockNavigate).toHaveBeenCalledWith(`/vehicles/${VIN}?tab=live`)
    expect(parentClick).not.toHaveBeenCalled()
  })
})
