import { useState, type ReactElement, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, Trash2, Gauge, AlertTriangle, Pencil, RotateCw, Layers, Disc, X } from 'lucide-react'
import { toast } from 'sonner'
import { formatDateForDisplay, formatDateForInput } from '../utils/dateUtils'
import { POSITIONS } from '../types/tire'
import type { MountedPosition, Tire, TireMountPeriod, TirePosition, TireReading, TireSet } from '../types/tire'
import {
  useTires,
  useCreateTire,
  useCreateAndMountTire,
  useDismountTire,
  useMountTire,
  useRestoreTire,
  useRetireTire,
  useRotateTires,
  useTireSets,
  useCreateTireSet,
  useUpdateTireSet,
  useDeleteTireSet,
  useMountTireSet,
  useUpdateTire,
  useAddTireReading,
  useDeleteTire,
} from '../hooks/queries/useTires'
import { useUnitFormat } from '../hooks/useUnitFormat'
import {
  canonicalFromUnitField,
  seedUnitField,
  type QuantityFormat,
  type UnitFieldOrigin,
  type UnitFormat,
} from '../utils/unitFormat'
import { withUnitSession } from '../contexts/UnitSession'
import { canonicalFromTreadField } from '../utils/treadEntry'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { formatHours, hoursFromField } from '../utils/hoursFormat'
import { num } from '../utils/wireNumber'
import {
  Button,
  IconButton,
  Card,
  Chip,
  Drawer,
  EmptyState,
  Input,
  Field,
  ListRow,
  Toggle,
} from './ui'
import ClickableCard from './ClickableCard'
import AddPastPeriodDrawer from './tires/AddPastPeriodDrawer'
import MountEventFields, { EMPTY_ODOMETER, type OdometerFieldValue } from './tires/MountEventFields'
import MountPeriodEditor from './tires/MountPeriodEditor'
import ReadingEditor from './tires/ReadingEditor'
import TireHistoryDrawer, { needsFix } from './tires/TireHistoryDrawer'
import TreadField from './tires/TreadField'

/**
 * The corners a rotation moves.
 *
 * SPARE is deliberately not one of them. A five-tire rotation that works the
 * spare into the pattern is a real thing, but it is only correct for a
 * full-size matching spare, and getting it wrong puts a temporary spare into
 * daily service. The rotate endpoint takes an arbitrary move list, so that
 * case stays expressible; this UI does not guess at it.
 */
const ROTATION_CORNERS = ['FL', 'FR', 'RL', 'RR'] as const
type RotationCorner = (typeof ROTATION_CORNERS)[number]

type RotationPatternId = 'forwardCross' | 'rearwardCross' | 'xPattern' | 'frontToBack'

/**
 * Where each corner's tire goes, per standard pattern.
 *
 * These are the four patterns every tire manufacturer publishes, and which one
 * is right depends on the drivetrain, so the drawer names the drivetrain
 * rather than making the user recognise the diagram.
 *
 * Every entry must be a PERMUTATION of `ROTATION_CORNERS`: a typo that sends
 * two tires to one corner is rejected by the request schema with a 422 the
 * user cannot act on, and one that drops a corner would silently leave a tire
 * where it was. `TireList.rotationPatterns.test.ts` asserts the property, one
 * pattern at a time, rather than trusting four hand-written maps to be read
 * correctly.
 */
const ROTATION_PATTERNS: Record<RotationPatternId, Record<RotationCorner, RotationCorner>> = {
  // The fronts go straight back; the rears cross to the front. FWD wears the
  // fronts, so the worn pair moves to the axle that wears less.
  forwardCross: { FL: 'RL', FR: 'RR', RL: 'FR', RR: 'FL' },
  // The mirror image, for RWD and 4WD, which wear the rears.
  rearwardCross: { FL: 'RR', FR: 'RL', RL: 'FL', RR: 'FR' },
  xPattern: { FL: 'RR', FR: 'RL', RL: 'FR', RR: 'FL' },
  // The only pattern that keeps every tire on its own side, which is what a
  // directional tread pattern requires.
  frontToBack: { FL: 'RL', FR: 'RR', RL: 'FL', RR: 'FR' },
}

const ROTATION_PATTERN_IDS = Object.keys(ROTATION_PATTERNS) as RotationPatternId[]

/**
 * The canonical origin of every unit-bearing field on the tire form.
 *
 * Held INSIDE the form state rather than beside it: every `setForm({ ...form,
 * x })` then carries the origins forward automatically, so there is no way to
 * update one and forget the other. See `utils/unitFormat.ts` for why an
 * untouched field must submit the value it was seeded from rather than a
 * re-conversion of what it displays.
 */
interface TireFormOrigins {
  tread_depth_mm: UnitFieldOrigin
  min_tread_mm: UnitFieldOrigin
  pressure_kpa: UnitFieldOrigin
}

interface TireFormState {
  /** Null means "into storage": a tire owned but not on the vehicle. */
  position: TirePosition
  /** Null means ungrouped. Only editable on an EXISTING tire: `POST /tires`
   *  does not take a `set_id`, because a set is a label you apply to a tire
   *  you already own rather than part of its identity. */
  set_id: number | null
  brand: string
  model_name: string
  size: string
  dot_code: string
  tread_depth_mm: string
  pressure_kpa: string
  min_tread_mm: string
  notes: string
  /** YYYY-MM-DD. Only meaningful on the corner branch of Add; ignored on Edit
   *  and on the storage branch, both of which hide the field that sets it. */
  mounted_on: string
  /** The odometer as typed, in the user's distance unit, with the canonical
   *  value it was last seeded from. Same scope as `mounted_on`. */
  mounted_odometer_km: OdometerFieldValue
  /** The hour meter as typed. Same scope as `mounted_on`. */
  mounted_hours: string
  storage_location: string
  origins: TireFormOrigins
}

interface ReadingFormOrigins {
  odometer_km: UnitFieldOrigin
  tread_depth_mm: UnitFieldOrigin
  pressure_kpa: UnitFieldOrigin
}

interface ReadingFormState {
  recorded_at: string
  odometer_km: string
  engine_hours: string
  tread_depth_mm: string
  pressure_kpa: string
  notes: string
  origins: ReadingFormOrigins
}

/**
 * The wear-out threshold a new tire gets, in canonical MILLIMETRES.
 *
 * Mirrors `TireBase.min_tread_mm`'s Pydantic default. It used to live in the
 * form as the string `'2.0'`, which was correct only while the input meant
 * millimetres: once an imperial user's field means thirty-seconds of an inch,
 * submitting that string unconverted stores 1.5875 mm, and converting it stores
 * 2.38125 mm. Neither is 2.0, and the user touched nothing.
 */
const DEFAULT_MIN_TREAD_MM = 2.0

/**
 * A blank reading form.
 *
 * A function rather than a shared constant so two open-and-cancel cycles never
 * alias the same origin objects. Both origins are empty, which is the same
 * answer `seedUnitField(null, ...)` gives for any quantity: an empty field has
 * no canonical value to preserve.
 *
 * @returns The empty reading form state.
 */
function emptyReadingForm(): ReadingFormState {
  return {
    recorded_at: '',
    odometer_km: '',
    engine_hours: '',
    tread_depth_mm: '',
    pressure_kpa: '',
    notes: '',
    origins: {
      odometer_km: { canonical: null, display: '' },
      tread_depth_mm: { canonical: null, display: '' },
      pressure_kpa: { canonical: null, display: '' },
    },
  }
}

/**
 * Hands one drawer the units it opened with (R4). The drawers' state and
 * handlers stay up in TireList; this only pins what they label and convert
 * with, so the cards behind them keep repainting live.
 */
const PinnedUnits = withUnitSession(function PinnedUnits({
  children,
}: {
  open: boolean
  children: (u: UnitFormat) => ReactNode
}): ReactElement {
  const u = useUnitFormat()
  return <>{children(u)}</>
})

interface TireListProps {
  vin: string
  /** Opens the Brakes tab's Log measurements, offered while the wheels are off (#202). */
  onLogBrakes?: () => void
}

export default function TireList({ vin, onLogBrakes }: TireListProps) {
  const { t } = useTranslation('vehicles')
  /* Retired tires are history, not inventory: hidden by default, and the list
     query only asks the server for them when the toggle is on. Declared here
     rather than beside the rest of the drawer/dialog state below, since the
     query on the next line reads it -- a `const` used before its own
     declaration is a ReferenceError, not just a style nit. */
  const [showRetired, setShowRetired] = useState(false)
  /* After a rotation or a set fit the wheels have just been off, which is when
     brake pads get measured. A callout rather than a toast action: a toast
     leaves in seconds, and this waits until it's used or dismissed. */
  const [brakesPrompt, setBrakesPrompt] = useState(false)
  const { data, isLoading, error } = useTires(vin, showRetired)
  const createTire = useCreateTire(vin)
  const createAndMount = useCreateAndMountTire(vin)
  const updateTire = useUpdateTire(vin)
  const mount = useMountTire(vin)
  const dismount = useDismountTire(vin)
  const retire = useRetireTire(vin)
  const restore = useRestoreTire(vin)
  const rotate = useRotateTires(vin)
  const [retireTireId, setRetireTireId] = useState<number | null>(null)
  const [rotateOpen, setRotateOpen] = useState(false)
  const [rotatePattern, setRotatePattern] = useState<RotationPatternId>('forwardCross')
  const sets = useTireSets(vin)
  const createSet = useCreateTireSet(vin)
  const updateSet = useUpdateTireSet(vin)
  const deleteSet = useDeleteTireSet(vin)
  const mountSet = useMountTireSet(vin)
  const [setsOpen, setSetsOpen] = useState(false)
  const [newSetName, setNewSetName] = useState('')
  const [renamingSetId, setRenamingSetId] = useState<number | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [renameError, setRenameError] = useState<string | null>(null)
  /* The fit form expands INSIDE the sets drawer rather than opening a second
   * one. `<Drawer>` sets `inert` on #root, so a drawer opened from a drawer is
   * dead rather than merely behind -- and a fit needs one field, which does not
   * justify a nested surface even if it worked. */
  const [fittingSetId, setFittingSetId] = useState<number | null>(null)
  const [fitOdometer, setFitOdometer] = useState<OdometerFieldValue>(EMPTY_ODOMETER)
  const [fitHours, setFitHours] = useState('')
  const [mountTireId, setMountTireId] = useState<number | null>(null)
  const [dismountTireId, setDismountTireId] = useState<number | null>(null)
  const [mountPosition, setMountPosition] = useState<MountedPosition>('FL')
  /* Separate odometer state per drawer. They were briefly one field, which
   * meant a value typed into Mount and abandoned reappeared in Dismount --
   * and silently became that period's closing bound. A wrong odometer here is
   * not a cosmetic slip: it is the number the tire's whole distance is
   * computed from. */
  const [mountOdometer, setMountOdometer] = useState<OdometerFieldValue>(EMPTY_ODOMETER)
  const [dismountOdometer, setDismountOdometer] = useState<OdometerFieldValue>(EMPTY_ODOMETER)
  const [retireOdometer, setRetireOdometer] = useState<OdometerFieldValue>(EMPTY_ODOMETER)
  const [rotateOdometer, setRotateOdometer] = useState<OdometerFieldValue>(EMPTY_ODOMETER)
  // The hour meter gets its own state per drawer too, for the same reason (#217).
  const [mountHours, setMountHours] = useState('')
  const [dismountHours, setDismountHours] = useState('')
  const [retireHours, setRetireHours] = useState('')
  const [rotateHours, setRotateHours] = useState('')
  // One date per dialog, defaulting to the LOCAL calendar date. Reset to
  // today, with the odometer emptied, each time its dialog opens.
  const [mountDate, setMountDate] = useState(() => formatDateForInput())
  const [dismountDate, setDismountDate] = useState(() => formatDateForInput())
  const [dismountLocation, setDismountLocation] = useState('')
  const [retireDate, setRetireDate] = useState(() => formatDateForInput())
  const [rotateDate, setRotateDate] = useState(() => formatDateForInput())
  const [fitDate, setFitDate] = useState(() => formatDateForInput())
  const addReading = useAddTireReading(vin)
  const remove = useDeleteTire(vin)
  /* Every unit on the cards resolves through `u`, per
   * quantity. The binary `system` is gone from the file: it is collapsed from
   * VOLUME (spec D8), so a custom user with litres and miles reads 'metric' and
   * a projection formatted from it would render kilometres directly above an
   * odometer field in miles. Two distances, one card, two units, which is the
   * disagreement D2 forbids and the one this file already carried for pressure.
   * Cost of joining: the projection reads "~621 mi" where it read "~621.37 mi",
   * because distance's declared precision is whole units.
   * The drawers get theirs from PinnedUnits instead, so this one is the live
   * card's only. */
  const u = useUnitFormat()

  /** A figure on the tire's own axis: hours on an hours-only vehicle, else the reader's distance unit. */
  const usageText = (tire: Tire, value: number | string): string =>
    tire.usage_axis === 'hours' ? formatHours(value) : u.distance.format(num(value))

  /**
   * Populate the tire form, recording what each unit-bearing field came from.
   *
   * One seeding path for Add and Edit, because they used to differ: Add carried
   * a raw canonical default and Edit read stored values straight into the input.
   * Both were correct only while the input meant millimetres.
   *
   * @param tire The tire being edited, or null when adding.
   * @param position The position to start on.
   * @returns The form state, origins included.
   */
  // Seeds read the live units at the click that opens the drawer, which is the
  // same moment its PinnedUnits captures, so seed and submit agree.
  const seedTireForm = (tire: Tire | null, position: TirePosition): TireFormState => {
    const tread = seedUnitField(num(tire?.tread_depth_mm), u.tread)
    const minTread = seedUnitField(num(tire?.min_tread_mm) ?? DEFAULT_MIN_TREAD_MM, u.tread)
    const pressure = seedUnitField(num(tire?.pressure_kpa), u.pressure)
    return {
      position,
      set_id: tire?.set_id ?? null,
      brand: tire?.brand ?? '',
      model_name: tire?.model_name ?? '',
      size: tire?.size ?? '',
      dot_code: tire?.dot_code ?? '',
      tread_depth_mm: tread.display,
      pressure_kpa: pressure.display,
      min_tread_mm: minTread.display,
      notes: tire?.notes ?? '',
      mounted_on: formatDateForInput(),
      mounted_odometer_km: EMPTY_ODOMETER,
      mounted_hours: '',
      storage_location: tire?.storage_location ?? '',
      origins: { tread_depth_mm: tread, min_tread_mm: minTread, pressure_kpa: pressure },
    }
  }

  const [formOpen, setFormOpen] = useState(false)
  const [editingTireId, setEditingTireId] = useState<number | null>(null)
  const [readingTireId, setReadingTireId] = useState<number | null>(null)
  const [historyTireId, setHistoryTireId] = useState<number | null>(null)
  const [editingPeriod, setEditingPeriod] = useState<TireMountPeriod | null>(null)
  const [editingReading, setEditingReading] = useState<TireReading | null>(null)
  const [addingPeriod, setAddingPeriod] = useState(false)
  const [form, setForm] = useState<TireFormState>(() => seedTireForm(null, 'FL'))
  const [readingForm, setReadingForm] = useState<ReadingFormState>(emptyReadingForm)

  const tires = data?.tires ?? []
  /* Which readings this vehicle takes, from the server that 422s the other one (#217).
     An older response without the flags reads as distance only. */
  const tracksDistance = data?.tracks_distance ?? true
  const tracksHours = data?.tracks_hours ?? false

  /* Each axis's key only when the vehicle takes it, so a distance vehicle's payloads stay as they were. */
  const odometerKey = <K extends string>(
    key: K,
    value: OdometerFieldValue,
    distance: QuantityFormat
  ): Partial<Record<K, number | null>> =>
    tracksDistance
      ? ({ [key]: canonicalFromUnitField(value.typed, value.origin, distance) } as Record<K, number | null>)
      : {}
  const hoursKey = <K extends string>(key: K, typed: string): Partial<Record<K, number | null>> =>
    tracksHours ? ({ [key]: hoursFromField(typed) } as Record<K, number | null>) : {}
  /* A stored tire occupies no corner, so its null position must not be
   * counted as taken -- otherwise dismounting a tire would make its old
   * corner permanently unavailable. */
  const takenPositions = new Set(
    tires.map((tire: Tire) => tire.position).filter((p): p is MountedPosition => p != null)
  )
  const freePositions = POSITIONS.filter((p) => !takenPositions.has(p))
  const mountedTires = tires.filter((tire: Tire) => tire.position != null && tire.retired_on == null)
  const storedTires = tires.filter((tire: Tire) => tire.position == null && tire.retired_on == null)
  const retiredTires = tires.filter((tire: Tire) => tire.retired_on != null)

  /* Rotation is all-or-nothing server-side, so the button is only offered when
     every corner it would move is actually occupied. Sending a move for an
     empty corner is a 404 on the missing tire; sending a partial pattern is a
     409 on the corner held by a tire that is not in the rotation. Neither is
     something a user can act on, and both are avoidable by looking at the list
     that is already on screen. */
  const tireAt = (position: RotationCorner): Tire | undefined =>
    mountedTires.find((tire: Tire) => tire.position === position)
  const canRotate = ROTATION_CORNERS.every((corner) => tireAt(corner) !== undefined)

  /* `tire_ids` and `mounted_count` carry server-side defaults, so the generated
     type marks them optional even though every response has them. Normalised
     once here rather than defended at each of the four places below -- the
     shape of lie that has cost this codebase two Criticals before. */
  const tireSets = (sets.data?.sets ?? []).map((s: TireSet) => ({
    ...s,
    tire_ids: s.tire_ids ?? [],
    mounted_count: s.mounted_count ?? 0,
  }))
  /* Stored tires grouped by set, ungrouped last. Rendering them as one flat
     list is what makes a second seasonal set unreadable: four winter tires and
     a spare look the same, and the whole reason a set exists is to say which
     four move together. */
  const storedGroups: { key: string; label: string; tires: Tire[] }[] = [
    ...tireSets
      .map((s) => ({
        key: `set-${s.id}`,
        label: s.name,
        tires: storedTires.filter((tire: Tire) => tire.set_id === s.id),
      }))
      .filter((group) => group.tires.length > 0),
    {
      key: 'ungrouped',
      label: t('tireList.setUngrouped'),
      tires: storedTires.filter((tire: Tire) => tire.set_id == null),
    },
  ].filter((group) => group.tires.length > 0)

  /* Derived from the live list rather than held in state: a mutation refetches
   * and replaces every Tire object, so a captured one would go stale the moment
   * a reading is saved. */
  const readingTire = tires.find((tire: Tire) => tire.id === readingTireId) ?? null
  const historyTire = tires.find((tire: Tire) => tire.id === historyTireId) ?? null

  /* Spelled out as five literal t() calls rather than t(`…positions.${p}`):
   * validate-i18n-usage scans for string literals, so a computed key is
   * invisible to it and a typo would ship a raw `tireList.positions.RL` to the
   * user. The Record type keeps the map exhaustive. Chips still show the short
   * codes — these are for the card heading and the drawer titles, where there
   * is room and where "FL" was untranslatable English in every locale. */
  const rotationPatternLabels: Record<RotationPatternId, { name: string; desc: string }> = {
    forwardCross: {
      name: t('tireList.rotatePatterns.forwardCross'),
      desc: t('tireList.rotatePatterns.forwardCrossDesc'),
    },
    rearwardCross: {
      name: t('tireList.rotatePatterns.rearwardCross'),
      desc: t('tireList.rotatePatterns.rearwardCrossDesc'),
    },
    xPattern: {
      name: t('tireList.rotatePatterns.xPattern'),
      desc: t('tireList.rotatePatterns.xPatternDesc'),
    },
    frontToBack: {
      name: t('tireList.rotatePatterns.frontToBack'),
      desc: t('tireList.rotatePatterns.frontToBackDesc'),
    },
  }

  const positionLabels: Record<MountedPosition, string> = {
    FL: t('tireList.positions.FL'),
    FR: t('tireList.positions.FR'),
    RL: t('tireList.positions.RL'),
    RR: t('tireList.positions.RR'),
    SPARE: t('tireList.positions.SPARE'),
  }

  /**
   * A name for a tire's current position, including when it has none.
   *
   * `position` is nullable since v3.3.0, and a stored tire still has to be
   * identifiable in a list, a drawer title and an aria-label. Typed against
   * `MountedPosition` so `positionLabels[null]` cannot type-check anywhere:
   * every caller comes through here and gets the storage wording instead of
   * an `undefined` rendered into the UI.
   */
  const labelFor = (position: TirePosition): string =>
    position ? positionLabels[position] : t('tireList.inStorage')

  /**
   * What to show for "distance on this tire", for every status.
   *
   * Six statuses, each with its own wording, because the previous single
   * "unknown" collapsed five different repairs into one message. In
   * particular `nothing_bounded` is the state of EVERY tire immediately after
   * upgrading -- migration 097 gives each existing tire an assumed mount
   * period whose start odometer is unknown -- so it is the common case rather
   * than an edge one, and it must never render as "0 km".
   *
   * Spelled out as literal t() calls rather than
   * t(`tireList.distance.${status}`): validate-i18n-usage scans for string
   * literals, so a computed key is invisible to it and a missing translation
   * would ship a raw key to the user.
   */
  /**
   * What to show for the wear projection, for every status.
   *
   * The card used to render a bare "—" whenever `projected_km_remaining` was
   * null, which covers seven different situations with one uninformative
   * dash. Driving the real production data made the cost obvious: every tire
   * on the maintainer's own instance showed "Wear Estimate —" and nothing
   * about what to do, which is the same dead end the typed statuses exist to
   * replace.
   */
  const wearSummary = (tire: Tire): string => {
    const remaining = tire.projected_usage_remaining ?? tire.projected_km_remaining
    const projection = (): string =>
      remaining != null
        ? `~${usageText(tire, remaining)}` +
            (tire.projected_wear_date
              ? ` · ${formatDateForDisplay(tire.projected_wear_date)}`
              : '')
        : '—'

    switch (tire.wear_status) {
      case 'projected':
        return projection()
      case 'at_or_below_minimum':
        return t('tireList.wear.replaceNow')
      case 'no_minimum_set':
        return t('tireList.wear.noMinimum')
      case 'insufficient_readings':
        return t('tireList.wear.needsSecondReading')
      case 'no_reading_odometers':
        return tire.usage_axis === 'hours'
          ? t('tireList.wear.needsReadingHours')
          : t('tireList.wear.needsReadingOdometer')
      case 'tread_not_decreasing':
        return t('tireList.wear.treadNotDecreasing')
      case 'no_distance_on_tire':
      case 'unverified_mount_history':
        return tire.usage_axis === 'hours'
          ? t('tireList.wear.needsMountHours')
          : t('tireList.wear.needsMountOdometer')
      default:
        // No status on the payload at all: a response cached by a client that
        // predates v3.3.0, or any future member this switch has not learned
        // yet. Fall back to the number if one is present rather than hiding a
        // figure the server did send -- an unknown status is a reason to stop
        // explaining, not a reason to withhold.
        return projection()
    }
  }

  const distanceSummary = (tire: Tire): string => {
    const total = tire.usage_on_tire ?? tire.distance_km
    const known = tire.known_usage ?? tire.known_distance_km
    const since = tire.known_usage_since ?? tire.known_distance_since
    const nothingBounded =
      tire.usage_axis === 'hours'
        ? t('tireList.distance.nothingBoundedHours')
        : t('tireList.distance.nothingBounded')
    switch (tire.distance_status) {
      case 'complete':
        return total != null ? usageText(tire, total) : '—'
      case 'incomplete':
        return known != null
          ? t('tireList.distance.since', {
              distance: usageText(tire, known),
              date: since ? formatDateForDisplay(since) : '',
            })
          : nothingBounded
      case 'nothing_bounded':
        return nothingBounded
      case 'no_periods':
        return t('tireList.distance.noPeriods')
      case 'spare_only':
        return t('tireList.distance.spareOnly')
      case 'odometer_rollback':
        return t('tireList.distance.rollback')
      default:
        return '—'
    }
  }

  /* The current mount, from the open period. `installed_date` on the
     response is the FIRST mount and lives in the history drawer; a seasonal
     tire's card would go stale after its first swap if it showed that. Four
     keys rather than one with placeholders, so the unknown variants are
     distinguishable in tests, where t() returns its key. */
  const openPeriod = (tire: Tire): TireMountPeriod | null =>
    (tire.mount_periods ?? []).find((p) => p.dismounted_on == null) ?? null
  const lastClosedPeriod = (tire: Tire): TireMountPeriod | null =>
    [...(tire.mount_periods ?? [])].reverse().find((p) => p.dismounted_on != null) ?? null

  const mountedLine = (tire: Tire): string => {
    const p = openPeriod(tire)
    if (!p) return '—'
    const onHours = tire.usage_axis === 'hours'
    const date = p.mounted_on ? formatDateForDisplay(p.mounted_on) : null
    const bound = onHours ? p.mounted_hours : p.mounted_odometer_km
    const odometer = bound != null ? usageText(tire, bound) : null
    if (date && odometer) return t('tireList.mountedLine', { date, odometer })
    if (date) {
      return onHours
        ? t('tireList.mountedDateOnlyHours', { date })
        : t('tireList.mountedDateOnly', { date })
    }
    if (odometer) return t('tireList.mountedOdometerOnly', { odometer })
    return onHours ? t('tireList.mountedUnknownHours') : t('tireList.mountedUnknown')
  }

  const storedLine = (tire: Tire): string => {
    const p = lastClosedPeriod(tire)
    const since = p?.dismounted_on
      ? t('tireList.inStorageSince', { date: formatDateForDisplay(p.dismounted_on) })
      : t('tireList.inStorage')
    return tire.storage_location ? `${since} · ${tire.storage_location}` : since
  }

  /* One key per field, interpolated with the resolved unit, replacing the pairs
   * of unit-specific keys a ternary used to choose between. `odometerMi` and
   * `odometerKm` could only ever name two of the vocabulary's units. Built from
   * the drawer's pinned units, not the list's live ones. */
  const unitLabels = (pu: UnitFormat) => ({
    pressure: t('tireList.pressureWithUnit', { unit: pu.pressure.label }),
    odometer: t('tireList.odometerWithUnit', { unit: pu.distance.label }),
    tread: t('tireList.treadWithUnit', { unit: pu.tread.label }),
    minTread: t('tireList.minTreadWithUnit', { unit: pu.tread.label }),
  })

  /* Add and Edit are deliberately separate intents. The form is one mutable
   * object holding every in-progress field, so reloading it when the position
   * dropdown changes would silently discard whatever the user had typed.
   * Instead, Add only offers unoccupied positions and Edit locks the position. */
  const openAddForm = () => {
    setEditingTireId(null)
    // Storage, not 'FL', when every corner is taken. The old fallback selected
    // an OCCUPIED chip that the form then refused to submit, and the Add button
    // was disabled outright in that state -- so the one moment a second set
    // most obviously needs entering, four tires already on the vehicle, was the
    // one moment nothing could be entered at all.
    setForm(seedTireForm(null, freePositions[0] ?? null))
    setFormOpen(true)
  }

  const openEditForm = (tire: Tire) => {
    setEditingTireId(tire.id)
    // The tire's OWN position, including null. It used to fall back to the
    // first free corner, which titled a stored tire's drawer after a corner it
    // was not in. Editing never moves a tire either way: position changes
    // through mount, dismount and rotate.
    setForm(seedTireForm(tire, tire.position))
    setFormOpen(true)
  }

  const closeForm = () => {
    setFormOpen(false)
    setEditingTireId(null)
  }

  /* Mount, Dismount, Retire and Rotate each open fresh: today's date and an
   * empty odometer, the way Set fit does. They used to reset only on success,
   * so a cancelled dialog carried its date and odometer, an accepted
   * suggestion included, into the next tire's dialog, where a quick confirm
   * recorded them against the wrong tire. */
  const openMount = (tireId: number): void => {
    setMountDate(formatDateForInput())
    setMountOdometer(EMPTY_ODOMETER)
    setMountHours('')
    setMountTireId(tireId)
  }

  const openDismount = (tire: Tire): void => {
    setDismountDate(formatDateForInput())
    setDismountOdometer(EMPTY_ODOMETER)
    setDismountHours('')
    setDismountLocation(tire.storage_location ?? '')
    setDismountTireId(tire.id)
  }

  const openRetire = (tireId: number): void => {
    setRetireDate(formatDateForInput())
    setRetireOdometer(EMPTY_ODOMETER)
    setRetireHours('')
    setRetireTireId(tireId)
  }

  const openRotate = (): void => {
    setRotateDate(formatDateForInput())
    setRotateOdometer(EMPTY_ODOMETER)
    setRotateHours('')
    setRotateOpen(true)
  }

  /* Seeded from the tire's current values so the common case — pressure checked,
   * tread unchanged — is a single edit rather than re-typing both.
   *
   * ★ That convenience is exactly why this path has to record origins too. The
   * backend overwrites the parent tire's tread from the newest reading
   * (`app/services/tire_service.py`), so a user who opens this drawer, corrects
   * only the pressure and saves would rewrite the tire's stored tread with a
   * round-tripped 7.14375 mm. Its own seed and submit are why it was missed
   * when Add and Edit were fixed. */
  const openReadingForm = (tire: Tire) => {
    const tread = seedUnitField(num(tire.tread_depth_mm), u.tread)
    const pressure = seedUnitField(num(tire.pressure_kpa), u.pressure)
    setReadingForm({
      // Local calendar date. The UTC slice this replaced was tomorrow after
      // early evening in the Americas.
      recorded_at: formatDateForInput(),
      odometer_km: '',
      engine_hours: '',
      tread_depth_mm: tread.display,
      pressure_kpa: pressure.display,
      notes: '',
      origins: {
        odometer_km: { canonical: null, display: '' },
        tread_depth_mm: tread,
        pressure_kpa: pressure,
      },
    })
    setReadingTireId(tire.id)
  }

  const handleSave = (pu: UnitFormat) => {
    // Create-and-mount for a new tire, PUT for an existing one.
    //
    // Before v3.3.0 both were one POST that upserted by position, so the same
    // payload covered both. It no longer does: a POST to an occupied corner is
    // now a 409, and `position` is not a writable field on a tire at all --
    // where a tire sits changes through mount/dismount, not through its
    // metadata form.
    const shared = {
      brand: form.brand || null,
      model_name: form.model_name || null,
      size: form.size || null,
      dot_code: form.dot_code || null,
      tread_depth_mm: canonicalFromTreadField(
        form.tread_depth_mm,
        form.origins.tread_depth_mm,
        pu.tread
      ),
      pressure_kpa: canonicalFromUnitField(
        form.pressure_kpa,
        form.origins.pressure_kpa,
        pu.pressure
      ),
      min_tread_mm:
        canonicalFromTreadField(form.min_tread_mm, form.origins.min_tread_mm, pu.tread) ??
        DEFAULT_MIN_TREAD_MM,
      notes: form.notes || null,
    }
    // Sent only where its input is rendered: editing, or adding to storage.
    // The corner branch of Add hides it, so a location typed on In storage
    // before switching to a corner would be saved where the form no longer
    // shows it.
    const storageLocation = form.storage_location.trim() || null

    const handlers = {
      onSuccess: () => {
        toast.success(t('tireList.saved'))
        closeForm()
      },
      onError: (err: unknown) => {
        toast.error(getActionErrorMessage(err, t('tireList.saveAction')))
      },
    }

    if (editingTireId !== null) {
      // `set_id` goes ONLY here. `TireCreate` declares extra="forbid", so
      // sending it on a create is a 422 rather than a field the server ignores
      // -- membership is a label applied to a tire you already own.
      updateTire.mutate(
        { tireId: editingTireId, set_id: form.set_id, ...shared, storage_location: storageLocation },
        handlers
      )
      return
    }
    // `POST /tires` forbids a `position` key outright (extra="forbid"), so the
    // two creates cannot share one payload: passing `position: null` to it is a
    // 422, not a null.
    if (form.position == null) {
      createTire.mutate({ vin, ...shared, storage_location: storageLocation }, handlers)
      return
    }
    if (!form.mounted_on) {
      toast.error(t('tireList.eventDateRequired'))
      return
    }
    createAndMount.mutate(
      {
        vin,
        position: form.position,
        ...shared,
        mounted_on: form.mounted_on,
        ...odometerKey('mounted_odometer_km', form.mounted_odometer_km, pu.distance),
        ...hoursKey('mounted_hours', form.mounted_hours),
      },
      handlers
    )
  }

  /**
   * Retire the tire the retire drawer is open on.
   *
   * Separate from `handleDelete` on purpose, and it is the one users should
   * reach for: retiring keeps every reading and every mount period, which is
   * the history this release exists to make worth collecting. Delete stays in
   * the edit drawer for a tire entered by mistake.
   */
  const handleRetire = (pu: UnitFormat) => {
    if (!retireDate) {
      toast.error(t('tireList.eventDateRequired'))
      return
    }
    if (retireTireId === null) return
    retire.mutate(
      {
        tireId: retireTireId,
        ...odometerKey('dismounted_odometer_km', retireOdometer, pu.distance),
        ...hoursKey('dismounted_hours', retireHours),
        dismounted_on: retireDate,
      },
      {
        onSuccess: () => {
          toast.success(t('tireList.retired'))
          setRetireTireId(null)
        },
        onError: (err: unknown) =>
          toast.error(getActionErrorMessage(err, t('tireList.retireAction'))),
      }
    )
  }

  const handleCreateSet = () => {
    const name = newSetName.trim()
    if (!name) return
    createSet.mutate(
      { name },
      {
        onSuccess: () => {
          toast.success(t('tireList.setCreated'))
          setNewSetName('')
        },
        onError: (err: unknown) =>
          toast.error(getActionErrorMessage(err, t('tireList.setCreateAction'))),
      }
    )
  }

  const handleRenameSet = (setId: number) => {
    const name = renameValue.trim()
    if (!name) {
      setRenameError(t('common:validation.tireSet.nameRequired'))
      return
    }
    setRenameError(null)
    updateSet.mutate(
      { setId, name },
      {
        onSuccess: () => {
          toast.success(t('tireList.setSaved'))
          setRenamingSetId(null)
        },
        onError: (err: unknown) =>
          toast.error(getActionErrorMessage(err, t('tireList.setSaveAction'))),
      }
    )
  }

  const handleDeleteSet = (setId: number) => {
    if (!confirm(t('tireList.setConfirmDelete'))) return
    deleteSet.mutate(setId, {
      onSuccess: () => toast.success(t('tireList.setDeleted')),
      onError: (err: unknown) =>
        toast.error(getActionErrorMessage(err, t('tireList.setDeleteAction'))),
    })
  }

  /**
   * Fit a whole set: the one action that replaces eight.
   *
   * No positions in the payload. The server reads each tire's own mount
   * history for the corner it was last on, and refuses -- naming the tires --
   * rather than guessing for one that has never been fitted.
   */
  const handleFitSet = (setId: number, pu: UnitFormat) => {
    if (!fitDate) {
      toast.error(t('tireList.eventDateRequired'))
      return
    }
    mountSet.mutate(
      {
        setId,
        ...odometerKey('odometer_km', fitOdometer, pu.distance),
        ...hoursKey('engine_hours', fitHours),
        mounted_on: fitDate,
      },
      {
        onSuccess: () => {
          toast.success(t('tireList.setFitted'))
          setBrakesPrompt(true)
          setFittingSetId(null)
          setFitOdometer(EMPTY_ODOMETER)
          setFitHours('')
          setFitDate(formatDateForInput())
          setSetsOpen(false)
        },
        onError: (err: unknown) =>
          toast.error(getActionErrorMessage(err, t('tireList.setFitAction'))),
      }
    )
  }

  /**
   * Apply the selected pattern to the four mounted corners.
   *
   * The moves are built from the LIVE list rather than from anything held in
   * state, so a rotation cannot be submitted against an arrangement that has
   * since changed. `canRotate` has already established every corner is filled;
   * the guard here is what makes that a type-level fact rather than a promise.
   */
  const handleRotate = (pu: UnitFormat) => {
    if (!rotateDate) {
      toast.error(t('tireList.eventDateRequired'))
      return
    }
    const pattern = ROTATION_PATTERNS[rotatePattern]
    const moves = ROTATION_CORNERS.flatMap((corner) => {
      const tire = tireAt(corner)
      return tire ? [{ tire_id: tire.id, position: pattern[corner] }] : []
    })
    if (moves.length !== ROTATION_CORNERS.length) {
      toast.error(t('tireList.rotateNeedsFourCorners'))
      return
    }
    rotate.mutate(
      {
        moves,
        ...odometerKey('odometer_km', rotateOdometer, pu.distance),
        ...hoursKey('engine_hours', rotateHours),
        rotated_on: rotateDate,
      },
      {
        onSuccess: () => {
          toast.success(t('tireList.rotated'))
          setBrakesPrompt(true)
          setRotateOpen(false)
        },
        onError: (err: unknown) =>
          toast.error(getActionErrorMessage(err, t('tireList.rotateAction'))),
      }
    )
  }

  /* Only reachable from the edit drawer, so `editingTireId` is the subject.
   * The mutation had no success or error callbacks at all when this lived on
   * the card, which meant a failed delete was completely silent and the row
   * simply stayed put with no explanation. */
  const handleDelete = () => {
    if (editingTireId === null) return
    if (!confirm(t('tireList.confirmDelete'))) return
    remove.mutate(editingTireId, {
      onSuccess: () => {
        toast.success(t('tireList.deleted'))
        closeForm()
      },
      onError: (err) => {
        toast.error(getActionErrorMessage(err, t('tireList.deleteAction')))
      },
    })
  }

  const handleReading = (tireId: number, pu: UnitFormat) => {
    if (!readingForm.recorded_at) {
      toast.error(t('tireList.eventDateRequired'))
      return
    }
    /* Resolved before the guard so the refusal and the payload come from one
     * computation rather than two. It is NOT a behaviour change against the old
     * truthiness check: `<Input type="number">` hands back an empty string for
     * text that is not a number, so `null` here means "blank" and nothing else
     * reaches it. */
    const tread = canonicalFromTreadField(
      readingForm.tread_depth_mm,
      readingForm.origins.tread_depth_mm,
      pu.tread
    )
    /* Hoisted out of the payload for the same reason as tread: the guard below
     * and the body must be one computation, not two that can disagree. */
    const pressure = canonicalFromUnitField(
      readingForm.pressure_kpa,
      readingForm.origins.pressure_kpa,
      pu.pressure
    )
    /* At least one MEASUREMENT, which is the rule `TireReadingCreate` enforces
     * server-side. Tread alone was required here until #152: the reporter is
     * tracking a slow leak and owns no tread gauge, so the field they could not
     * fill in was blocking the one they could. The odometer deliberately does
     * not satisfy this: it is context for the wear projection, not an
     * observation of the tire. */
    if (tread === null && pressure === null) {
      toast.error(t('tireList.treadOrPressureRequired'))
      return
    }
    addReading.mutate(
      {
        tireId,
        recorded_at: readingForm.recorded_at,
        ...(tracksDistance
          ? {
              odometer_km: canonicalFromUnitField(
                readingForm.odometer_km,
                readingForm.origins.odometer_km,
                pu.distance
              ),
            }
          : {}),
        ...hoursKey('engine_hours', readingForm.engine_hours),
        tread_depth_mm: tread,
        pressure_kpa: pressure,
        notes: readingForm.notes || null,
      },
      {
        onSuccess: () => {
          toast.success(t('tireList.readingSaved'))
          setReadingTireId(null)
        },
        onError: (err) => {
          toast.error(getActionErrorMessage(err, t('tireList.saveReadingAction')))
        },
      }
    )
  }

  if (isLoading) {
    return <div className="text-text-mute">{t('common:loading')}</div>
  }
  if (error) {
    return (
      <div className="rounded-panel border border-danger bg-danger/10 p-4 text-danger">
        {getActionErrorMessage(error, t('tireList.loadAction'))}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <Gauge className="h-5 w-5" />
          {t('tireList.title')}
        </h2>
        <div className="flex items-center gap-2">
          <Toggle
            id="show-retired"
            label={t('tireList.showRetired')}
            checked={showRetired}
            onChange={setShowRetired}
          />
          {/* Vehicle-level, so it sits in the header rather than on a card:
              a rotation is one action on four tires, and putting it on each
              card would ask which of four identical buttons to press. */}
          <Button
            variant="secondary"
            size="sm"
            icon={Layers}
            onClick={() => setSetsOpen(true)}
          >
            {t('tireList.sets')}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={RotateCw}
            disabled={!canRotate || rotate.isPending}
            title={canRotate ? undefined : t('tireList.rotateNeedsFourCorners')}
            onClick={openRotate}
          >
            {t('tireList.rotate')}
          </Button>
          {/* No longer disabled when every corner is taken: that is exactly
              when a second seasonal set gets entered, and Add now offers
              storage as a destination. */}
          <Button variant="primary" size="sm" onClick={openAddForm} icon={Plus}>
            {t('tireList.add')}
          </Button>
        </div>
      </div>

      {brakesPrompt && onLogBrakes && (
        <Card padding="sm" className="flex flex-wrap items-center justify-between gap-3">
          <span className="flex items-center gap-2 text-sm">
            <Disc aria-hidden="true" className="h-4 w-4" />
            {t('tireList.brakesPrompt')}
          </span>
          <span className="flex items-center gap-2">
            <Button size="sm" variant="secondary" onClick={onLogBrakes}>
              {t('tireList.brakesPromptAction')}
            </Button>
            <IconButton
              icon={X}
              label={t('tireList.brakesPromptDismiss')}
              variant="ghost"
              size="sm"
              onClick={() => setBrakesPrompt(false)}
            />
          </span>
        </Card>
      )}

      {tires.length === 0 && (
        <EmptyState icon={Gauge} title={t('tireList.empty')} description={t('tireList.emptyHint')} />
      )}

      {/* Mounted and stored are separate sections, not one list sorted by
          position. "In storage" is a state a tire spends half the year in
          now, and a stored tire mixed into the corner list reads as a corner
          whose label failed to render. The heading only appears when there is
          something in it, so a single-set owner sees exactly what they saw
          before this release. */}
      {storedTires.length > 0 && (
        <h3 className="text-sm font-semibold text-text-mute">{t('tireList.onTheVehicle')}</h3>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        {mountedTires.map((tire: Tire) => (
          <ClickableCard
            key={tire.id}
            padding="sm"
            className="space-y-2"
            label={t('tireList.historyOpen', { position: labelFor(tire.position) })}
            onActivate={() => setHistoryTireId(tire.id)}
          >
            {/* The whole card opens the history and nothing sits over its values,
                so the DOT code can be long-pressed and copied (#179). The buttons
                inside keep their own clicks: ClickableCard ignores one that starts there. */}
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="font-semibold flex items-center gap-2">
                  {labelFor(tire.position)}
                  {tire.below_threshold && (
                    <span className="inline-flex items-center gap-1 text-xs text-danger">
                      <AlertTriangle className="h-3.5 w-3.5" />
                      {t('tireList.lowTread')}
                    </span>
                  )}
                </div>
                <div className="text-sm text-text-mute">
                  {[tire.brand, tire.model_name, tire.size].filter(Boolean).join(' · ') || '—'}
                </div>
              </div>
              {/* Delete lives in the edit drawer, not here: it is the one
                  destructive action on a card whose other controls (Edit, Log
                  Reading) are routine, and sitting them side by side invites a
                  mis-tap that costs a tire's whole reading history. */}
              <IconButton
                icon={Pencil}
                label={t('tireList.edit')}
                variant="ghost"
                size="sm"
                onClick={() => openEditForm(tire)}
              />
            </div>
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
              <dt className="text-text-mute">{t('tireList.dot')}</dt>
              <dd className="font-mono">{tire.dot_code || '—'}</dd>
              <dt className="text-text-mute">{t('tireList.tread')}</dt>
              <dd className="font-mono">
                {tire.tread_depth_mm != null ? u.tread.format(num(tire.tread_depth_mm)) : '—'}
              </dd>
              <dt className="text-text-mute">{t('tireList.pressure')}</dt>
              {/* Through the adapter. The binary `UnitFormatter.formatPressure`
                  this replaced rendered BAR for a metric user while the form
                  below it accepts kPa, a disagreement this file's own comment
                  used to document; phase 3b task 2 deleted that method once
                  this was its last would-be caller. Binding decision D2
                  requires one unit for entry and display. */}
              <dd className="font-mono">
                {tire.pressure_kpa != null ? u.pressure.format(num(tire.pressure_kpa)) : '—'}
              </dd>
              <dt className="text-text-mute">{t('tireList.projection')}</dt>
              <dd className="font-mono text-xs">{wearSummary(tire)}</dd>
              {/* Distance on tire belongs on the MOUNTED card, not only on the
                  stored one. It is the number this whole release exists to
                  make correct, and leaving it off the card people actually
                  look at made the feature invisible on real data. */}
              <dt className="text-text-mute">
                {tire.usage_axis === 'hours' ? t('tireList.hoursOnTire') : t('tireList.distanceOnTire')}
              </dt>
              <dd className="flex items-center gap-2 font-mono text-xs">
                <span>{distanceSummary(tire)}</span>
                {/* "Add an odometer to this tire's mount" was an instruction
                    with no control behind it until v3.4.0. This is the control. */}
                {needsFix(tire) && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setHistoryTireId(tire.id)}
                  >
                    {t('tireList.fix')}
                  </Button>
                )}
              </dd>
              <dt className="text-text-mute">{t('tireList.mountedOn')}</dt>
              <dd className="font-mono text-xs">{mountedLine(tire)}</dd>
            </dl>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="secondary"
                onClick={() => openReadingForm(tire)}
              >
                {t('tireList.addReading')}
              </Button>
              {/* Dismount, not delete. Taking a tire off for the season keeps
                  every reading and mount period; the destructive action stays
                  in the edit drawer where a mis-tap cannot reach it. */}
              <Button
                size="sm"
                variant="ghost"
                disabled={dismount.isPending}
                onClick={() => openDismount(tire)}
              >
                {t('tireList.dismount')}
              </Button>
              {/* Retire sits beside Dismount and not beside Delete, because
                  the mis-tap this arrangement guards against is the one that
                  actually happens: reaching for Delete when you mean "I
                  replaced this tire". The drawer it opens IS the confirmation
                  step, and it explains the difference. */}
              <Button
                size="sm"
                variant="ghost"
                disabled={retire.isPending}
                onClick={() => openRetire(tire.id)}
              >
                {t('tireList.retire')}
              </Button>
            </div>
          </ClickableCard>
        ))}
      </div>

      {storedTires.length > 0 && (
        <>
          <h3 className="text-sm font-semibold text-text-mute">{t('tireList.inStorageHeading')}</h3>
          {storedGroups.map((group) => (
        <div key={group.key} className="space-y-2">
          {/* The set's own name, so four winter tires read as a set rather
              than as four unrelated cards. Only rendered when more than one
              group exists: a single-set owner should see exactly what they
              saw before sets existed. */}
          {storedGroups.length > 1 && (
            <h4 className="text-xs font-semibold uppercase tracking-wide text-text-mute">
              {group.label}
            </h4>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            {group.tires.map((tire: Tire) => (
              <Card key={tire.id} padding="sm" className="space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="font-semibold">{labelFor(tire.position)}</div>
                    <div className="text-sm text-text-mute">
                      {[tire.brand, tire.model_name, tire.size].filter(Boolean).join(' · ') || '—'}
                    </div>
                    <div className="text-sm text-text-mute">{storedLine(tire)}</div>
                  </div>
                  <IconButton
                    icon={Pencil}
                    label={t('tireList.edit')}
                    variant="ghost"
                    size="sm"
                    onClick={() => openEditForm(tire)}
                  />
                </div>
                <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
                  <dt className="text-text-mute">{t('tireList.tread')}</dt>
                  <dd className="font-mono">
                    {tire.tread_depth_mm != null ? u.tread.format(num(tire.tread_depth_mm)) : '—'}
                  </dd>
                  <dt className="text-text-mute">
                    {tire.usage_axis === 'hours' ? t('tireList.hoursOnTire') : t('tireList.distanceOnTire')}
                  </dt>
                  <dd className="flex items-center gap-2 font-mono">
                    <span>{distanceSummary(tire)}</span>
                    {needsFix(tire) && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setHistoryTireId(tire.id)}
                      >
                        {t('tireList.fix')}
                      </Button>
                    )}
                  </dd>
                </dl>
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={freePositions.length === 0 || mount.isPending}
                    onClick={() => openMount(tire.id)}
                  >
                    {t('tireList.mount')}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setHistoryTireId(tire.id)}>
                    {t('tireList.history')}
                  </Button>
                  {/* A set can wear out and be replaced without ever going
                      back on the vehicle, so retire has to reach a stored
                      tire too. */}
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={retire.isPending}
                    onClick={() => openRetire(tire.id)}
                  >
                    {t('tireList.retire')}
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        </div>
          ))}
        </>
      )}

      {showRetired && retiredTires.length > 0 && (
        <>
          <h3 className="text-sm font-semibold text-text-mute">{t('tireList.retiredHeading')}</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            {retiredTires.map((tire: Tire) => (
              <Card key={tire.id} padding="sm" className="space-y-2">
                <div>
                  <div className="font-semibold">
                    {[tire.brand, tire.model_name, tire.size].filter(Boolean).join(' · ') || '—'}
                  </div>
                  <div className="text-sm text-text-mute">
                    {t('tireList.retiredOn', {
                      date: tire.retired_on ? formatDateForDisplay(tire.retired_on) : '',
                    })}
                  </div>
                </div>
                <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
                  <dt className="text-text-mute">{t('tireList.tread')}</dt>
                  <dd className="font-mono">
                    {tire.tread_depth_mm != null ? u.tread.format(num(tire.tread_depth_mm)) : '—'}
                  </dd>
                  <dt className="text-text-mute">
                    {tire.usage_axis === 'hours' ? t('tireList.hoursOnTire') : t('tireList.distanceOnTire')}
                  </dt>
                  <dd className="font-mono">{distanceSummary(tire)}</dd>
                </dl>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="ghost" onClick={() => setHistoryTireId(tire.id)}>
                    {t('tireList.history')}
                  </Button>
                  {/* The way back from a mistaken Retire. Back to storage,
                      history intact; a corner is a Mount like any other. */}
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={restore.isPending}
                    onClick={() =>
                      restore.mutate(tire.id, {
                        onSuccess: () => toast.success(t('tireList.restored')),
                        onError: (err: unknown) =>
                          toast.error(getActionErrorMessage(err, t('tireList.restoreAction'))),
                      })
                    }
                  >
                    {t('tireList.restore')}
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        </>
      )}

      {/* Mount and dismount are their own drawers, not confirm dialogs: both
          carry an odometer reading, and that reading is what makes the tire's
          distance computable at all. A confirm with no field would produce a
          mount period with no bound, which reports "not recorded yet" forever
          -- the exact dead end this release exists to get out of. */}
      <PinnedUnits open={mountTireId !== null}>
        {(pu) => (
          <Drawer
            open={mountTireId !== null}
            onClose={() => setMountTireId(null)}
            title={t('tireList.mountTitle')}
            icon={Gauge}
            width="xs"
            closeLabel={t('common:close')}
            footer={
              <>
                <Button variant="ghost" onClick={() => setMountTireId(null)}>
                  {t('common:cancel')}
                </Button>
                <Button
                  variant="primary"
                  disabled={mount.isPending}
                  onClick={() => {
                    if (!mountDate) {
                      toast.error(t('tireList.eventDateRequired'))
                      return
                    }
                    if (mountTireId === null) return
                    mount.mutate(
                      {
                        tireId: mountTireId,
                        position: mountPosition,
                        mounted_on: mountDate,
                        ...odometerKey('mounted_odometer_km', mountOdometer, pu.distance),
                        ...hoursKey('mounted_hours', mountHours),
                      },
                      {
                        onSuccess: () => {
                          toast.success(t('tireList.mounted'))
                          setMountTireId(null)
                        },
                        onError: (err: unknown) =>
                          toast.error(getActionErrorMessage(err, t('tireList.mountAction'))),
                      }
                    )
                  }}
                >
                  {t('tireList.mount')}
                </Button>
              </>
            }
          >
            <div className="space-y-4">
              <Field id="mount-position" label={t('tireList.position')}>
                <div className="flex flex-wrap gap-2">
                  {freePositions.map((position) => (
                    <Chip
                      key={position}
                      selected={mountPosition === position}
                      onClick={() => setMountPosition(position)}
                    >
                      {position}
                    </Chip>
                  ))}
                </div>
              </Field>
              <MountEventFields
                vin={vin}
                idPrefix="mount"
                dateLabel={t('tireList.mountedOn')}
                date={mountDate}
                onDateChange={setMountDate}
                odometerLabel={unitLabels(pu).odometer}
                odometerHint={t('tireList.mountOdometerHint')}
                odometer={mountOdometer}
                onOdometerChange={setMountOdometer}
                tracksDistance={tracksDistance}
                tracksHours={tracksHours}
                hours={mountHours}
                onHoursChange={setMountHours}
                hoursHint={tracksDistance ? undefined : t('tireList.mountHoursHint')}
              />
            </div>
          </Drawer>
        )}
      </PinnedUnits>

      <PinnedUnits open={dismountTireId !== null}>
        {(pu) => (
          <Drawer
            open={dismountTireId !== null}
            onClose={() => setDismountTireId(null)}
            title={t('tireList.dismountTitle')}
            icon={Gauge}
            width="xs"
            closeLabel={t('common:close')}
            footer={
              <>
                <Button variant="ghost" onClick={() => setDismountTireId(null)}>
                  {t('common:cancel')}
                </Button>
                <Button
                  variant="primary"
                  disabled={dismount.isPending}
                  onClick={() => {
                    if (!dismountDate) {
                      toast.error(t('tireList.eventDateRequired'))
                      return
                    }
                    if (dismountTireId === null) return
                    dismount.mutate(
                      {
                        tireId: dismountTireId,
                        ...odometerKey('dismounted_odometer_km', dismountOdometer, pu.distance),
                        ...hoursKey('dismounted_hours', dismountHours),
                        dismounted_on: dismountDate,
                        // Always sent while this drawer is rendered: an empty
                        // string clears the stored location, an absent key would
                        // leave it alone. A user who blanks the field means clear.
                        storage_location: dismountLocation.trim(),
                      },
                      {
                        onSuccess: () => {
                          toast.success(t('tireList.dismounted'))
                          setDismountTireId(null)
                        },
                        onError: (err: unknown) =>
                          toast.error(getActionErrorMessage(err, t('tireList.dismountAction'))),
                      }
                    )
                  }}
                >
                  {t('tireList.dismount')}
                </Button>
              </>
            }
          >
            <div className="space-y-4">
              <p className="text-sm text-text-mute">{t('tireList.dismountHint')}</p>
              <MountEventFields
                vin={vin}
                idPrefix="dismount"
                dateLabel={t('tireList.eventDate')}
                date={dismountDate}
                onDateChange={setDismountDate}
                odometerLabel={unitLabels(pu).odometer}
                odometerHint={t('tireList.mountOdometerHint')}
                odometer={dismountOdometer}
                onOdometerChange={setDismountOdometer}
                tracksDistance={tracksDistance}
                tracksHours={tracksHours}
                hours={dismountHours}
                onHoursChange={setDismountHours}
                hoursHint={tracksDistance ? undefined : t('tireList.mountHoursHint')}
              />
              <Field
                id="dismount-storage"
                label={t('tireList.storageLocation')}
                hint={t('tireList.storageLocationHint')}
              >
                <Input
                  id="dismount-storage"
                  value={dismountLocation}
                  onChange={(e) => setDismountLocation(e.target.value)}
                />
              </Field>
            </div>
          </Drawer>
        )}
      </PinnedUnits>

      {/* Retire is its own drawer for the same reason dismount is: it closes a
          mount period, and a period closed without an odometer is one this
          tire's distance can never be computed from. The hint is the whole
          point of the drawer, though -- it is the only place the app says out
          loud that retiring and deleting are different. */}
      <PinnedUnits open={retireTireId !== null}>
        {(pu) => (
          <Drawer
            open={retireTireId !== null}
            onClose={() => setRetireTireId(null)}
            title={t('tireList.retireTitle')}
            icon={Gauge}
            width="xs"
            closeLabel={t('common:close')}
            footer={
              <>
                <Button variant="ghost" onClick={() => setRetireTireId(null)}>
                  {t('common:cancel')}
                </Button>
                <Button variant="primary" disabled={retire.isPending} onClick={() => handleRetire(pu)}>
                  {t('tireList.retire')}
                </Button>
              </>
            }
          >
            <div className="space-y-4">
              <p className="text-sm text-text-mute">{t('tireList.retireHint')}</p>
              <MountEventFields
                vin={vin}
                idPrefix="retire"
                dateLabel={t('tireList.eventDate')}
                date={retireDate}
                onDateChange={setRetireDate}
                odometerLabel={unitLabels(pu).odometer}
                odometerHint={t('tireList.mountOdometerHint')}
                odometer={retireOdometer}
                onOdometerChange={setRetireOdometer}
                tracksDistance={tracksDistance}
                tracksHours={tracksHours}
                hours={retireHours}
                onHoursChange={setRetireHours}
                hoursHint={tracksDistance ? undefined : t('tireList.mountHoursHint')}
              />
            </div>
          </Drawer>
        )}
      </PinnedUnits>

      <PinnedUnits open={rotateOpen}>
        {(pu) => (
          <Drawer
            open={rotateOpen}
            onClose={() => setRotateOpen(false)}
            title={t('tireList.rotateTitle')}
            icon={RotateCw}
            width="sm"
            closeLabel={t('common:close')}
            footer={
              <>
                <Button variant="ghost" onClick={() => setRotateOpen(false)}>
                  {t('common:cancel')}
                </Button>
                <Button
                  variant="primary"
                  disabled={!canRotate || rotate.isPending}
                  onClick={() => handleRotate(pu)}
                >
                  {t('tireList.rotate')}
                </Button>
              </>
            }
          >
            <div className="space-y-4">
              <p className="text-sm text-text-mute">{t('tireList.rotateHint')}</p>
              <div>
                <span id="rotate-pattern-label" className="mb-1 block text-sm font-medium text-text">
                  {t('tireList.rotatePattern')}
                </span>
                {/* Named by drivetrain rather than drawn as a diagram: the user
                    knows what they drive, and a four-arrow diagram is the part of
                    every tire-rotation chart people misread. The resulting moves
                    are shown below in full, so the choice is checkable without
                    trusting the name. */}
                <div
                  role="group"
                  aria-labelledby="rotate-pattern-label"
                  className="flex flex-wrap gap-2"
                >
                  {ROTATION_PATTERN_IDS.map((id) => (
                    <Chip
                      key={id}
                      selected={rotatePattern === id}
                      onClick={() => setRotatePattern(id)}
                    >
                      {rotationPatternLabels[id].name}
                    </Chip>
                  ))}
                </div>
                <p className="mt-1 text-sm text-text-mute">{rotationPatternLabels[rotatePattern].desc}</p>
              </div>
              <div>
                <span className="mb-1 block text-sm font-medium text-text">
                  {t('tireList.rotatePreview')}
                </span>
                <ul className="space-y-1">
                  {ROTATION_CORNERS.map((corner) => (
                    <ListRow
                      key={corner}
                      label={positionLabels[corner]}
                      value={positionLabels[ROTATION_PATTERNS[rotatePattern][corner]]}
                    />
                  ))}
                </ul>
              </div>
              <MountEventFields
                vin={vin}
                idPrefix="rotate"
                dateLabel={t('tireList.eventDate')}
                date={rotateDate}
                onDateChange={setRotateDate}
                odometerLabel={unitLabels(pu).odometer}
                odometerHint={t('tireList.rotateOdometerHint')}
                odometer={rotateOdometer}
                onOdometerChange={setRotateOdometer}
                tracksDistance={tracksDistance}
                tracksHours={tracksHours}
                hours={rotateHours}
                onHoursChange={setRotateHours}
                hoursHint={tracksDistance ? undefined : t('tireList.rotateHoursHint')}
              />
            </div>
          </Drawer>
        )}
      </PinnedUnits>

      <PinnedUnits open={setsOpen}>
        {(pu) => (
          <Drawer
            open={setsOpen}
            onClose={() => {
              setSetsOpen(false)
              setFittingSetId(null)
              setRenamingSetId(null)
            }}
            title={t('tireList.setsTitle')}
            icon={Layers}
            width="sm"
            closeLabel={t('common:close')}
            footer={
              <Button variant="ghost" onClick={() => setSetsOpen(false)}>
                {t('common:close')}
              </Button>
            }
          >
            <div className="space-y-4">
              <p className="text-sm text-text-mute">{t('tireList.setsHint')}</p>

              {tireSets.length === 0 ? (
                <EmptyState
                  icon={Layers}
                  size="sm"
                  title={t('tireList.setsEmpty')}
                  description={t('tireList.setsEmptyHint')}
                />
              ) : (
                <ul className="space-y-2">
                  {tireSets.map((tireSet) => (
                    <li key={tireSet.id} className="rounded-card border border-border p-3 space-y-2">
                      {renamingSetId === tireSet.id ? (
                        <div className="flex items-end gap-2">
                          <div className="flex-1">
                            <Field
                              id={`set-rename-${tireSet.id}`}
                              label={t('tireList.setName')}
                              error={renameError ?? undefined}
                            >
                              <Input
                                id={`set-rename-${tireSet.id}`}
                                value={renameValue}
                                onChange={(e) => setRenameValue(e.target.value)}
                              />
                            </Field>
                          </div>
                          <Button
                            size="sm"
                            variant="primary"
                            disabled={updateSet.isPending}
                            onClick={() => handleRenameSet(tireSet.id)}
                          >
                            {t('common:save')}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setRenamingSetId(null)}>
                            {t('common:cancel')}
                          </Button>
                        </div>
                      ) : (
                        <>
                          <div className="flex items-start justify-between gap-2">
                            <div>
                              <div className="font-semibold">{tireSet.name}</div>
                              <div className="text-sm text-text-mute">
                                {t('tireList.setMembership', {
                                  total: tireSet.tire_ids.length,
                                  mounted: tireSet.mounted_count,
                                })}
                              </div>
                            </div>
                            <IconButton
                              icon={Trash2}
                              label={t('common:delete')}
                              variant="danger"
                              size="sm"
                              disabled={deleteSet.isPending}
                              onClick={() => handleDeleteSet(tireSet.id)}
                            />
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {/* Fitting an empty set is a 409 the user cannot act
                                on from here, so the control is not offered until
                                the set has something in it. */}
                            <Button
                              size="sm"
                              variant="secondary"
                              disabled={tireSet.tire_ids.length === 0 || mountSet.isPending}
                              onClick={() => {
                                setFittingSetId(tireSet.id)
                                setFitOdometer(EMPTY_ODOMETER)
                                setFitHours('')
                                setFitDate(formatDateForInput())
                              }}
                            >
                              {t('tireList.setFit')}
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => {
                                setRenamingSetId(tireSet.id)
                                setRenameValue(tireSet.name)
                                setRenameError(null)
                              }}
                            >
                              {t('tireList.setRename')}
                            </Button>
                          </div>
                        </>
                      )}

                      {fittingSetId === tireSet.id && (
                        <div className="space-y-2 border-t border-border pt-2">
                          <p className="text-sm text-text-mute">{t('tireList.setFitHint')}</p>
                          <MountEventFields
                            vin={vin}
                            idPrefix={`set-fit-${tireSet.id}`}
                            dateLabel={t('tireList.eventDate')}
                            date={fitDate}
                            onDateChange={setFitDate}
                            odometerLabel={unitLabels(pu).odometer}
                            odometer={fitOdometer}
                            onOdometerChange={setFitOdometer}
                            tracksDistance={tracksDistance}
                            tracksHours={tracksHours}
                            hours={fitHours}
                            onHoursChange={setFitHours}
                          />
                          <div className="flex gap-2">
                            <Button
                              size="sm"
                              variant="primary"
                              disabled={mountSet.isPending}
                              onClick={() => handleFitSet(tireSet.id, pu)}
                            >
                              {t('tireList.setFit')}
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => setFittingSetId(null)}>
                              {t('common:cancel')}
                            </Button>
                          </div>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}

              <div className="flex items-end gap-2 border-t border-border pt-4">
                <div className="flex-1">
                  <Field id="new-set-name" label={t('tireList.setName')}>
                    <Input
                      id="new-set-name"
                      value={newSetName}
                      onChange={(e) => setNewSetName(e.target.value)}
                    />
                  </Field>
                </div>
                <Button
                  variant="primary"
                  icon={Plus}
                  disabled={createSet.isPending || newSetName.trim() === ''}
                  onClick={handleCreateSet}
                >
                  {t('tireList.setAdd')}
                </Button>
              </div>
            </div>
          </Drawer>
        )}
      </PinnedUnits>

      <PinnedUnits open={formOpen}>
        {(pu) => (
          <Drawer
            open={formOpen}
            onClose={closeForm}
            /* Editing names the tire, because position is a tire's whole identity
               and five otherwise-identical rows are indistinguishable without it.
               Adding stays the generic "Add Tire": retitling as the position chips
               are pressed would make a create read like an edit. */
            title={
              editingTireId === null
                ? t('tireList.addTitle')
                : form.position == null
                  ? t('tireList.editTitleStored')
                  : t('tireList.editTitleNamed', { position: positionLabels[form.position] })
            }
            icon={Gauge}
            width="sm"
            closeLabel={t('common:close')}
            footer={
              <>
                {/* mr-auto against the footer's justify-end: the destructive action
                    sits hard left, a full footer's width away from Save. */}
                {editingTireId !== null && (
                  <Button
                    variant="danger"
                    icon={Trash2}
                    className="mr-auto"
                    onClick={handleDelete}
                    disabled={remove.isPending}
                  >
                    {t('common:delete')}
                  </Button>
                )}
                <Button variant="ghost" onClick={closeForm}>
                  {t('common:cancel')}
                </Button>
                <Button variant="primary" onClick={() => handleSave(pu)} disabled={createAndMount.isPending || updateTire.isPending}>
                  {t('common:save')}
                </Button>
              </>
            }
          >
            <div className="space-y-3">
              {/* Push toggles rather than a select: five short fixed options, one tap
                  instead of two-plus-a-scroll on mobile, and (the real gain) the
                  occupied slots stay visible instead of silently vanishing from a
                  collapsed menu.

                  role="group" + aria-pressed chips, not a radiogroup: Chip is the
                  app's established filter primitive (Address Book categories) and
                  matching it beats hand-rolling a roving-tabindex radiogroup for
                  five buttons. Field is bypassed on purpose: it renders
                  <label htmlFor>, which associates with nothing when the control is
                  a group of buttons, so the label is wired via aria-labelledby. */}
              <div className="mb-4">
                <span
                  id="tire-position-label"
                  className="mb-1 block text-sm font-medium text-text"
                >
                  {t('tireList.position')}
                </span>
                <div
                  role="group"
                  aria-labelledby="tire-position-label"
                  className="flex flex-wrap gap-2"
                >
                  {POSITIONS.map((p) => {
                    const locked = editingTireId !== null
                    const taken = takenPositions.has(p)
                    // Editing locks every chip; adding leaves occupied slots inert.
                    // Chip renders a plain <span> without onClick, so an unavailable
                    // slot is shown as state rather than as a dead-looking button.
                    const selectable = !locked && !taken
                    return (
                      <Chip
                        key={p}
                        tone={taken && !locked ? 'muted' : 'default'}
                        selected={form.position === p}
                        onClick={selectable ? () => setForm({ ...form, position: p }) : undefined}
                      >
                        {p}
                      </Chip>
                    )
                  })}
                  {/* Storage is a sixth destination, not a sixth corner. It is the
                      only way to enter a tire you own but are not fitting today,
                      which is every second seasonal set, and without it a tire
                      could only come into the app by being mounted onto a corner
                      it then had to be dismounted from. */}
                  <Chip
                    selected={form.position == null}
                    onClick={
                      editingTireId === null ? () => setForm({ ...form, position: null }) : undefined
                    }
                  >
                    {t('tireList.inStorage')}
                  </Chip>
                </div>
                {editingTireId === null && form.position == null && (
                  <p className="mt-1 text-sm text-text-mute">{t('tireList.storedHint')}</p>
                )}
              </div>
              {/* A tire added at a corner is born with a mount period, and a
                  period without an odometer is one whose distance can never be
                  worked out. Before v3.4.0 this form sent neither field, which is
                  why every tire added here read "add an odometer to this tire's
                  mount" with no control that could. Hidden on the storage branch
                  and on Edit: a stored tire has no mount to date, and an existing
                  tire's history is edited in its history drawer. */}
              {editingTireId === null && form.position != null && (
                <div className="mb-4">
                  <MountEventFields
                    vin={vin}
                    idPrefix="tire-mount"
                    dateLabel={t('tireList.mountedOn')}
                    date={form.mounted_on}
                    onDateChange={(next) => setForm({ ...form, mounted_on: next })}
                    odometerLabel={unitLabels(pu).odometer}
                    odometerHint={t('tireList.mountOdometerHint')}
                    odometer={form.mounted_odometer_km}
                    onOdometerChange={(next) => setForm({ ...form, mounted_odometer_km: next })}
                    tracksDistance={tracksDistance}
                    tracksHours={tracksHours}
                    hours={form.mounted_hours}
                    onHoursChange={(next) => setForm({ ...form, mounted_hours: next })}
                    hoursHint={tracksDistance ? undefined : t('tireList.mountHoursHint')}
                  />
                </div>
              )}
              {(editingTireId !== null || form.position == null) && (
                <div className="mb-4">
                  <Field
                    id="tire-storage"
                    label={t('tireList.storageLocation')}
                    hint={t('tireList.storageLocationHint')}
                  >
                    <Input
                      id="tire-storage"
                      value={form.storage_location}
                      onChange={(e) => setForm({ ...form, storage_location: e.target.value })}
                    />
                  </Field>
                </div>
              )}
              {/* Membership is editable on an EXISTING tire only, because
                  `POST /tires` forbids a `set_id`. Hidden rather than disabled
                  when adding: a control that cannot be used yet reads as broken,
                  and the tire can be filed the moment it is saved. */}
              {editingTireId !== null && tireSets.length > 0 && (
                <div className="mb-4">
                  <span id="tire-set-label" className="mb-1 block text-sm font-medium text-text">
                    {t('tireList.setLabel')}
                  </span>
                  <div role="group" aria-labelledby="tire-set-label" className="flex flex-wrap gap-2">
                    <Chip
                      selected={form.set_id == null}
                      onClick={() => setForm({ ...form, set_id: null })}
                    >
                      {t('tireList.setNone')}
                    </Chip>
                    {tireSets.map((tireSet) => (
                      <Chip
                        key={tireSet.id}
                        selected={form.set_id === tireSet.id}
                        onClick={() => setForm({ ...form, set_id: tireSet.id })}
                      >
                        {tireSet.name}
                      </Chip>
                    ))}
                  </div>
                </div>
              )}
              <div className="grid gap-3 sm:grid-cols-2">
                <Field id="tire-brand" label={t('tireList.brand')}>
                  <Input
                    id="tire-brand"
                    value={form.brand}
                    onChange={(e) => setForm({ ...form, brand: e.target.value })}
                  />
                </Field>
                <Field id="tire-model" label={t('tireList.model')}>
                  <Input
                    id="tire-model"
                    value={form.model_name}
                    onChange={(e) => setForm({ ...form, model_name: e.target.value })}
                  />
                </Field>
                <Field id="tire-size" label={t('tireList.size')}>
                  <Input
                    id="tire-size"
                    value={form.size}
                    onChange={(e) => setForm({ ...form, size: e.target.value })}
                  />
                </Field>
                <Field id="tire-dot" label={t('tireList.dot')}>
                  <Input
                    id="tire-dot"
                    value={form.dot_code}
                    onChange={(e) => setForm({ ...form, dot_code: e.target.value })}
                  />
                </Field>
                <TreadField
                  id="tire-tread"
                  label={unitLabels(pu).tread}
                  value={form.tread_depth_mm}
                  onChange={(next) => setForm((prev) => ({ ...prev, tread_depth_mm: next }))}
                  onConverted={() =>
                    setForm((prev) => ({
                      ...prev,
                      origins: { ...prev.origins, tread_depth_mm: seedUnitField(null, pu.tread) },
                    }))
                  }
                />
                <Field id="tire-pressure" label={unitLabels(pu).pressure}>
                  <Input
                    id="tire-pressure"
                    type="number"
                    step={pu.pressure.step}
                    value={form.pressure_kpa}
                    onChange={(e) => setForm({ ...form, pressure_kpa: e.target.value })}
                  />
                </Field>
                <TreadField
                  id="tire-min"
                  label={unitLabels(pu).minTread}
                  value={form.min_tread_mm}
                  onChange={(next) => setForm((prev) => ({ ...prev, min_tread_mm: next }))}
                  onConverted={() =>
                    setForm((prev) => ({
                      ...prev,
                      origins: { ...prev.origins, min_tread_mm: seedUnitField(null, pu.tread) },
                    }))
                  }
                  gaugeHint={false}
                />
              </div>
            </div>
          </Drawer>
        )}
      </PinnedUnits>

      <PinnedUnits open={readingTire !== null}>
        {(pu) => (
          <Drawer
            open={readingTire !== null}
            onClose={() => setReadingTireId(null)}
            title={t('tireList.readingTitle', {
              position: readingTire ? labelFor(readingTire.position) : '',
            })}
            icon={Gauge}
            width="xs"
            closeLabel={t('common:close')}
            footer={
              <>
                <Button variant="ghost" onClick={() => setReadingTireId(null)}>
                  {t('common:cancel')}
                </Button>
                <Button
                  variant="primary"
                  disabled={addReading.isPending}
                  onClick={() => readingTire && handleReading(readingTire.id, pu)}
                >
                  {t('common:save')}
                </Button>
              </>
            }
          >
            <div className="space-y-3">
              <Field id="reading-date" label={t('common:date')}>
                <Input
                  id="reading-date"
                  type="date"
                  value={readingForm.recorded_at}
                  onChange={(e) => setReadingForm({ ...readingForm, recorded_at: e.target.value })}
                />
              </Field>
              <TreadField
                id="reading-tread"
                label={unitLabels(pu).tread}
                value={readingForm.tread_depth_mm}
                onChange={(next) => setReadingForm((prev) => ({ ...prev, tread_depth_mm: next }))}
                onConverted={() =>
                  setReadingForm((prev) => ({
                    ...prev,
                    origins: { ...prev.origins, tread_depth_mm: seedUnitField(null, pu.tread) },
                  }))
                }
              />
              <Field id="reading-pressure" label={unitLabels(pu).pressure}>
                <Input
                  id="reading-pressure"
                  type="number"
                  step={pu.pressure.step}
                  value={readingForm.pressure_kpa}
                  onChange={(e) => setReadingForm({ ...readingForm, pressure_kpa: e.target.value })}
                />
              </Field>
              {tracksDistance && (
                <Field id="reading-odo" label={unitLabels(pu).odometer}>
                  <Input
                    id="reading-odo"
                    type="number"
                    step={pu.distance.step}
                    value={readingForm.odometer_km}
                    onChange={(e) => setReadingForm({ ...readingForm, odometer_km: e.target.value })}
                  />
                </Field>
              )}
              {tracksHours && (
                <Field id="reading-hours" label={t('common:engineHours')} unit="hr">
                  <Input
                    id="reading-hours"
                    type="number"
                    step="0.1"
                    value={readingForm.engine_hours}
                    onChange={(e) => setReadingForm({ ...readingForm, engine_hours: e.target.value })}
                  />
                </Field>
              )}
            </div>
          </Drawer>
        )}
      </PinnedUnits>

      <TireHistoryDrawer
        vin={vin}
        tire={historyTire}
        open={historyTire !== null}
        onClose={() => {
          setEditingPeriod(null)
          setEditingReading(null)
          setAddingPeriod(false)
          setHistoryTireId(null)
        }}
        onEditPeriod={setEditingPeriod}
        onEditReading={setEditingReading}
        onAddPeriod={() => setAddingPeriod(true)}
        labelFor={labelFor}
        tracksDistance={tracksDistance}
        tracksHours={tracksHours}
      />

      {historyTire && editingPeriod && (
        <MountPeriodEditor
          key={editingPeriod.id}
          vin={vin}
          tire={historyTire}
          period={editingPeriod}
          open
          onClose={() => setEditingPeriod(null)}
          labelFor={labelFor}
          tracksDistance={tracksDistance}
          tracksHours={tracksHours}
        />
      )}

      {historyTire && editingReading && (
        <ReadingEditor
          key={editingReading.id}
          vin={vin}
          tire={historyTire}
          reading={editingReading}
          open
          onClose={() => setEditingReading(null)}
          labelFor={labelFor}
          tracksDistance={tracksDistance}
          tracksHours={tracksHours}
        />
      )}

      {historyTire && addingPeriod && (
        <AddPastPeriodDrawer
          key={historyTire.id}
          vin={vin}
          tire={historyTire}
          open
          onClose={() => setAddingPeriod(false)}
          labelFor={labelFor}
          tracksDistance={tracksDistance}
          tracksHours={tracksHours}
        />
      )}
    </div>
  )
}
