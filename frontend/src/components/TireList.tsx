import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, Trash2, Gauge, AlertTriangle, Pencil, RotateCw } from 'lucide-react'
import { toast } from 'sonner'
import { formatDateForDisplay } from '../utils/dateUtils'
import type { MountedPosition, Tire, TirePosition, TireReading } from '../types/tire'
import {
  useTires,
  useCreateTire,
  useCreateAndMountTire,
  useDismountTire,
  useMountTire,
  useRetireTire,
  useRotateTires,
  useUpdateTire,
  useAddTireReading,
  useDeleteTire,
} from '../hooks/queries/useTires'
import { useUnitFormat } from '../hooks/useUnitFormat'
import {
  canonicalFromUnitField,
  seedUnitField,
  type UnitFieldOrigin,
} from '../utils/unitFormat'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { Button, IconButton, Card, Chip, Drawer, EmptyState, Input, Field, ListRow } from './ui'

const POSITIONS: MountedPosition[] = ['FL', 'FR', 'RL', 'RR', 'SPARE']

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
  brand: string
  model_name: string
  size: string
  dot_code: string
  tread_depth_mm: string
  pressure_kpa: string
  min_tread_mm: string
  notes: string
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

interface TireListProps {
  vin: string
}

export default function TireList({ vin }: TireListProps) {
  const { t } = useTranslation('vehicles')
  const { data, isLoading, error } = useTires(vin)
  const createTire = useCreateTire(vin)
  const createAndMount = useCreateAndMountTire(vin)
  const updateTire = useUpdateTire(vin)
  const mount = useMountTire(vin)
  const dismount = useDismountTire(vin)
  const retire = useRetireTire(vin)
  const rotate = useRotateTires(vin)
  const [retireTireId, setRetireTireId] = useState<number | null>(null)
  const [rotateOpen, setRotateOpen] = useState(false)
  const [rotatePattern, setRotatePattern] = useState<RotationPatternId>('forwardCross')
  const [mountTireId, setMountTireId] = useState<number | null>(null)
  const [dismountTireId, setDismountTireId] = useState<number | null>(null)
  const [mountPosition, setMountPosition] = useState<MountedPosition>('FL')
  /* Separate odometer state per drawer. They were briefly one field, which
   * meant a value typed into Mount and abandoned reappeared in Dismount --
   * and silently became that period's closing bound. A wrong odometer here is
   * not a cosmetic slip: it is the number the tire's whole distance is
   * computed from. */
  const [mountOdometer, setMountOdometer] = useState('')
  const [dismountOdometer, setDismountOdometer] = useState('')
  const [retireOdometer, setRetireOdometer] = useState('')
  const [rotateOdometer, setRotateOdometer] = useState('')
  const addReading = useAddTireReading(vin)
  const remove = useDeleteTire(vin)
  /* Every unit on this card and in both drawers resolves through `u`, per
   * quantity. The binary `system` is gone from the file: it is collapsed from
   * VOLUME (spec D8), so a custom user with litres and miles reads 'metric' and
   * a projection formatted from it would render kilometres directly above an
   * odometer field in miles. Two distances, one card, two units, which is the
   * disagreement D2 forbids and the one this file already carried for pressure.
   * Cost of joining: the projection reads "~621 mi" where it read "~621.37 mi",
   * because distance's declared precision is whole units. */
  const u = useUnitFormat()

  /** Tire API fields are `number | string | null`; the unit utils take `number | null`. */
  const num = (v: number | string | null | undefined): number | null =>
    v === null || v === undefined || v === '' ? null : Number(v)

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
  const seedTireForm = (tire: Tire | null, position: TirePosition): TireFormState => {
    const tread = seedUnitField(num(tire?.tread_depth_mm), u.tread)
    const minTread = seedUnitField(num(tire?.min_tread_mm) ?? DEFAULT_MIN_TREAD_MM, u.tread)
    const pressure = seedUnitField(num(tire?.pressure_kpa), u.pressure)
    return {
      position,
      brand: tire?.brand ?? '',
      model_name: tire?.model_name ?? '',
      size: tire?.size ?? '',
      dot_code: tire?.dot_code ?? '',
      tread_depth_mm: tread.display,
      pressure_kpa: pressure.display,
      min_tread_mm: minTread.display,
      notes: tire?.notes ?? '',
      origins: { tread_depth_mm: tread, min_tread_mm: minTread, pressure_kpa: pressure },
    }
  }

  const [formOpen, setFormOpen] = useState(false)
  const [editingTireId, setEditingTireId] = useState<number | null>(null)
  const [readingTireId, setReadingTireId] = useState<number | null>(null)
  const [historyTireId, setHistoryTireId] = useState<number | null>(null)
  const [form, setForm] = useState<TireFormState>(() => seedTireForm(null, 'FL'))
  const [readingForm, setReadingForm] = useState<ReadingFormState>(emptyReadingForm)

  const tires = data?.tires ?? []
  /* A stored tire occupies no corner, so its null position must not be
   * counted as taken -- otherwise dismounting a tire would make its old
   * corner permanently unavailable. */
  const takenPositions = new Set(
    tires.map((tire: Tire) => tire.position).filter((p): p is MountedPosition => p != null)
  )
  const freePositions = POSITIONS.filter((p) => !takenPositions.has(p))
  const mountedTires = tires.filter((tire: Tire) => tire.position != null)
  const storedTires = tires.filter((tire: Tire) => tire.position == null)

  /* Rotation is all-or-nothing server-side, so the button is only offered when
     every corner it would move is actually occupied. Sending a move for an
     empty corner is a 404 on the missing tire; sending a partial pattern is a
     409 on the corner held by a tire that is not in the rotation. Neither is
     something a user can act on, and both are avoidable by looking at the list
     that is already on screen. */
  const tireAt = (position: RotationCorner): Tire | undefined =>
    mountedTires.find((tire: Tire) => tire.position === position)
  const canRotate = ROTATION_CORNERS.every((corner) => tireAt(corner) !== undefined)

  /* Derived from the live list rather than held in state: a mutation refetches
   * and replaces every Tire object, so a captured one would go stale the moment
   * a reading is saved. */
  const readingTire = tires.find((tire: Tire) => tire.id === readingTireId) ?? null
  const historyTire = tires.find((tire: Tire) => tire.id === historyTireId) ?? null
  /* `readings` is optional on the generated response type (it carries a
   * server-side default), so it is normalised once here rather than
   * defended at each of the three places the drawer reads it. */
  const historyReadings: TireReading[] = historyTire?.readings ?? []

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
    const projection = (): string =>
      tire.projected_km_remaining != null
        ? `~${u.distance.format(num(tire.projected_km_remaining))}` +
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
        return t('tireList.wear.needsReadingOdometer')
      case 'tread_not_decreasing':
        return t('tireList.wear.treadNotDecreasing')
      case 'no_distance_on_tire':
      case 'unverified_mount_history':
        return t('tireList.wear.needsMountOdometer')
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
    switch (tire.distance_status) {
      case 'complete':
        return tire.distance_km != null ? u.distance.format(num(tire.distance_km)) : '—'
      case 'incomplete':
        return tire.known_distance_km != null
          ? t('tireList.distance.since', {
              distance: u.distance.format(num(tire.known_distance_km)),
              date: tire.known_distance_since
                ? formatDateForDisplay(tire.known_distance_since)
                : '',
            })
          : t('tireList.distance.nothingBounded')
      case 'nothing_bounded':
        return t('tireList.distance.nothingBounded')
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

  /* One key per field, interpolated with the resolved unit, replacing the pairs
   * of unit-specific keys a ternary used to choose between. `odometerMi` and
   * `odometerKm` could only ever name two of the vocabulary's units. */
  const pressureLabel = t('tireList.pressureWithUnit', { unit: u.pressure.label })
  const odometerLabel = t('tireList.odometerWithUnit', { unit: u.distance.label })
  const treadLabel = t('tireList.treadWithUnit', { unit: u.tread.label })
  const minTreadLabel = t('tireList.minTreadWithUnit', { unit: u.tread.label })

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
      recorded_at: new Date().toISOString().slice(0, 10),
      odometer_km: '',
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

  const handleSave = () => {
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
      tread_depth_mm: canonicalFromUnitField(
        form.tread_depth_mm,
        form.origins.tread_depth_mm,
        u.tread
      ),
      pressure_kpa: canonicalFromUnitField(
        form.pressure_kpa,
        form.origins.pressure_kpa,
        u.pressure
      ),
      min_tread_mm:
        canonicalFromUnitField(form.min_tread_mm, form.origins.min_tread_mm, u.tread) ??
        DEFAULT_MIN_TREAD_MM,
      notes: form.notes || null,
    }

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
      updateTire.mutate({ tireId: editingTireId, ...shared }, handlers)
      return
    }
    // `POST /tires` forbids a `position` key outright (extra="forbid"), so the
    // two creates cannot share one payload: passing `position: null` to it is a
    // 422, not a null.
    if (form.position == null) {
      createTire.mutate({ vin, ...shared }, handlers)
      return
    }
    createAndMount.mutate({ vin, position: form.position, ...shared }, handlers)
  }

  /**
   * Retire the tire the retire drawer is open on.
   *
   * Separate from `handleDelete` on purpose, and it is the one users should
   * reach for: retiring keeps every reading and every mount period, which is
   * the history this release exists to make worth collecting. Delete stays in
   * the edit drawer for a tire entered by mistake.
   */
  const handleRetire = () => {
    if (retireTireId === null) return
    retire.mutate(
      {
        tireId: retireTireId,
        dismounted_odometer_km: canonicalFromUnitField(
          retireOdometer,
          { canonical: null, display: '' },
          u.distance
        ),
      },
      {
        onSuccess: () => {
          toast.success(t('tireList.retired'))
          setRetireTireId(null)
          setRetireOdometer('')
        },
        onError: (err: unknown) =>
          toast.error(getActionErrorMessage(err, t('tireList.retireAction'))),
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
  const handleRotate = () => {
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
        odometer_km: canonicalFromUnitField(
          rotateOdometer,
          { canonical: null, display: '' },
          u.distance
        ),
      },
      {
        onSuccess: () => {
          toast.success(t('tireList.rotated'))
          setRotateOpen(false)
          setRotateOdometer('')
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

  const handleReading = (tireId: number) => {
    /* Resolved before the guard so the refusal and the payload come from one
     * computation rather than two. It is NOT a behaviour change against the old
     * truthiness check: `<Input type="number">` hands back an empty string for
     * text that is not a number, so `null` here means "blank" and nothing else
     * reaches it. */
    const tread = canonicalFromUnitField(
      readingForm.tread_depth_mm,
      readingForm.origins.tread_depth_mm,
      u.tread
    )
    /* Hoisted out of the payload for the same reason as tread: the guard below
     * and the body must be one computation, not two that can disagree. */
    const pressure = canonicalFromUnitField(
      readingForm.pressure_kpa,
      readingForm.origins.pressure_kpa,
      u.pressure
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
        odometer_km: canonicalFromUnitField(
          readingForm.odometer_km,
          readingForm.origins.odometer_km,
          u.distance
        ),
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
          {/* Vehicle-level, so it sits in the header rather than on a card:
              a rotation is one action on four tires, and putting it on each
              card would ask which of four identical buttons to press. */}
          <Button
            variant="secondary"
            size="sm"
            icon={RotateCw}
            disabled={!canRotate || rotate.isPending}
            title={canRotate ? undefined : t('tireList.rotateNeedsFourCorners')}
            onClick={() => setRotateOpen(true)}
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
          <Card key={tire.id} padding="sm" className="relative space-y-2">
            {/* A full-bleed sibling button, which is a fourth clickable-card
                shape in this codebase and deliberately so. `Card interactive`
                renders the Card itself as a <button>, and the container
                role="button" that ExternalVehicleCard and FamilyMemberCard use
                is the same shape by another route: both would put Edit and Log
                Reading INSIDE the click target, which is interactive content
                nested in a button and needs stopPropagation on each child to
                behave. Neither of those two cards has that problem because
                neither encloses a control. A sibling cannot receive their
                clicks at all, so the isolation is structural rather than
                handled. The overlay is a real button so the card is reachable
                by keyboard; the two controls sit above it on `z-10`. */}
            <button
              type="button"
              className="ui-focus-ring absolute inset-0 rounded-card"
              aria-label={t('tireList.historyOpen', {
                position: labelFor(tire.position),
              })}
              onClick={() => setHistoryTireId(tire.id)}
            />
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
                className="relative z-10"
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
              <dt className="text-text-mute">{t('tireList.distanceOnTire')}</dt>
              <dd className="font-mono text-xs">{distanceSummary(tire)}</dd>
            </dl>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="secondary"
                className="relative z-10"
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
                className="relative z-10"
                disabled={dismount.isPending}
                onClick={() => setDismountTireId(tire.id)}
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
                className="relative z-10"
                disabled={retire.isPending}
                onClick={() => setRetireTireId(tire.id)}
              >
                {t('tireList.retire')}
              </Button>
            </div>
          </Card>
        ))}
      </div>

      {storedTires.length > 0 && (
        <>
          <h3 className="text-sm font-semibold text-text-mute">{t('tireList.inStorageHeading')}</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            {storedTires.map((tire: Tire) => (
              <Card key={tire.id} padding="sm" className="space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="font-semibold">{labelFor(tire.position)}</div>
                    <div className="text-sm text-text-mute">
                      {[tire.brand, tire.model_name, tire.size].filter(Boolean).join(' · ') || '—'}
                    </div>
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
                  <dt className="text-text-mute">{t('tireList.distanceOnTire')}</dt>
                  <dd className="font-mono">{distanceSummary(tire)}</dd>
                </dl>
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={freePositions.length === 0 || mount.isPending}
                    onClick={() => setMountTireId(tire.id)}
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
                    onClick={() => setRetireTireId(tire.id)}
                  >
                    {t('tireList.retire')}
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
                if (mountTireId === null) return
                mount.mutate(
                  {
                    tireId: mountTireId,
                    position: mountPosition,
                    mounted_odometer_km: canonicalFromUnitField(
                      mountOdometer,
                      { canonical: null, display: '' },
                      u.distance
                    ),
                  },
                  {
                    onSuccess: () => {
                      toast.success(t('tireList.mounted'))
                      setMountTireId(null)
                      setMountOdometer('')
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
          <Field
            id="mount-odometer"
            label={odometerLabel}
            hint={t('tireList.mountOdometerHint')}
          >
            <Input
              id="mount-odometer"
              type="number"
              step={u.distance.step}
              value={mountOdometer}
              onChange={(e) => setMountOdometer(e.target.value)}
            />
          </Field>
        </div>
      </Drawer>

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
                if (dismountTireId === null) return
                dismount.mutate(
                  {
                    tireId: dismountTireId,
                    dismounted_odometer_km: canonicalFromUnitField(
                      dismountOdometer,
                      { canonical: null, display: '' },
                      u.distance
                    ),
                  },
                  {
                    onSuccess: () => {
                      toast.success(t('tireList.dismounted'))
                      setDismountTireId(null)
                      setDismountOdometer('')
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
          <Field
            id="dismount-odometer"
            label={odometerLabel}
            hint={t('tireList.mountOdometerHint')}
          >
            <Input
              id="dismount-odometer"
              type="number"
              step={u.distance.step}
              value={dismountOdometer}
              onChange={(e) => setDismountOdometer(e.target.value)}
            />
          </Field>
        </div>
      </Drawer>

      {/* Retire is its own drawer for the same reason dismount is: it closes a
          mount period, and a period closed without an odometer is one this
          tire's distance can never be computed from. The hint is the whole
          point of the drawer, though -- it is the only place the app says out
          loud that retiring and deleting are different. */}
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
            <Button variant="primary" disabled={retire.isPending} onClick={handleRetire}>
              {t('tireList.retire')}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <p className="text-sm text-text-mute">{t('tireList.retireHint')}</p>
          <Field id="retire-odometer" label={odometerLabel} hint={t('tireList.mountOdometerHint')}>
            <Input
              id="retire-odometer"
              type="number"
              step={u.distance.step}
              value={retireOdometer}
              onChange={(e) => setRetireOdometer(e.target.value)}
            />
          </Field>
        </div>
      </Drawer>

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
              onClick={handleRotate}
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
          <Field
            id="rotate-odometer"
            label={odometerLabel}
            hint={t('tireList.rotateOdometerHint')}
          >
            <Input
              id="rotate-odometer"
              type="number"
              step={u.distance.step}
              value={rotateOdometer}
              onChange={(e) => setRotateOdometer(e.target.value)}
            />
          </Field>
        </div>
      </Drawer>

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
            <Button variant="primary" onClick={handleSave} disabled={createAndMount.isPending || updateTire.isPending}>
              {t('common:save')}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {/* Push toggles rather than a select: five short fixed options, one tap
              instead of two-plus-a-scroll on mobile, and — the real gain — the
              occupied slots stay visible instead of silently vanishing from a
              collapsed menu.

              role="group" + aria-pressed chips, not a radiogroup: Chip is the
              app's established filter primitive (Address Book categories) and
              matching it beats hand-rolling a roving-tabindex radiogroup for
              five buttons. Field is bypassed on purpose — it renders
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
            <Field id="tire-tread" label={treadLabel}>
              <Input
                id="tire-tread"
                type="number"
                step={u.tread.step}
                value={form.tread_depth_mm}
                onChange={(e) => setForm({ ...form, tread_depth_mm: e.target.value })}
              />
            </Field>
            <Field id="tire-pressure" label={pressureLabel}>
              <Input
                id="tire-pressure"
                type="number"
                step={u.pressure.step}
                value={form.pressure_kpa}
                onChange={(e) => setForm({ ...form, pressure_kpa: e.target.value })}
              />
            </Field>
            <Field id="tire-min" label={minTreadLabel}>
              <Input
                id="tire-min"
                type="number"
                step={u.tread.step}
                value={form.min_tread_mm}
                onChange={(e) => setForm({ ...form, min_tread_mm: e.target.value })}
              />
            </Field>
          </div>
        </div>
      </Drawer>

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
              onClick={() => readingTire && handleReading(readingTire.id)}
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
          <Field id="reading-tread" label={treadLabel}>
            <Input
              id="reading-tread"
              type="number"
              step={u.tread.step}
              value={readingForm.tread_depth_mm}
              onChange={(e) => setReadingForm({ ...readingForm, tread_depth_mm: e.target.value })}
            />
          </Field>
          <Field id="reading-pressure" label={pressureLabel}>
            <Input
              id="reading-pressure"
              type="number"
              step={u.pressure.step}
              value={readingForm.pressure_kpa}
              onChange={(e) => setReadingForm({ ...readingForm, pressure_kpa: e.target.value })}
            />
          </Field>
          <Field id="reading-odo" label={odometerLabel}>
            <Input
              id="reading-odo"
              type="number"
              step={u.distance.step}
              value={readingForm.odometer_km}
              onChange={(e) => setReadingForm({ ...readingForm, odometer_km: e.target.value })}
            />
          </Field>
        </div>
      </Drawer>

      <Drawer
        open={historyTire !== null}
        onClose={() => setHistoryTireId(null)}
        title={t('tireList.historyTitle', {
          position: historyTire ? labelFor(historyTire.position) : '',
        })}
        icon={Gauge}
        width="sm"
        closeLabel={t('common:close')}
      >
        {/* `readings` arrives newest-first: TireService sorts descending by
            recorded_at before building the response, and the projection reads
            [0] and [1] as the two most recent. Re-sorting here would be a
            second, drifting source of truth for the same order. */}
        {historyReadings.length > 0 ? (
          <ul className="space-y-2">
            {historyReadings.map((reading: TireReading) => (
              <li key={reading.id} className="space-y-1 rounded-card border border-border p-3">
                <div className="font-semibold">{formatDateForDisplay(reading.recorded_at)}</div>
                {/* Every value through the same adapters the card uses, so a
                    history row can never disagree with the card above it. The
                    ternaries stay spelled out per row rather than folding into
                    a shared cell() helper: validate-units.ts matches lexical
                    expression shapes, and a helper that converts INTERNALLY is
                    exactly the form its manifest notes it cannot see. */}
                <ListRow
                  label={t('tireList.tread')}
                  value={
                    reading.tread_depth_mm != null
                      ? u.tread.format(num(reading.tread_depth_mm))
                      : '—'
                  }
                />
                <ListRow
                  label={t('tireList.pressure')}
                  value={
                    reading.pressure_kpa != null
                      ? u.pressure.format(num(reading.pressure_kpa))
                      : '—'
                  }
                />
                <ListRow
                  label={t('tireList.odometer')}
                  value={
                    reading.odometer_km != null
                      ? u.distance.format(num(reading.odometer_km))
                      : '—'
                  }
                />
                {reading.notes ? (
                  <p className="text-sm text-text-mute">{reading.notes}</p>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            icon={Gauge}
            size="sm"
            title={t('tireList.historyEmpty')}
            description={t('tireList.historyEmptyHint')}
          />
        )}
      </Drawer>
    </div>
  )
}
