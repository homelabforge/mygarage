import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ComponentProps } from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { FUEL_TYPE_VALUES } from '../../../constants/fuel'
import type { Vehicle, VehicleDetailStats } from '../../../types/vehicle'

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(),
    put: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

// Requires AuthProvider otherwise — same mock pattern as ServiceVisitForm.test.tsx
const unitPrefMock = vi.hoisted(() => ({
  system: 'metric' as 'metric' | 'imperial',
  showBoth: false,
  // Set to pin an exact resolved set (a `gal_uk` user, say); left null the set
  // follows `system`, the way the real hook derives both on one rung.
  units: null as null | import('@/types/units').UnitSet,
}))
vi.mock('../../../hooks/useUnitPreference', async () => {
  const { IMPERIAL_UNITS, METRIC_UNITS } = await import('@/__tests__/factories')
  return {
    useUnitPreference: () => ({
      system: unitPrefMock.system,
      showBoth: unitPrefMock.showBoth,
      units:
        unitPrefMock.units ??
        (unitPrefMock.system === 'imperial' ? IMPERIAL_UNITS : METRIC_UNITS),
    }),
  }
})

import { IMPERIAL_UNITS, UK_IMPERIAL_UNITS } from '../../../__tests__/factories'
import { binarySystemFor } from '../../../types/units'
import { UnitConverter } from '../../../utils/units'
import { toast } from 'sonner'
import api from '../../../services/api'
import VehicleEditDrawer from '../VehicleEditDrawer'

const mockedApi = vi.mocked(api)

const baseVehicle: Vehicle = {
  vin: 'TEST12345678901234',
  nickname: 'Test Car',
  vehicle_type: 'Car',
  usage_unit: 'distance',
  secondary_usage_enabled: false,
  year: 2024,
  make: 'Toyota',
  model: 'Camry',
  created_at: '2024-01-15T00:00:00Z',
  archived_visible: true,
  fuel_type: 'diesel',
  location_tracking_enabled: true,
}

const baseDetailStats: VehicleDetailStats = {
  average_cost_per_hr: null,
  average_l_per_hr: null,
  current_hours: null,
  last_fillup_date: null,
  last_service_date: null,
  latest_hours: null,
  latest_odometer_date: null,
  latest_odometer_km: null,
  overdue_count: 0,
  secondary_usage_enabled: false,
  spent_this_year: '0',
  upcoming_count: 0,
  usage_unit: 'distance',
  year: 2024,
}

type DrawerProps = ComponentProps<typeof VehicleEditDrawer>
/** The three launcher callbacks — required props almost no test cares about. */
type LauncherProps = 'onDownloadWindowSticker' | 'onUploadWindowSticker' | 'onManageTorqueSources'

/**
 * Every render site goes through this. Two reasons it exists rather than each
 * test constructing the element inline: the window-sticker section renders a
 * react-router <Link>, so a bare render() throws "useHref() may be used only in
 * the context of a <Router>"; and the launcher callbacks are required props
 * that almost no test cares about. All are defaulted here and overridable.
 */
function drawerEl(
  props: Omit<DrawerProps, LauncherProps> & Partial<Pick<DrawerProps, LauncherProps>>,
) {
  return (
    <MemoryRouter>
      <VehicleEditDrawer
        onDownloadWindowSticker={vi.fn()}
        onUploadWindowSticker={vi.fn()}
        onManageTorqueSources={vi.fn()}
        {...props}
      />
    </MemoryRouter>
  )
}

// The drawer seeds from a fresh GET /vehicles/{vin} (not the possibly-stale
// `vehicle` prop — see the lost-update fix) in parallel with detail-stats, so
// the api mock discriminates by URL: detail-stats gets `detailStats`,
// everything else (the vehicle refetch) gets `vehicle`. vehicleService.update()
// wraps api.put and returns response.data, so every existing `mockedApi.put`
// payload assertion still applies unchanged.
function renderVehicleEdit(vehicle: Vehicle, detailStats: VehicleDetailStats = baseDetailStats): {
  onClose: ReturnType<typeof vi.fn>
  onUpdated: ReturnType<typeof vi.fn>
} {
  mockedApi.get.mockImplementation((url: string) => {
    if (url.includes('detail-stats')) return Promise.resolve({ data: detailStats })
    return Promise.resolve({ data: vehicle })
  })
  const onClose = vi.fn()
  const onUpdated = vi.fn()
  render(drawerEl({ open: true, vin: vehicle.vin, vehicle, onClose, onUpdated }))
  return { onClose, onUpdated }
}

function renderVehicleEditWithStats(vehicle: Vehicle, detailStats: VehicleDetailStats): void {
  renderVehicleEdit(vehicle, detailStats)
}

describe('VehicleEditDrawer — canonical fuel-type select', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders a select with the empty option plus all 10 canonical fuel types (motorized)', async () => {
    renderVehicleEdit(baseVehicle)

    const select = (await screen.findByLabelText('edit.fuelType')) as HTMLSelectElement
    const options = Array.from(select.options)

    expect(options).toHaveLength(FUEL_TYPE_VALUES.length + 1)
    expect(options[0].value).toBe('')

    FUEL_TYPE_VALUES.forEach((value, index) => {
      const option = options[index + 1]
      expect(option.value).toBe(value)
      // The option label is rendered via t(`forms:fuel.fuelTypes.${value}`);
      // under the vitest i18n mock (t: key => key) that resolves to the key.
      expect(option.textContent).toBe(`forms:fuel.fuelTypes.${value}`)
    })

    expect(select.value).toBe('diesel')
  })

  it('keeps working for the non-motorized (fifth wheel) propane path', async () => {
    renderVehicleEdit({
      ...baseVehicle,
      vehicle_type: 'FifthWheel',
      fuel_type: 'propane_lpg',
    })

    const select = (await screen.findByLabelText('edit.fuelType')) as HTMLSelectElement
    expect(select.value).toBe('propane_lpg')

    const options = Array.from(select.options).map((o) => o.value)
    expect(options).toContain('propane_lpg')
    expect(options).toHaveLength(FUEL_TYPE_VALUES.length + 1)
  })

  it('submits fuel_type as null (not omitted) when the empty option is selected', async () => {
    renderVehicleEdit(baseVehicle)

    const select = (await screen.findByLabelText('edit.fuelType')) as HTMLSelectElement
    fireEvent.change(select, { target: { value: '' } })

    const saveButton = screen.getByRole('button', { name: 'edit.saveChanges' })
    fireEvent.click(saveButton)

    await waitFor(() => expect(mockedApi.put).toHaveBeenCalled())

    const [, payload] = mockedApi.put.mock.calls[0]
    // `null` here (not `undefined`) matters: JSON.stringify drops
    // `undefined` properties, which would silently no-op against the
    // backend's `exclude_unset=True` partial-update logic. toMatchObject
    // distinguishes `null` from a missing/`undefined` key.
    expect(payload).toMatchObject({ fuel_type: null })
  })

  it('leaves an untouched fuel_type value unchanged on submit', async () => {
    renderVehicleEdit(baseVehicle)

    await screen.findByLabelText('edit.fuelType')

    const saveButton = screen.getByRole('button', { name: 'edit.saveChanges' })
    fireEvent.click(saveButton)

    await waitFor(() => expect(mockedApi.put).toHaveBeenCalled())

    const [, payload] = mockedApi.put.mock.calls[0]
    expect(payload).toMatchObject({ fuel_type: 'diesel' })
  })
})

describe('VehicleEditDrawer — clear-on-blank vs. NOT NULL required fields', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('blocks submit with a field error (no PUT) when nickname is cleared — NOT NULL column', async () => {
    renderVehicleEdit(baseVehicle)

    const nicknameInput = (await screen.findByLabelText(
      'edit.nickname *',
    )) as HTMLInputElement
    fireEvent.change(nicknameInput, { target: { value: '' } })

    const saveButton = screen.getByRole('button', { name: 'edit.saveChanges' })
    fireEvent.click(saveButton)

    // Client-side validation must reject the blank nickname: submitting
    // `nickname: null` would violate the NOT NULL DB column, 409, and roll
    // back the entire update (losing every other edited field).
    expect(await screen.findByText('Nickname is required')).toBeInTheDocument()
    expect(mockedApi.put).not.toHaveBeenCalled()
  })

  it('offers no blank vehicle_type option (NOT NULL column, matches the wizard)', async () => {
    renderVehicleEdit(baseVehicle)

    const select = (await screen.findByLabelText('edit.vehicleType')) as HTMLSelectElement
    const values = Array.from(select.options).map((o) => o.value)

    expect(values).not.toContain('')
    expect(select.value).toBe('Car')
  })

})

describe('VehicleEditDrawer — DEF tank capacity diesel-only gate', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  const dieselWithCapacity: Vehicle = {
    ...baseVehicle,
    fuel_type: 'diesel',
    def_tank_capacity_liters: '19.0',
  }

  it('keeps the DEF capacity input enabled while diesel stays selected', async () => {
    renderVehicleEdit(dieselWithCapacity)

    const capacityInput = (await screen.findByLabelText('edit.defTankCapacity (L)')) as HTMLInputElement
    expect(capacityInput).not.toBeDisabled()
    expect(screen.getByText('edit.defTankCapacityHint')).toBeInTheDocument()
    expect(screen.queryByText('edit.defCapacityRequiresDieselHint')).not.toBeInTheDocument()
    expect(screen.queryByText('edit.clearDefTankCapacity')).not.toBeInTheDocument()
  })

  it('disables the DEF capacity input and surfaces the clear-first hint when switching away from diesel', async () => {
    renderVehicleEdit(dieselWithCapacity)

    const select = (await screen.findByLabelText('edit.fuelType')) as HTMLSelectElement
    fireEvent.change(select, { target: { value: 'gasoline' } })

    const capacityInput = (await screen.findByLabelText('edit.defTankCapacity (L)')) as HTMLInputElement
    expect(capacityInput).toBeDisabled()
    expect(screen.getByText('edit.defCapacityRequiresDieselHint')).toBeInTheDocument()
    expect(screen.getByText('edit.clearDefTankCapacity')).toBeInTheDocument()
  })

  it('clearing the capacity after switching away from diesel hides the field and submits null', async () => {
    renderVehicleEdit(dieselWithCapacity)

    const select = (await screen.findByLabelText('edit.fuelType')) as HTMLSelectElement
    fireEvent.change(select, { target: { value: 'gasoline' } })

    const clearButton = await screen.findByText('edit.clearDefTankCapacity')
    fireEvent.click(clearButton)

    // The whole capacity block hides once DEF tracking is unchecked.
    expect(screen.queryByLabelText('edit.defTankCapacity (L)')).not.toBeInTheDocument()

    const saveButton = screen.getByRole('button', { name: 'edit.saveChanges' })
    fireEvent.click(saveButton)

    await waitFor(() => expect(mockedApi.put).toHaveBeenCalled())

    const [, payload] = mockedApi.put.mock.calls[0]
    expect(payload).toMatchObject({ fuel_type: 'gasoline', def_tank_capacity_liters: null })
  })
})

describe('VehicleEditDrawer — dual usage tracking (hours + distance)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the Current Hours field when the primary usage unit is hours', async () => {
    renderVehicleEditWithStats(
      { ...baseVehicle, usage_unit: 'hours' },
      baseDetailStats,
    )

    expect(await screen.findByLabelText('edit.currentHours')).toBeInTheDocument()
  })

  it('shows the Current Hours field when primary is distance but secondary (hours) tracking is enabled', async () => {
    renderVehicleEditWithStats(
      { ...baseVehicle, usage_unit: 'distance' },
      { ...baseDetailStats, secondary_usage_enabled: true },
    )

    expect(await screen.findByLabelText('edit.currentHours')).toBeInTheDocument()
  })

  it('hides the Current Hours field for a distance-only vehicle (no secondary tracking)', async () => {
    renderVehicleEditWithStats(
      { ...baseVehicle, usage_unit: 'distance' },
      { ...baseDetailStats, secondary_usage_enabled: false },
    )

    // Wait for the form to finish loading before asserting absence.
    await screen.findByLabelText('edit.nickname *')
    expect(screen.queryByLabelText('edit.currentHours')).not.toBeInTheDocument()
  })

  it('labels the also-track toggle as "also track hours" for a distance-primary vehicle', async () => {
    renderVehicleEditWithStats(
      { ...baseVehicle, usage_unit: 'distance' },
      baseDetailStats,
    )

    expect(await screen.findByLabelText('edit.alsoTrackHours')).toBeInTheDocument()
    expect(screen.queryByLabelText('edit.alsoTrackDistance')).not.toBeInTheDocument()
  })

  it('labels the also-track toggle as "also track distance/odometer" for an hours-primary vehicle', async () => {
    renderVehicleEditWithStats(
      { ...baseVehicle, usage_unit: 'hours' },
      baseDetailStats,
    )

    expect(await screen.findByLabelText('edit.alsoTrackDistance')).toBeInTheDocument()
    expect(screen.queryByLabelText('edit.alsoTrackHours')).not.toBeInTheDocument()
  })

  it('toggling the also-track checkbox for a distance-primary vehicle reveals the Current Hours field', async () => {
    renderVehicleEditWithStats(
      { ...baseVehicle, usage_unit: 'distance' },
      { ...baseDetailStats, secondary_usage_enabled: false },
    )

    const toggle = (await screen.findByLabelText('edit.alsoTrackHours')) as HTMLInputElement
    expect(screen.queryByLabelText('edit.currentHours')).not.toBeInTheDocument()

    fireEvent.click(toggle)

    expect(await screen.findByLabelText('edit.currentHours')).toBeInTheDocument()
  })

  it('submits secondary_usage_enabled and current_hours in the payload', async () => {
    renderVehicleEditWithStats(
      { ...baseVehicle, usage_unit: 'hours' },
      { ...baseDetailStats, usage_unit: 'hours', latest_hours: '42.5' },
    )

    const hoursInput = (await screen.findByLabelText('edit.currentHours')) as HTMLInputElement
    fireEvent.change(hoursInput, { target: { value: '55.5' } })

    const saveButton = screen.getByRole('button', { name: 'edit.saveChanges' })
    fireEvent.click(saveButton)

    await waitFor(() => expect(mockedApi.put).toHaveBeenCalled())

    const [, payload] = mockedApi.put.mock.calls[0]
    expect(payload).toMatchObject({ secondary_usage_enabled: false, current_hours: 55.5 })
  })

  it('prefills Current Hours from detail-stats latest_hours, not the stale vehicle.current_hours column', async () => {
    renderVehicleEditWithStats(
      { ...baseVehicle, usage_unit: 'hours', current_hours: '999.9' },
      { ...baseDetailStats, usage_unit: 'hours', latest_hours: '42.5' },
    )

    const hoursInput = (await screen.findByLabelText('edit.currentHours')) as HTMLInputElement
    expect(hoursInput.value).toBe('42.5')
  })

  it('leaves Current Hours empty when detail-stats has no latest_hours reading yet', async () => {
    renderVehicleEditWithStats(
      { ...baseVehicle, usage_unit: 'hours', current_hours: '999.9' },
      { ...baseDetailStats, usage_unit: 'hours', latest_hours: null },
    )

    const hoursInput = (await screen.findByLabelText('edit.currentHours')) as HTMLInputElement
    expect(hoursInput.value).toBe('')
  })
})

describe('VehicleEditDrawer — seeds from a fresh fetch, not the stale prop', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('seeds from a fresh GET, not the possibly-stale vehicle prop', async () => {
    // The prop is what a long-open (or offline-cached) VehicleDetail would hold;
    // the server has newer truth. The editor must show the server's value.
    const stale = { ...baseVehicle, nickname: 'Stale Name' }
    const fresh = { ...baseVehicle, nickname: 'Fresh Name' }
    mockedApi.get.mockImplementation((url: string) => {
      if (url.includes('detail-stats')) return Promise.resolve({ data: baseDetailStats })
      return Promise.resolve({ data: fresh })
    })
    render(
      drawerEl({ open: true, vin: stale.vin, vehicle: stale, onClose: vi.fn(), onUpdated: vi.fn() }),
    )
    const nickname = (await screen.findByLabelText('edit.nickname *')) as HTMLInputElement
    await waitFor(() => expect(nickname.value).toBe('Fresh Name'))
  })

  it('does not render the DEF section when the fresh vehicle is non-motorized with no stored capacity', async () => {
    // The prop is a stale/offline-cached snapshot saying "Car"; the server
    // says Trailer, with no DEF capacity on record. The gate reads
    // `seedSource` (the fresh source) via `isMotorized`, not the stale
    // `vehicle` prop — gating on the stale prop would mount and register a
    // field the fresh data never populated, which is how a mounted-but-
    // unseeded field submits an explicit null.
    const staleProp = { ...baseVehicle, vehicle_type: 'Car', def_tank_capacity_liters: null }
    const freshNonMotorized = { ...baseVehicle, vehicle_type: 'Trailer', def_tank_capacity_liters: null }
    mockedApi.get.mockImplementation((url: string) => {
      if (url.includes('detail-stats')) return Promise.resolve({ data: baseDetailStats })
      return Promise.resolve({ data: freshNonMotorized })
    })
    render(
      drawerEl({ open: true, vin: staleProp.vin, vehicle: staleProp as Vehicle, onClose: vi.fn(), onUpdated: vi.fn() }),
    )
    await screen.findByLabelText('edit.nickname *')
    expect(screen.queryByLabelText('edit.enableDefTracking')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'edit.saveChanges' }))
    await waitFor(() => expect(mockedApi.put).toHaveBeenCalled())
    const [, payload] = mockedApi.put.mock.calls[0] as [string, Record<string, unknown>]
    expect(payload.def_tank_capacity_liters).toBe(null)
  })

  // D6 (final-review fix wave): a non-motorized vehicle that already carries
  // stored DEF capacity is a nonsense data state, but a real one — and the
  // backend 400s if fuel_type moves away from diesel while capacity > 0.
  // Gating the whole section on `isMotorized` alone stranded that vehicle
  // with no UI path to the Clear button (which lives inside the same gate),
  // so the gate widened to `(isMotorized || defEnabled)` — `defEnabled`
  // seeds `true` whenever stored capacity is present, motorized or not.
  it('renders the DEF section — and its Clear escape hatch — for a non-motorized vehicle that already carries stored capacity', async () => {
    const nonMotorizedWithCapacity: Vehicle = {
      ...baseVehicle,
      vehicle_type: 'Trailer',
      fuel_type: 'diesel',
      def_tank_capacity_liters: '19.0',
    }
    renderVehicleEdit(nonMotorizedWithCapacity)

    expect(await screen.findByLabelText('edit.enableDefTracking')).toBeInTheDocument()
    expect(await screen.findByLabelText('edit.defTankCapacity (L)')).toBeInTheDocument()

    // Switch away from diesel — the Clear button must be reachable so the
    // vehicle isn't stranded on the backend's diesel-only capacity 400.
    const select = (await screen.findByLabelText('edit.fuelType')) as HTMLSelectElement
    fireEvent.change(select, { target: { value: 'gasoline' } })
    expect(await screen.findByText('edit.clearDefTankCapacity')).toBeInTheDocument()
  })
})

describe('VehicleEditDrawer — conversion behaviour', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedApi.put.mockResolvedValue({ data: {} })
  })

  it('closes and hands the saved vehicle to onUpdated instead of reloading the page', async () => {
    const saved = { ...baseVehicle, nickname: 'Renamed' }
    mockedApi.put.mockResolvedValue({ data: saved })
    const { onClose, onUpdated } = renderVehicleEdit(baseVehicle)

    await screen.findByLabelText('edit.nickname *')
    fireEvent.click(screen.getByRole('button', { name: 'edit.saveChanges' }))

    await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(saved))
    expect(onClose).toHaveBeenCalled()
  })

  it('reseeds from the vehicle on reopen, discarding an abandoned edit', async () => {
    // Discriminate by URL like renderVehicleEdit: the drawer's seed effect
    // fetches the vehicle fresh (see VehicleEditDrawer.tsx's seedForm) in
    // parallel with detail-stats — both hit the same mocked api.get, so a
    // single mockResolvedValue would feed the vehicle-shaped detail-stats
    // object into `source` and silently blank the nickname instead of
    // restoring 'Test Car'.
    mockedApi.get.mockImplementation((url: string) => {
      if (url.includes('detail-stats')) return Promise.resolve({ data: baseDetailStats })
      return Promise.resolve({ data: baseVehicle })
    })
    const { rerender } = render(
      drawerEl({ open: true, vin: baseVehicle.vin, vehicle: baseVehicle, onClose: vi.fn(), onUpdated: vi.fn() }),
    )

    const nickname = (await screen.findByLabelText('edit.nickname *')) as HTMLInputElement
    fireEvent.change(nickname, { target: { value: 'Abandoned' } })
    expect(nickname.value).toBe('Abandoned')

    // Close, then reopen — the same mount, exactly what VehicleDetail does.
    rerender(
      drawerEl({ open: false, vin: baseVehicle.vin, vehicle: baseVehicle, onClose: vi.fn(), onUpdated: vi.fn() }),
    )
    rerender(
      drawerEl({ open: true, vin: baseVehicle.vin, vehicle: baseVehicle, onClose: vi.fn(), onUpdated: vi.fn() }),
    )

    await waitFor(() => {
      const reopened = screen.getByLabelText('edit.nickname *') as HTMLInputElement
      expect(reopened.value).toBe('Test Car')
    })
  })

  // Why this discriminates: Drawer.tsx:260 unmounts its CHILDREN on close, but
  // VehicleEditDrawer itself stays mounted (VehicleDetail renders it
  // unconditionally with an `open` prop), so react-hook-form's store survives —
  // shouldUnregister defaults to false. Without the [open]-keyed seed effect the
  // abandoned value is still in the store and comes straight back on reopen.

  it('renders no colour input and never sends a color key — the card owns exterior_color', async () => {
    renderVehicleEdit({ ...baseVehicle, color: 'Black' })

    await screen.findByLabelText('edit.nickname *')
    expect(screen.queryByLabelText('edit.color')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'edit.saveChanges' }))
    await waitFor(() => expect(mockedApi.put).toHaveBeenCalled())

    const [, payload] = mockedApi.put.mock.calls[0]
    // Not `toMatchObject({color: undefined})` — that passes on a present
    // `color: undefined`. The key must be absent so JSON.stringify drops it
    // and the backend's exclude_unset leaves the column alone.
    expect(Object.prototype.hasOwnProperty.call(payload, 'color')).toBe(false)
  })

  it('toasts and stays open when the save fails', async () => {
    // A plain Error (network drop, 500, etc.) carries no field-level detail —
    // applyServerErrors returns both `attached` and `unhandled` empty, so the
    // toast fallback must fire on `attached.length === 0`, not on
    // `unhandled.length > 0` alone (that stays empty here too and would
    // silently drop the failure).
    mockedApi.put.mockRejectedValue(new Error('Boom'))
    const { onClose, onUpdated } = renderVehicleEdit(baseVehicle)

    await screen.findByLabelText('edit.nickname *')
    fireEvent.click(screen.getByRole('button', { name: 'edit.saveChanges' }))

    // i18next isn't initialized in this test environment (only the
    // react-i18next hook is mocked), so getActionErrorMessage's generic
    // fallback resolves to i18next's unresolved defaultValue template rather
    // than an interpolated string. This still proves the toast fired via the
    // generic-failure branch, which is what this test is verifying.
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith('Failed to {{action}}. {{message}}')
    )
    expect(onUpdated).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('submits exactly the settings fields and nothing the drawer no longer owns', async () => {
    renderVehicleEdit(baseVehicle)
    await screen.findByLabelText('edit.nickname *')
    fireEvent.click(screen.getByRole('button', { name: 'edit.saveChanges' }))
    await waitFor(() => expect(mockedApi.put).toHaveBeenCalled())
    const [, payload] = mockedApi.put.mock.calls[0] as [string, Record<string, unknown>]
    // Pins the KEY SET, not values. Every other assertion here is toMatchObject
    // or single-key, which is how `purchase_price: null` on every save survived
    // a fully green suite. Any field this drawer starts or stops sending fails
    // here, loudly.
    expect(Object.keys(payload).sort()).toEqual([
      'current_hours',
      'def_tank_capacity_liters',
      'fuel_type',
      'nickname',
      'secondary_usage_enabled',
      'usage_unit',
      'vehicle_type',
    ])
  })
})

describe('VehicleEditDrawer — window sticker section', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  const withSticker = {
    ...baseVehicle,
    window_sticker_file_path: '/data/stickers/TEST12345678901234.pdf',
    window_sticker_parser_used: 'tesseract',
    window_sticker_confidence_score: 91.4,
    window_sticker_extracted_vin: baseVehicle.vin,
  } as unknown as Vehicle

  it('renders the upload prompt for a sticker-bearing type with no file on record', async () => {
    renderVehicleEdit(baseVehicle)
    await screen.findByLabelText('edit.nickname *')

    expect(screen.getByRole('heading', { name: 'detail.windowSticker' })).toBeInTheDocument()
    expect(screen.getByText('detail.noWindowSticker')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'detail.uploadWindowSticker' })).toBeInTheDocument()
    expect(screen.queryByText('detail.viewWindowSticker')).not.toBeInTheDocument()
  })

  it('renders the view tile, OCR metadata and replace action when a sticker exists', async () => {
    renderVehicleEdit(withSticker)
    await screen.findByLabelText('edit.nickname *')

    expect(screen.getByText('detail.viewWindowSticker')).toBeInTheDocument()
    expect(screen.getByText('detail.clickToOpenPDF')).toBeInTheDocument()
    expect(screen.getByText('detail.misc.parser')).toBeInTheDocument()
    expect(screen.getByText('detail.misc.confidence')).toBeInTheDocument()
    // extracted VIN matches the vehicle's, so this is the verified variant.
    expect(screen.getByText('✓ detail.misc.vinVerified')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'detail.replaceSticker' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'detail.uploadWindowSticker' })).not.toBeInTheDocument()
  })

  it('flags a mismatch when the extracted VIN is not the vehicle VIN', async () => {
    renderVehicleEdit({ ...withSticker, window_sticker_extracted_vin: 'OTHER00000000000000' } as Vehicle)
    await screen.findByLabelText('edit.nickname *')

    expect(screen.getByText('⚠ detail.misc.vinMismatch')).toBeInTheDocument()
    expect(screen.queryByText('✓ detail.misc.vinVerified')).not.toBeInTheDocument()
  })

  it('hides the whole section for a type that has no Monroney label', async () => {
    renderVehicleEdit({ ...baseVehicle, vehicle_type: 'Trailer' } as Vehicle)
    await screen.findByLabelText('edit.nickname *')

    expect(screen.queryByRole('heading', { name: 'detail.windowSticker' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'detail.uploadWindowSticker' })).not.toBeInTheDocument()
  })

  it('gates the section on the FRESH vehicle type, not the possibly-stale prop', async () => {
    // Same stale-prop hazard the DEF section guards against: the prop is an
    // offline cache saying Car, the server says Trailer.
    const staleProp = { ...baseVehicle, vehicle_type: 'Car' } as Vehicle
    mockedApi.get.mockImplementation((url: string) => {
      if (url.includes('detail-stats')) return Promise.resolve({ data: baseDetailStats })
      return Promise.resolve({ data: { ...baseVehicle, vehicle_type: 'Trailer' } })
    })
    render(drawerEl({ open: true, vin: staleProp.vin, vehicle: staleProp, onClose: vi.fn(), onUpdated: vi.fn() }))
    await screen.findByLabelText('edit.nickname *')

    expect(screen.queryByRole('heading', { name: 'detail.windowSticker' })).not.toBeInTheDocument()
  })

  it('reads the sticker file/metadata from the PROP, so a fresh upload shows without reopening', async () => {
    // Deliberate asymmetry with the gate above: the parent refetches into the
    // `vehicle` prop when an upload succeeds, but `seedSource` is a one-shot
    // snapshot taken when the drawer opened. Reading display values from
    // seedSource would leave the section saying "no window sticker" directly
    // after a successful upload. Nothing here registers with the form, so the
    // stale-seed null-clearing hazard does not apply.
    mockedApi.get.mockImplementation((url: string) => {
      if (url.includes('detail-stats')) return Promise.resolve({ data: baseDetailStats })
      // The seed source has NO sticker; the prop does.
      return Promise.resolve({ data: baseVehicle })
    })
    render(drawerEl({ open: true, vin: withSticker.vin, vehicle: withSticker, onClose: vi.fn(), onUpdated: vi.fn() }))
    await screen.findByLabelText('edit.nickname *')

    expect(screen.getByText('detail.viewWindowSticker')).toBeInTheDocument()
  })

  it('wires the two actions to their callbacks without submitting the settings form', async () => {
    const onDownloadWindowSticker = vi.fn()
    const onUploadWindowSticker = vi.fn()
    mockedApi.get.mockImplementation((url: string) => {
      if (url.includes('detail-stats')) return Promise.resolve({ data: baseDetailStats })
      return Promise.resolve({ data: withSticker })
    })
    render(
      drawerEl({
        open: true,
        vin: withSticker.vin,
        vehicle: withSticker,
        onClose: vi.fn(),
        onUpdated: vi.fn(),
        onDownloadWindowSticker,
        onUploadWindowSticker,
      }),
    )
    await screen.findByLabelText('edit.nickname *')

    const view = screen.getByText('detail.viewWindowSticker').closest('button')!
    const replace = screen.getByRole('button', { name: 'detail.replaceSticker' })

    // Asserted on the attribute, not inferred from "no PUT happened": both
    // buttons live inside #vehicle-edit-form, so without an explicit
    // type="button" they are SUBMIT buttons and every click saves the vehicle.
    // A post-click `expect(put).not.toHaveBeenCalled()` cannot catch that —
    // react-hook-form validates asynchronously, so the PUT lands after the
    // assertion and the test passes either way (verified by sabotage).
    expect(view).toHaveAttribute('type', 'button')
    expect(replace).toHaveAttribute('type', 'button')

    fireEvent.click(view)
    expect(onDownloadWindowSticker).toHaveBeenCalledTimes(1)

    fireEvent.click(replace)
    expect(onUploadWindowSticker).toHaveBeenCalledTimes(1)

    // Belt-and-braces, now that it can actually observe a submit: flush the
    // async validation both clicks would have kicked off.
    await waitFor(() => expect(mockedApi.put).not.toHaveBeenCalled())
  })
})

describe('VehicleEditDrawer — connected devices (Torque sources)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the launcher and wires it without submitting the settings form', async () => {
    const onManageTorqueSources = vi.fn()
    mockedApi.get.mockImplementation((url: string) => {
      if (url.includes('detail-stats')) return Promise.resolve({ data: baseDetailStats })
      return Promise.resolve({ data: baseVehicle })
    })
    render(
      drawerEl({
        open: true,
        vin: baseVehicle.vin,
        vehicle: baseVehicle,
        onClose: vi.fn(),
        onUpdated: vi.fn(),
        onManageTorqueSources,
      }),
    )
    await screen.findByLabelText('edit.nickname *')

    expect(screen.getByRole('heading', { name: 'detail.connectedDevices' })).toBeInTheDocument()
    const launch = screen.getByRole('button', { name: 'forms:modal.torque.launchButton' })
    // Inside #vehicle-edit-form: a submit-typed button here would PUT the
    // vehicle on every click. The <Button> primitive defaults to "button" —
    // this pins that it stays that way.
    expect(launch).toHaveAttribute('type', 'button')

    fireEvent.click(launch)
    expect(onManageTorqueSources).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(mockedApi.put).not.toHaveBeenCalled())
  })

  it('stays visible for a non-motorized vehicle, so an existing source can still be revoked', async () => {
    // Deliberately ungated on vehicle type, matching the Overview card it
    // replaced. Sources are revoked through the same drawer they are created
    // in, so hiding the launcher would strand any source already registered
    // against a trailer — there would be no other way to reach it.
    renderVehicleEdit({ ...baseVehicle, vehicle_type: 'Trailer' } as Vehicle)
    await screen.findByLabelText('edit.nickname *')

    expect(screen.getByRole('heading', { name: 'detail.connectedDevices' })).toBeInTheDocument()
    // The type-gated neighbours are correctly absent on the same vehicle.
    expect(screen.queryByRole('heading', { name: 'detail.windowSticker' })).not.toBeInTheDocument()
  })

  it('changing vehicle_type does NOT rewrite an existing usage_unit (fails if the wizard onChange is copied here)', async () => {
    // A Boat tracked in hours, with hours history hanging off that column. The
    // owner opens the drawer to correct a mis-typed vehicle_type; the type
    // default for the new type must not silently flip the vehicle to distance
    // and hide its Hours tab.
    renderVehicleEditWithStats(
      { ...baseVehicle, vehicle_type: 'Boat', usage_unit: 'hours' },
      baseDetailStats,
    )

    await screen.findByLabelText('edit.nickname *')
    fireEvent.change(screen.getByLabelText('edit.vehicleType'), { target: { value: 'Car' } })
    fireEvent.submit(document.querySelector('form') as HTMLFormElement)

    await waitFor(() => expect(mockedApi.put).toHaveBeenCalled())
    const body = mockedApi.put.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(body.vehicle_type).toBe('Car')
    expect(body.usage_unit).toBe('hours')
  })
})

describe('VehicleEditDrawer — the DEF tank capacity is the eighth gallon write site', () => {
  // ★ Not in any revision of the phase plan and not in any of the four codex
  // rounds: `def_tank_capacity_liters` goes through the same
  // `toCanonicalLiters` boundary the fuel forms do, so a UK user entering a
  // capacity in gallons stored it with the US factor.
  const dieselWithCapacity: Vehicle = {
    ...baseVehicle,
    fuel_type: 'diesel',
    def_tank_capacity_liters: '19.0',
  }

  beforeEach(() => {
    vi.clearAllMocks()
    unitPrefMock.system = 'metric'
    unitPrefMock.units = null
    UnitConverter.setGallonStandard('us')
  })

  it('seeds and submits the capacity on the USER\'s gallon, on a US-default instance', async () => {
    UnitConverter.setGallonStandard('us')
    unitPrefMock.system = 'imperial'
    unitPrefMock.units = UK_IMPERIAL_UNITS

    renderVehicleEdit(dieselWithCapacity)

    // 19 L is 4.18 imperial gallons; it would read 5.02 on US ones.
    const capacity = (await screen.findByLabelText('edit.defTankCapacity (gal)')) as HTMLInputElement
    expect(capacity.value).toBe('4.18')

    fireEvent.click(screen.getByRole('button', { name: 'edit.saveChanges' }))
    await waitFor(() => expect(mockedApi.put).toHaveBeenCalled())
    const [, payload] = mockedApi.put.mock.calls[0] as [string, Record<string, unknown>]
    // ★ 19, not 19.003, and the difference is plan 3b task 7. This field had
    // the entry-grid shift the three fuel forms had: 19 L seeds a UK-gallon
    // box as 4.18, and 4.18 x 4.54609 = 19.0026562, which the wire precision
    // rounds to 19.003. Opening this drawer to change a nickname moved a
    // capacity nobody edited. It is now seeded WITH its canonical origin, so
    // an untouched field posts what it was seeded from.
    expect(payload.def_tank_capacity_liters).toBe(19)
    expect(payload.def_tank_capacity_liters).not.toBe(19.003)
    expect(UnitConverter.getGallonStandard()).toBe('us')
  })

  it('★ a TYPED capacity converts on the user\'s gallon, which the origin case cannot see', async () => {
    // ★ THE CONVERSION TEST THIS TASK RETIRED, PUT BACK. At `ee8ab69` the case
    // above asserted `19.003` (4.18 x 4.54609), and that assertion WAS the
    // conversion test: it was the only place `def_tank_capacity_liters`
    // arithmetic ran. Task 7's origin makes an untouched save short-circuit to
    // the stored 19, which is correct and is why that number had to change, but
    // nothing replaced what the short-circuit retired. The drawer has no CREATE
    // path, so every other write site's typed-value coverage has no analogue
    // here, and rerouting this field's read token from `u.volume` to `u.mass`
    // survived the entire suite.
    //
    // So this case TYPES a value. 5.00 imperial gallons x 4.54609 = 22.73045,
    // which the wire precision rounds to 22.730. Through `u.mass` it would be
    // 5 x 0.453592 = 2.268, and through the US gallon 18.927.
    UnitConverter.setGallonStandard('us')
    unitPrefMock.system = 'imperial'
    unitPrefMock.units = UK_IMPERIAL_UNITS

    renderVehicleEdit(dieselWithCapacity)
    const capacity = (await screen.findByLabelText('edit.defTankCapacity (gal)')) as HTMLInputElement
    expect(capacity.value).toBe('4.18')

    fireEvent.change(capacity, { target: { value: '5.00' } })
    fireEvent.click(screen.getByRole('button', { name: 'edit.saveChanges' }))
    await waitFor(() => expect(mockedApi.put).toHaveBeenCalled())
    const [, payload] = mockedApi.put.mock.calls[0] as [string, Record<string, unknown>]
    expect(payload.def_tank_capacity_liters).toBe(22.73)
    // The three answers a wrong token or a wrong gallon would give, named so
    // this cannot pass on a build where any of them is what runs.
    expect(payload.def_tank_capacity_liters).not.toBe(2.268)
    expect(payload.def_tank_capacity_liters).not.toBe(18.927)
    expect(payload.def_tank_capacity_liters).not.toBe(19)
    expect(UnitConverter.getGallonStandard()).toBe('us')
  })

  it('★ REOPENING on a vehicle whose capacity was cleared does not keep the last one\'s origin', async () => {
    // ★ The absent path. `seedForm` used to write the origin only where the
    // stored capacity was a real number, so both `undefined` returns left the
    // PREVIOUS open's origin in place, which is the exact state the ref's
    // docstring says it is re-seeded to avoid.
    //
    // Reachable, and driven here rather than argued: open on 19 L (origin
    // `{19, '4.18'}`), close, reopen on a vehicle whose capacity is now null,
    // then type `4.18`. With a stale origin the typed value matches the
    // remembered display and posts the remembered 19; with a reset one it
    // converts, 4.18 x 4.54609 = 19.0026562 -> 19.003.
    UnitConverter.setGallonStandard('us')
    unitPrefMock.system = 'imperial'
    unitPrefMock.units = UK_IMPERIAL_UNITS

    const cleared: Vehicle = { ...dieselWithCapacity, def_tank_capacity_liters: null }
    let served: Vehicle = dieselWithCapacity
    mockedApi.get.mockImplementation((url: string) =>
      url.includes('detail-stats')
        ? Promise.resolve({ data: baseDetailStats })
        : Promise.resolve({ data: served })
    )

    const view = render(
      drawerEl({ open: true, vin: dieselWithCapacity.vin, vehicle: dieselWithCapacity, onClose: vi.fn(), onUpdated: vi.fn() })
    )
    const first = (await screen.findByLabelText('edit.defTankCapacity (gal)')) as HTMLInputElement
    expect(first.value).toBe('4.18')

    // Close and reopen the SAME mounted drawer, which is what re-seeds it. A
    // fresh render would build a fresh ref and could not express the defect.
    served = cleared
    view.rerender(
      drawerEl({ open: false, vin: cleared.vin, vehicle: cleared, onClose: vi.fn(), onUpdated: vi.fn() })
    )
    view.rerender(
      drawerEl({ open: true, vin: cleared.vin, vehicle: cleared, onClose: vi.fn(), onUpdated: vi.fn() })
    )
    await waitFor(() =>
      expect(screen.queryByLabelText('edit.defTankCapacity (gal)')).toBeNull()
    )

    fireEvent.click(screen.getByLabelText('edit.enableDefTracking'))
    const reopened = (await screen.findByLabelText('edit.defTankCapacity (gal)')) as HTMLInputElement
    expect(reopened.value).toBe('')

    fireEvent.change(reopened, { target: { value: '4.18' } })
    fireEvent.click(screen.getByRole('button', { name: 'edit.saveChanges' }))
    await waitFor(() => expect(mockedApi.put).toHaveBeenCalled())
    const [, payload] = mockedApi.put.mock.calls.at(-1) as [string, Record<string, unknown>]
    expect(payload.def_tank_capacity_liters).toBe(19.003)
    expect(payload.def_tank_capacity_liters).not.toBe(19)
  })

  it('★ the capacity EXAMPLE names the reader\'s OWN gallon', async () => {
    // ★ FOUND BY MUTATION, not by reading. Pinning the example table to
    // `gal_us` killed NOTHING: this placeholder had no test, and it was a
    // `system === 'imperial'` ternary, so a UK account read a US-gallon example
    // for a unit 20 percent larger. One physical tank, three vocabularies:
    // 19 L is 5.0 US gallons and 4.2 imperial ones.
    UnitConverter.setGallonStandard('us')
    unitPrefMock.system = 'imperial'
    unitPrefMock.units = UK_IMPERIAL_UNITS

    renderVehicleEdit(dieselWithCapacity)
    const uk = (await screen.findByLabelText('edit.defTankCapacity (gal)')) as HTMLInputElement
    expect(uk.placeholder).toBe('4.2')
    // The collapsed answer agrees with the US one here, which is what made this
    // invisible: both gallons read 'imperial'.
    expect(binarySystemFor(UK_IMPERIAL_UNITS.volume)).toBe('imperial')
    expect(binarySystemFor(IMPERIAL_UNITS.volume)).toBe('imperial')
  })

  it('labels and converts in litres for a metric set, on a UK-default instance', async () => {
    UnitConverter.setGallonStandard('uk')
    unitPrefMock.system = 'metric'
    unitPrefMock.units = null

    renderVehicleEdit(dieselWithCapacity)

    const capacity = (await screen.findByLabelText('edit.defTankCapacity (L)')) as HTMLInputElement
    expect(capacity.value).toBe('19')

    fireEvent.click(screen.getByRole('button', { name: 'edit.saveChanges' }))
    await waitFor(() => expect(mockedApi.put).toHaveBeenCalled())
    const [, payload] = mockedApi.put.mock.calls[0] as [string, Record<string, unknown>]
    expect(payload.def_tank_capacity_liters).toBe(19)
  })
})
