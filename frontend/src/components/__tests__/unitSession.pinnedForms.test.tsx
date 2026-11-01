/**
 * Every form that pins its units actually does (R4), one row per pin site.
 *
 * The REAL hooks run. `useUnitPreference` is wrapped only to log what each
 * call hands back, so the log is exactly the units the form labels and
 * converts with. Each row opens on US units, the store flips the account to
 * metric, and every call after the flip must still say gal_us/mi. Drop the
 * wrapper from any row and that row logs L/km.
 *
 * TireList and VehicleSpecsPanel hold a live card next to a pinned drawer, so
 * their rows want both: the drawer's pinned units and the card's live ones.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ReactElement } from 'react'
import { act, fireEvent, screen } from '@testing-library/react'
import { render } from '../../__tests__/test-utils'
import { IMPERIAL_UNITS, METRIC_UNITS } from '../../__tests__/factories'
import { setUnitPrefs } from '../../utils/unitPrefsStore'
import type { Reminder } from '../../types/reminder'
import type { Supply } from '../../types/supplies'
import type { BrakeOverview } from '../../types/brake'
import type { Vehicle } from '../../types/vehicle'

const seen = vi.hoisted(() => ({ log: [] as string[] }))

vi.mock('../../hooks/useUnitPreference', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../hooks/useUnitPreference')>()
  return {
    ...real,
    // Pass-through: the real answer, logged.
    useUnitPreference: () => {
      const pref = real.useUnitPreference()
      seen.log.push(`${pref.units.volume}/${pref.units.distance}`)
      return pref
    },
  }
})
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: null,
    isAuthenticated: false,
    isAdmin: false,
    defaultUnitPrefs: METRIC_UNITS,
    householdTimeZone: null,
  }),
}))
vi.mock('../../hooks/useTimeFormat', () => ({ useTimeFormat: () => ({ timeFormat: '24h' }) }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

// The tire list needs a loaded list to render its drawers; everything else
// can sit on a request that never answers.
vi.mock('../../services/api', () => ({
  default: {
    get: (url: string) =>
      url.endsWith('/tires')
        ? Promise.resolve({ data: { tires: [], tracks_distance: true, tracks_hours: false } })
        : url.endsWith('/tire-sets')
          ? Promise.resolve({ data: { sets: [] } })
          : new Promise(() => {}),
    post: () => new Promise(() => {}),
    put: () => new Promise(() => {}),
    patch: () => new Promise(() => {}),
    delete: () => new Promise(() => {}),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    defaults: { headers: { common: {} } },
  },
}))

import FuelRecordForm from '../FuelRecordForm'
import DEFRecordForm from '../DEFRecordForm'
import PropaneRecordForm from '../PropaneRecordForm'
import OdometerRecordForm from '../OdometerRecordForm'
import ServiceVisitForm from '../ServiceVisitForm'
import ReminderForm from '../ReminderForm'
import WarrantyForm from '../WarrantyForm'
import SupplyHistoryModal from '../SupplyHistoryModal'
import CompleteReminderDialog from '../CompleteReminderDialog'
import ApplyPackDialog from '../ApplyPackDialog'
import WindowStickerUpload from '../WindowStickerUpload'
import TireList from '../TireList'
import { JobEditor, MeasurementEditor } from '../brakes/BrakeEditors'
import BrakeJobDrawer from '../brakes/BrakeJobDrawer'
import LogBrakeMeasurementsDrawer from '../brakes/LogBrakeMeasurementsDrawer'
import AddPastPeriodDrawer from '../tires/AddPastPeriodDrawer'
import MountPeriodEditor from '../tires/MountPeriodEditor'
import ReadingEditor from '../tires/ReadingEditor'
import VehicleSpecsPanel from '../vehicle-detail/VehicleSpecsPanel'
import VehicleEditDrawer from '../vehicle-detail/VehicleEditDrawer'
import { SupplyForm } from '../../pages/Supplies'

const VIN = 'TEST12345678901234'
const noop = (): void => {}
const labelFor = (p: string | null | undefined): string => `pos-${p}`

const OVERVIEW: BrakeOverview = {
  usage_axis: 'distance',
  tracks_distance: true,
  tracks_hours: false,
  axles: [],
  corners: [],
}
const JOB = {
  id: 7,
  position: 'FL' as const,
  brake_type: 'disc' as const,
  performed_on: '2026-09-10',
  odometer_km: '47000.00',
  friction_replaced: true,
  surface: 'resurfaced' as const,
}
const PADS = {
  id: 11,
  position: 'FL' as const,
  recorded_at: '2026-09-10',
  odometer_km: '47000.00',
  inner_pad_mm: '10.00',
  outer_pad_mm: '10.00',
}
const TIRE = {
  id: 9,
  vin: VIN,
  position: 'FL',
  min_tread_mm: '1.60',
  created_at: '2026-01-01T00:00:00',
  mount_periods: [],
  readings: [],
}
const PERIOD = {
  id: 4,
  position: 'FL',
  mounted_on: '2026-01-10',
  dismounted_on: '2026-03-10',
  mounted_odometer_km: '10000.00',
  dismounted_odometer_km: '12000.00',
  is_assumed: false,
  observed_active_on: null,
  notes: null,
}
const READING = {
  id: 31,
  tire_id: 9,
  vin: VIN,
  position: 'FL',
  recorded_at: '2026-10-11',
  odometer_km: '12000.00',
  engine_hours: null,
  tread_depth_mm: '6.00',
  pressure_kpa: '240.00',
  notes: null,
  created_at: '2026-10-11T12:00:00',
}
const REMINDER = {
  id: 4,
  vin: VIN,
  title: 'Oil Change',
  reminder_type: 'smart',
  status: 'pending',
  due_date: '2026-12-13',
  due_mileage_km: '151064.24',
  due_hours: null,
  notes: null,
  created_at: '2026-06-14T00:00:00Z',
} as unknown as Reminder
// No stored volume unit, so the shown unit follows the account.
const SUPPLY = {
  id: 1,
  name: 'Motor Oil',
  unit_type: 'volume',
  on_hand: '3.500',
  is_active: true,
  created_at: '2026-01-01T00:00:00',
} as Supply
const VEHICLE = {
  vin: VIN,
  nickname: 'Test Car',
  vehicle_type: 'Car',
  usage_unit: 'distance',
  secondary_usage_enabled: false,
  created_at: '2024-01-15T00:00:00Z',
  archived_visible: true,
  fuel_type: 'gasoline',
  location_tracking_enabled: true,
  distance_unit: null,
} as Vehicle

const PINNED = 'gal_us/mi'
const LIVE = 'L/km'

interface Row {
  name: string
  ui: () => ReactElement
  /** Clicks that open the drawer, for a site whose drawer starts closed. */
  open?: () => Promise<void>
  /** A live card beside the pinned drawer: both answers must show after the flip. */
  live?: true
}

const ROWS: Row[] = [
  { name: 'FuelRecordForm', ui: () => <FuelRecordForm vin={VIN} onClose={noop} onSuccess={noop} /> },
  { name: 'DEFRecordForm', ui: () => <DEFRecordForm vin={VIN} onClose={noop} onSuccess={noop} /> },
  { name: 'PropaneRecordForm', ui: () => <PropaneRecordForm vin={VIN} onClose={noop} onSuccess={noop} /> },
  { name: 'OdometerRecordForm', ui: () => <OdometerRecordForm vin={VIN} onClose={noop} onSuccess={noop} /> },
  { name: 'ServiceVisitForm', ui: () => <ServiceVisitForm vin={VIN} onClose={noop} onSuccess={noop} /> },
  { name: 'ReminderForm', ui: () => <ReminderForm vin={VIN} onClose={noop} onSuccess={noop} /> },
  { name: 'WarrantyForm', ui: () => <WarrantyForm vin={VIN} onClose={noop} onSuccess={noop} /> },
  { name: 'SupplyHistoryModal', ui: () => <SupplyHistoryModal supply={SUPPLY} onClose={noop} initialForm="purchase" /> },
  { name: 'SupplyForm', ui: () => <SupplyForm onClose={noop} onSuccess={noop} /> },
  {
    name: 'MeasurementEditor',
    ui: () => (
      <MeasurementEditor vin={VIN} overview={OVERVIEW} measurement={PADS as never} brakeType="disc" open onClose={noop} />
    ),
  },
  { name: 'JobEditor', ui: () => <JobEditor vin={VIN} overview={OVERVIEW} job={JOB as never} open onClose={noop} /> },
  {
    name: 'BrakeJobDrawer',
    ui: () => <BrakeJobDrawer vin={VIN} overview={OVERVIEW} open onClose={noop} initialCorners={['FL']} />,
  },
  {
    name: 'LogBrakeMeasurementsDrawer',
    ui: () => <LogBrakeMeasurementsDrawer vin={VIN} overview={OVERVIEW} open onClose={noop} />,
  },
  {
    name: 'AddPastPeriodDrawer',
    ui: () => <AddPastPeriodDrawer vin={VIN} tire={TIRE as never} open onClose={noop} labelFor={labelFor} />,
  },
  {
    name: 'MountPeriodEditor',
    ui: () => (
      <MountPeriodEditor vin={VIN} tire={TIRE as never} period={PERIOD as never} open onClose={noop} labelFor={labelFor} />
    ),
  },
  {
    name: 'ReadingEditor',
    ui: () => (
      <ReadingEditor vin={VIN} tire={TIRE as never} reading={READING as never} open onClose={noop} labelFor={labelFor} />
    ),
  },
  {
    name: 'CompleteReminderDialog',
    ui: () => (
      <CompleteReminderDialog
        vin={VIN}
        reminder={REMINDER}
        currentMileage={143064.24}
        tracksDistance
        tracksHours={false}
        onClose={noop}
        onSuccess={noop}
      />
    ),
  },
  {
    name: 'ApplyPackDialog',
    ui: () => <ApplyPackDialog vin={VIN} packId="oil_and_filter" packName="Oil" onClose={noop} onApplied={noop} />,
  },
  { name: 'WindowStickerUpload', ui: () => <WindowStickerUpload vin={VIN} onSuccess={noop} onClose={noop} /> },
  {
    name: 'VehicleEditDrawer',
    ui: () => (
      <VehicleEditDrawer
        open
        vin={VIN}
        vehicle={VEHICLE}
        onClose={noop}
        onUpdated={noop}
        onDownloadWindowSticker={noop}
        onUploadWindowSticker={noop}
        onManageTorqueSources={noop}
      />
    ),
  },
  {
    name: 'TireList (its drawers)',
    ui: () => <TireList vin={VIN} />,
    open: async () => {
      fireEvent.click(await screen.findByRole('button', { name: 'tireList.add' }))
    },
    live: true,
  },
  {
    name: 'VehicleSpecsPanel (its editor)',
    ui: () => <VehicleSpecsPanel vin={VIN} vehicle={VEHICLE} onUpdated={noop} />,
    open: async () => {
      fireEvent.click(await screen.findByRole('button', { name: 'detail.specs.editAria' }))
    },
    live: true,
  },
]

/** Let queries, effects and the NumberInput poll settle. */
async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
}

beforeEach(() => {
  localStorage.clear()
  // Bare event: the store re-reads everything, so it drops the last row's set.
  window.dispatchEvent(new Event('storage'))
  setUnitPrefs({ units: IMPERIAL_UNITS, unit_preference: null, show_both_units: false })
  seen.log = []
})

describe('every pinned form holds its units through a flip', () => {
  it.each(ROWS)('$name', async (row) => {
    render(row.ui())
    await settle()
    await row.open?.()
    await settle()
    expect(seen.log).toContain(PINNED)
    expect(seen.log).not.toContain(LIVE)

    seen.log = []
    act(() => setUnitPrefs({ units: METRIC_UNITS, unit_preference: null, show_both_units: false }))
    await settle()

    // It re-rendered on the flip, and the pinned answer is still there.
    expect(seen.log).toContain(PINNED)
    if (row.live) {
      // The card beside it repainted.
      expect(seen.log).toContain(LIVE)
    } else {
      expect(new Set(seen.log)).toEqual(new Set([PINNED]))
    }
  })
})
