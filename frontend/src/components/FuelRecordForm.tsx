import { useMemo, useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Save, ChevronDown, ChevronUp, Sparkles } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import AddressBookAutocomplete from './AddressBookAutocomplete'
import AddressBookQuickAddModal from './AddressBookQuickAddModal'
import type { FuelRecord, FuelRecordCreate, FuelRecordUpdate } from '../types/fuel'
import type { Vehicle } from '../types/vehicle'
import type { UnitSet } from '../types/units'
import type { AddressBookEntry } from '../types/addressBook'
import { makeFuelRecordSchema, type FuelRecordFormData } from '../schemas/fuel'
import {
  FUEL_TYPE_VALUES,
  PAYMENT_METHOD_VALUES,
  TRIP_TYPE_VALUES,
  isDieselFuelType,
  isFuelType,
} from '../constants/fuel'
import { FormError } from './FormError'
import api from '../services/api'
import { useCreateFuelRecord, useUpdateFuelRecord, useParseFuelReceipt, type FuelReceiptDraft } from '../hooks/queries/useFuelRecords'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { useAuth } from '../contexts/AuthContext'
import { UnitFormatter } from '../utils/units'
import {
  canonicalFromPriceField,
  readNumber,
  seedPriceField,
  toLitersWirePrecision,
  type PriceFieldOrigin,
} from '../utils/decimalSafe'
import { useUnitFormat } from '../hooks/useUnitFormat'
import {
  canonicalFromUnitField,
  seedUnitField,
  NOT_AVAILABLE,
  type QuantityFormat,
  type UnitFieldOrigin,
} from '../utils/unitFormat'
import { useOnUserEdit } from '../hooks/useOnUserEdit'
import { getUsageTracking } from '../utils/usageTracking'
import CurrencyInputPrefix from './common/CurrencyInputPrefix'
import { Button, Field, Input, NumberInput, Select, Textarea, Checkbox, registerDecimal } from './ui'
import { formatDateForInput } from '../utils/dateUtils'
import TimeInput24, { normalizeTime, formatTimeForInput } from './common/TimeInput24'
import { useTimeFormat } from '../hooks/useTimeFormat'
import { applyServerErrors } from '../hooks/useApiFormErrors'
import { getActionErrorMessage } from '../utils/httpErrorHandler'

const MORE_DETAILS_KEY = 'fuel_form:more_details_expanded'

/**
 * The volume and price EXAMPLES each volume token gets, as ONE physical fill.
 *
 * ★ Keyed by the resolved token rather than branched on `units.volume === 'L'`,
 * which is the correction ruling R4 hands this task along with the two fields'
 * round trip. The branch named the right QUANTITY and still could not name the
 * right UNIT: `gal_uk` took the else arm, so a UK account read a US-gallon
 * example (12.500 gal at $3.499) beside a field labelled with its own gallon,
 * which is 20 percent larger. `Record` over the token means a volume unit added
 * later cannot compile without its own example.
 *
 * All three describe the same 47.318 L at $0.924/L: 47.318 / 3.78541 = 12.500
 * US gallons at 0.924 x 3.78541 = $3.498, and / 4.54609 = 10.409 imperial
 * gallons at 0.924 x 4.54609 = $4.200. They are placeholders, not converted
 * quantities (ruling R5's exempt class), which is why they are written out
 * rather than computed. PropaneRecordForm and VehicleEditDrawer carry sibling
 * tables for their own examples; one shared table would have to describe a fuel
 * fill, a propane bottle and a DEF tank at once.
 */
const VOLUME_EXAMPLES: Readonly<Record<UnitSet['volume'], { volume: string; price: string }>> = {
  L: { volume: '47.318', price: '0.924' },
  gal_us: { volume: '12.500', price: '3.498' },
  gal_uk: { volume: '10.409', price: '4.200' },
}

/** Split a "YYYY-MM-DDTHH:mm" (or naive ISO) value into date + 24h time parts. */
export function splitFilledAt(val: string | null | undefined): { date: string; time: string } {
  if (!val) return { date: '', time: '' }
  const trimmed = val.slice(0, 16) // drop seconds/offset
  const [date = '', time = ''] = trimmed.split('T')
  return { date, time: time.slice(0, 5) }
}

/** Recombine date + 24h time into the submit string; empty unless both present. */
export function joinFilledAt(date: string, time: string): string {
  if (!date || !time) return ''
  return `${date}T${time}`
}

/**
 * The fields this form CONSUMES from `/fuel/obc-suggestion`, not the wire shape.
 *
 * `distance_km` was declared here and never read; the response still carries it
 * and `ObcSuggestionResponse` in the generated types is where the wire contract
 * lives. A field nothing reads is a claim that something does.
 */
interface ObcSuggestion {
  session_id: number
  ended_at: string
  obc_l_per_100km: number | string | null
  obc_avg_speed_kmh: number | string | null
  obc_trip_duration_s: number | null
}

interface FuelRecordFormProps {
  vin: string
  record?: FuelRecord
  onClose: () => void
  onSuccess: () => void
}

export default function FuelRecordForm({ vin, record, onClose, onSuccess }: FuelRecordFormProps) {
  const { t } = useTranslation('forms')
  const isEdit = !!record
  const [error, setError] = useState<string | null>(null)
  const createMutation = useCreateFuelRecord(vin)
  const updateMutation = useUpdateFuelRecord(vin)
  const parseReceiptMutation = useParseFuelReceipt(vin)
  const [vehicleFuelType, setVehicleFuelType] = useState<string>('')
  const [vehicleFuelTypeSecondary, setVehicleFuelTypeSecondary] = useState<string>('')
  // Task 13 — which usage dimension(s) this vehicle tracks, driving the
  // odometer vs. engine-hours field visibility below. Defaults mirror
  // getUsageTracking's own distance-primary default so the form doesn't
  // flash the wrong field before the vehicle fetch resolves.
  const [vehicleUsageUnit, setVehicleUsageUnit] = useState<string>('distance')
  const [vehicleSecondaryUsageEnabled, setVehicleSecondaryUsageEnabled] = useState<boolean>(false)
  const { units } = useUnitPreference()
  // Per-quantity adapters. The binary `system` is D8-collapsed from VOLUME, so
  // it cannot answer for the odometer or the outside temperature: a client
  // resolving `{volume: 'L', distance: 'mi'}` reads 'metric' out of it for a
  // distance they chose in miles, and the field beside their litres was then
  // seeded, labelled and STORED as kilometres.
  const u = useUnitFormat()
  const { timeFormat } = useTimeFormat()
  const { user } = useAuth()

  // Initial render of the "More details" panel state — sticky per-user via
  // localStorage so users who use it always get it expanded.
  const [moreDetailsOpen, setMoreDetailsOpen] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false
    try {
      return window.localStorage.getItem(MORE_DETAILS_KEY) === '1'
    } catch {
      return false
    }
  })

  const toggleMoreDetails = () => {
    setMoreDetailsOpen((prev) => {
      const next = !prev
      try {
        window.localStorage.setItem(MORE_DETAILS_KEY, next ? '1' : '0')
      } catch {
        // ignore
      }
      return next
    })
  }

  // OBC suggestion state — populated when the user clicks "Auto-fill from
  // last drive" and an OBC value can be matched to filled_at.
  const [obcSuggestion, setObcSuggestion] = useState<ObcSuggestion | null>(null)
  const [obcLoading, setObcLoading] = useState(false)
  const [obcMessage, setObcMessage] = useState<string | null>(null)
  const [hasLinkedTrailers, setHasLinkedTrailers] = useState(false)
  const [llmReceiptEnabled, setLlmReceiptEnabled] = useState(false)
  const [receiptDraft, setReceiptDraft] = useState<FuelReceiptDraft | null>(null)
  const [receiptMessage, setReceiptMessage] = useState<string | null>(null)
  const [receiptText, setReceiptText] = useState('')
  const receiptFileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (record) return
    let cancelled = false
    void import('../services/vehicleService').then(({ default: vehicleService }) =>
      vehicleService
        .listTowedTrailers(vin)
        .then((list) => {
          if (!cancelled) setHasLinkedTrailers(list.length > 0)
        })
        .catch(() => {
          if (!cancelled) setHasLinkedTrailers(false)
        }),
    )
    return () => {
      cancelled = true
    }
  }, [vin, record])

  useEffect(() => {
    if (record) return
    let cancelled = false
    // /settings is admin-only, so reading the flag from there hid the receipt
    // panel from every non-admin (the 403 lands in the catch below and sets the
    // flag false). The key is on the public whitelist instead.
    void api
      .get('/settings/public')
      .then((response) => {
        const settings: { key: string; value: string | null }[] =
          response.data?.settings ?? []
        const enabled = settings.find((s) => s.key === 'llm_receipt_parse_enabled')
        if (!cancelled) {
          setLlmReceiptEnabled((enabled?.value || 'false').toLowerCase() === 'true')
        }
      })
      .catch(() => {
        if (!cancelled) setLlmReceiptEnabled(false)
      })
    return () => {
      cancelled = true
    }
  }, [record])

  // `labelKey` is translated at render time; the fraction labels are numerals
  // and stay as-is (they are not prose).
  const FILL_LEVEL_PRESETS = [
    { label: null, labelKey: 'fuelRecordForm.fillLevelFull', value: 100 },
    { label: '3/4', labelKey: null, value: 75 },
    { label: '1/2', labelKey: null, value: 50 },
    { label: '1/4', labelKey: null, value: 25 },
  ] as const

  // Zod bakes its messages in at construction, so the schema is rebuilt when
  // the language changes. Only the resolver depends on it — no fetch, no
  // reset() — so a rebuild can't discard what the user typed.
  const schema = useMemo(() => makeFuelRecordSchema(t), [t])

  /**
   * The canonical origin of each unit-bearing field this form seeds.
   *
   * A display unit that only formats corrupts data (binding decision D2): a
   * stored 72420.3 km reads as 45000 mi, and 45000 mi converts back to
   * 72420.3 km only by luck of the rounding. `seedUnitField` records what each
   * field was populated from so `canonicalFromUnitField` can hand that value
   * straight back when the field still reads what it was seeded with, and a
   * user who opens a record to change the notes does not rewrite the odometer.
   *
   * Seeded through a lazy `useState` for the same reason `defaultValues` is
   * computed once: an origin that moved on re-render would stop being an
   * origin.
   *
   * ★ VOLUME IS HERE NOW, and the comment it replaces said the two were
   * "deliberately NOT here; they are react-hook-form number fields whose own
   * round trip Task 2 already made exact". It was not exact. Task 2 put both
   * on the resolved `UnitSet`, which settled WHICH gallon they convert
   * through and left the round trip reconverting a rounded display: a stored
   * 37.9 L seeded a US-gallon field as 10.01 and came back 37.892 on a save
   * that touched nothing. Ruling R4 gives that shift to plan 3b task 7.
   * PRICE is one field over, in `priceOrigin`, because a price origin also
   * carries the basis its number was read under and this record's shape
   * cannot express that.
   *
   * ★ The setter has exactly one caller, `acceptUnitField`, which is where a
   * canonical value arriving after mount gets seeded; see its docstring for
   * why that is a second seed rather than an edit. Nothing else moves an
   * origin, so the six still change only when the value behind them does.
   *
   * ★ The spelling gap this used to rest a precision pin on is now closed in
   * the helper. `canonicalFromUnitField` decided "the user did not touch this"
   * by string comparison against `toInputValue`, i.e. `toFixed(precision)`.
   * The temperature field HOLDS that string; the odometer is a
   * react-hook-form NUMBER, so its submit can only offer `String(number)`, and
   * the two spellings agreed only because `mi` and `km` carry no decimals.
   * Phase 3b task 3 hit the same gap on propane's two-decimal mass field,
   * where the sidestep does not reach, and made the helper compare the
   * QUANTITY instead. The `UNIT_ADAPTERS.mi.precision` pin in
   * FuelRecordForm.mixedUnits.test.tsx is kept as documentation of the
   * displayed precision, not as the thing holding this together.
   */
  const [unitOrigins, setUnitOrigins] = useState<{
    odometer_km: UnitFieldOrigin
    outside_temp_c: UnitFieldOrigin
    obc_l_per_100km: UnitFieldOrigin
    obc_avg_speed_kmh: UnitFieldOrigin
    liters: UnitFieldOrigin
    propane_liters: UnitFieldOrigin
  }>(() => ({
    odometer_km: seedUnitField(readNumber(record?.odometer_km), u.distance),
    outside_temp_c: seedUnitField(readNumber(record?.outside_temp_c), u.temperature),
    obc_l_per_100km: seedUnitField(readNumber(record?.obc_l_per_100km), u.consumption),
    obc_avg_speed_kmh: seedUnitField(readNumber(record?.obc_avg_speed_kmh), u.speed),
    liters: seedUnitField(readNumber(record?.liters), u.volume),
    propane_liters: seedUnitField(readNumber(record?.propane_liters), u.volume),
  }))

  /**
   * The price field's canonical origin, and the basis its number was read as.
   *
   * ★ SEPARATE FROM `unitOrigins` BECAUSE A PRICE ORIGIN IS NOT A QUANTITY
   * ORIGIN. `price_basis` is a `<select>` on this very form, so a user can move
   * the denominator from `per_volume` to `per_weight` without touching the
   * number, and the same characters then mean a different quantity.
   * `canonicalFromPriceField` compares the basis as well as the value, which is
   * what stops an untouched-looking field from storing a $/gal figure as $/lb.
   */
  const [priceOrigin, setPriceOrigin] = useState<PriceFieldOrigin>(() =>
    seedPriceField(record?.price_per_unit, units, record?.price_basis)
  )

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    setValue,
    watch,
    getValues,
    subscribe,
    setError: setFieldError,
  } = useForm<FuelRecordFormData>({
    resolver: zodResolver(schema) as Resolver<FuelRecordFormData>,
    defaultValues: {
      date: formatDateForInput(record?.date),
      // Immediately overwritten by the sub-field mirror effect below once
      // filledTime seeds on mount — this is just the RHF key placeholder.
      filled_at: '',
      // Seeded in `units.distance`, and the submit converts back through the
      // SAME adapter. `readNumber('')` is undefined, which is the empty field.
      odometer_km: readNumber(unitOrigins.odometer_km.display),
      // Engine hours are dimensionless — no unit conversion regardless of system.
      engine_hours: readNumber(record?.engine_hours),
      // Seeded in `units.volume`, and the submit reads both back through the
      // SAME origins: a seed on one gallon and a submit on another rewrites a
      // record the user only opened (defect L1), and a submit that reconverts
      // its own seed's rounding does it again by a smaller amount (R4).
      liters: readNumber(unitOrigins.liters.display),
      propane_liters: readNumber(unitOrigins.propane_liters.display),
      kwh: readNumber(record?.kwh),
      soc_start_pct: readNumber((record as { soc_start_pct?: number | string | null })?.soc_start_pct),
      soc_end_pct: readNumber((record as { soc_end_pct?: number | string | null })?.soc_end_pct),
      charge_level: (record as { charge_level?: 'L1' | 'L2' | 'DCFC' | null })?.charge_level ?? undefined,
      charge_location: (record as { charge_location?: 'home' | 'public' | null })?.charge_location ?? undefined,
      battery_soh_pct: readNumber((record as { battery_soh_pct?: number | string | null })?.battery_soh_pct),
      price_per_unit: readNumber(priceOrigin.display),
      price_basis: (record?.price_basis as 'per_volume' | 'per_weight' | 'per_kwh' | 'per_tank' | undefined) ?? undefined,
      cost: readNumber(record?.cost),
      rebate: readNumber(record?.rebate),
      fuel_type_used: record?.fuel_type_used as FuelRecordFormData['fuel_type_used'] ?? undefined,
      is_full_tank: record?.is_full_tank ?? true,
      missed_fillup: record?.missed_fillup ?? false,
      is_hauling: record?.is_hauling ?? false,
      notes: record?.notes || '',
      // Issue #69 — pre-fill from user defaults on create only
      payment_method: record
        ? (record.payment_method as FuelRecordFormData['payment_method'] ?? undefined)
        : (user?.default_payment_method as FuelRecordFormData['payment_method'] ?? undefined),
      trip_type: record
        ? (record.trip_type as FuelRecordFormData['trip_type'] ?? undefined)
        : (user?.default_trip_type as FuelRecordFormData['trip_type'] ?? undefined),
      station_address_book_id: readNumber(record?.station_address_book_id),
      station_name_freetext: record?.station_name_freetext || '',
      // A station with freetext and no FK IS a one-time visit — the flag isn't
      // stored, it's implied by that shape. Seeding a flat `false` left the box
      // unchecked on such a record, so editing it promoted a stop the user had
      // deliberately kept out of the address book (issue #108).
      one_time_visit: !record?.station_address_book_id && !!record?.station_name_freetext,
      driver_user_id: readNumber(record?.driver_user_id),
      driver_name_freetext: record?.driver_name_freetext || '',
      outside_temp_c: unitOrigins.outside_temp_c.canonical ?? undefined,
      // Seeded in `units.consumption` and `units.speed`, and the submit
      // converts back through the SAME adapters. Storage is L/100km and km/h;
      // an MPH client reading 100 km/h as 60 and having 60 stored back was a
      // 38% error in a field nothing on this screen even hinted was metric.
      obc_l_per_100km: readNumber(unitOrigins.obc_l_per_100km.display),
      obc_avg_speed_kmh: readNumber(unitOrigins.obc_avg_speed_kmh.display),
      // Phase 3.7 — field accepts HH:MM or HH:MM:SS strings as well as
      // raw seconds; default to the stored canonical seconds as a
      // string so users can either edit verbatim or paste a fresh
      // OBC reading. Empty string for new records.
      obc_trip_duration_s:
        record?.obc_trip_duration_s != null
          ? String(record.obc_trip_duration_s)
          : '',
    },
  })

  // Fill-up time is entered as a time-of-day; the date comes from the record's
  // own `date` field (issue #109 follow-up). Seed the display string from the
  // stored canonical time, in the user's format.
  const [filledTime, setFilledTime] = useState(() =>
    formatTimeForInput(splitFilledAt(record?.filled_at).time, timeFormat),
  )
  const recordDate = watch('date')

  // Mirror the recombined value into RHF so watchers (e.g. OBC suggestion) see
  // it live. NOT the source of truth for submission — onSubmit recomputes.
  useEffect(() => {
    setValue('filled_at', joinFilledAt(recordDate, normalizeTime(filledTime, timeFormat)), {
      shouldValidate: false,
    })
  }, [recordDate, filledTime, timeFormat, setValue])

  // Fetch vehicle data to get fuel_type
  useEffect(() => {
    const fetchVehicle = async () => {
      try {
        const response = await api.get(`/vehicles/${vin}`)
        const vehicleData: Vehicle & { fuel_type_secondary?: string | null } = response.data

        // Store fuel_type for conditional rendering
        setVehicleFuelType(vehicleData.fuel_type || '')
        setVehicleFuelTypeSecondary(vehicleData.fuel_type_secondary || '')
        // Task 13 — usage-dimension fields, for odometer/engine-hours field visibility.
        setVehicleUsageUnit(vehicleData.usage_unit || 'distance')
        setVehicleSecondaryUsageEnabled(!!vehicleData.secondary_usage_enabled)

        // Auto-populate the fuel dispensed from the vehicle's primary fuel
        // when creating. The select below is only rendered for multi-fuel
        // vehicles, so for everyone else this is what puts a fuel type on the
        // record at all. Guarded on the enum: a vehicle carrying a legacy
        // off-vocabulary value would otherwise fail the form's own validation.
        if (!record && vehicleData.fuel_type) {
          const primary = vehicleData.fuel_type as FuelRecordFormData['fuel_type_used']
          if (FUEL_TYPE_VALUES.includes(primary as (typeof FUEL_TYPE_VALUES)[number])) {
            setValue('fuel_type_used', primary)
          }
        }
      } catch {
        // Silent fail - non-critical auto-populate
      }
    }
    fetchVehicle()
  }, [vin, record, setValue])

  // Station autocomplete state — drives both the textbox and the FK pick.
  // Seed from the resolved `station_name`, not the freetext: picking an
  // address-book station stores the FK and leaves freetext null, so seeding
  // from freetext showed a blank box on edit and looked like the station had
  // never saved (issue #108). `station_name` covers both storage shapes.
  const [stationText, setStationText] = useState<string>(record?.station_name || '')
  // The saved station this fill-up points at — from the record, or picked this
  // session. It is the baseline the typed text is compared against, so it holds
  // steady while the text diverges; `station_address_book_id` in form state is
  // the live answer to "still linked?" and is what actually gets submitted.
  const [linkedStation, setLinkedStation] = useState<{ id: number; name: string } | null>(
    record?.station_address_book_id && record?.station_name
      ? { id: record.station_address_book_id, name: record.station_name }
      : null,
  )
  const hasLinkedStation = !!watch('station_address_book_id')
  // Phase 3.4 quick-add modal — opened from the autocomplete's "+ Add"
  // footer when the user types a station name not in the address book.
  const [quickAddOpen, setQuickAddOpen] = useState(false)
  const [quickAddName, setQuickAddName] = useState('')

  // Outside temperature display state. The backend stores canonical Celsius
  // (`outside_temp_c`) and the form's own field holds that canonical value;
  // this string is what the user reads and types, in `units.temperature`.
  // Fahrenheit is the one AFFINE token in the set, so its conversion is the
  // adapter's business and never a local `9/5 + 32`.
  const [outsideTempDisplay, setOutsideTempDisplay] = useState<string>(
    () => unitOrigins.outside_temp_c.display
  )
  const filledAt = watch('filled_at')
  const isMultiFuel = !!vehicleFuelTypeSecondary
  const obcAvailable = !!filledAt && filledAt.length > 0

  const handleStationSelect = (entry: AddressBookEntry | null) => {
    setLinkedStation(entry ? { id: entry.id, name: entry.business_name || '' } : null)
    if (entry) {
      setValue('station_address_book_id', entry.id, { shouldValidate: true })
      setValue('station_name_freetext', '', { shouldValidate: true })
      setValue('one_time_visit', false, { shouldValidate: true })
    }
  }

  const handleStationTextChange = (value: string) => {
    setStationText(value)
    // Text matching the linked station keeps (or restores) the link; anything
    // else means the user retyped over it, so the FK has to go or the record
    // keeps pointing at the old station (issue #108). Restoring matters as much
    // as clearing: typing a character and deleting it would otherwise leave the
    // link dropped and silently re-create the station on save.
    if (linkedStation && value === linkedStation.name) {
      setValue('station_address_book_id', linkedStation.id, { shouldValidate: true })
    } else {
      setValue('station_address_book_id', undefined, { shouldValidate: true })
    }
    setValue('station_name_freetext', value, { shouldValidate: true })
  }

  const fetchObcSuggestion = async () => {
    setObcMessage(null)
    setObcSuggestion(null)
    const at = getValues('filled_at')
    if (!at) return
    setObcLoading(true)
    try {
      const response = await api.get(
        `/vehicles/${vin}/fuel/obc-suggestion`,
        { params: { at } },
      )
      setObcSuggestion(response.data as ObcSuggestion)
    } catch (e: unknown) {
      // 404 = no matching session, surface a friendly message
      const err = e as { response?: { status?: number } }
      if (err?.response?.status === 404) {
        setObcMessage(t('fuel.obcNoSession'))
      } else {
        setObcMessage(t('common:error'))
      }
    } finally {
      setObcLoading(false)
    }
  }

  /**
   * Seed one unit-bearing react-hook-form field from a canonical value that
   * arrived AFTER mount, recording where it came from.
   *
   * ★ THE WHOLE POINT IS THAT THE TWO WRITES ARE ONE ACT. A value handed to
   * the form by the API (an OBC suggestion, a parsed receipt) is canonical, so
   * landing it is a second SEED and not a user edit: it needs the same
   * conversion the load-time seed does AND a fresh origin. Leave the load-time
   * origin in place and the next submit reads the rounded display as a change
   * and converts it back, so an accepted 8 L/100km is stored as 8.00047619048
   * for an MPG client. Setting the value without the origin is therefore not a
   * smaller version of this, it is the defect; there is no call site where one
   * without the other is right, which is why they live in one function rather
   * than in a convention.
   *
   * ★ It covers EVERY react-hook-form quantity origin, not just the two the
   * task that wrote it added. The receipt path used to inline the value half
   * and skip the origin half, so a draft odometer between two whole miles came
   * back rounded; that was one unguarded seed sitting beside a guarded one,
   * which is how the next unit-bearing field would have learned the wrong
   * idiom. Task 7 added `liters`, which the receipt path was landing the same
   * unguarded way, and `propane_liters` for symmetry: a name in this union with
   * no caller is cheaper than the next accepted draft reaching for `setValue`.
   * `outside_temp_c` is the one origin it cannot take: that field holds its
   * canonical value in react-hook-form and its display in a separate string
   * state, so it is written through `setOutsideTempDisplay` instead. See the
   * deferral note on that field's `<Field>` below. PRICE cannot use it either,
   * for a different reason: its origin carries a basis, so it has its own
   * `acceptPriceField` below.
   *
   * An absent value writes nothing rather than clearing the field, and that
   * covers two cases in one: a `null` from the API, and a quantity with no
   * finite display for the value (`mpg` is reciprocal, so a canonical zero
   * gives `toInputValue` nothing to return).
   *
   * @param name The form field to seed.
   * @param canonical The value in canonical units, or undefined for none.
   * @param quantity The formatter for that field's quantity.
   */
  const acceptUnitField = (
    name: 'odometer_km' | 'obc_l_per_100km' | 'obc_avg_speed_kmh' | 'liters' | 'propane_liters',
    canonical: number | undefined,
    quantity: QuantityFormat
  ) => {
    const origin = seedUnitField(canonical, quantity)
    const display = readNumber(origin.display)
    if (display === undefined) return
    setValue(name, display, { shouldValidate: true })
    setUnitOrigins((prev) => ({ ...prev, [name]: origin }))
  }

  /**
   * Seed the price field from a canonical price that arrived after mount.
   *
   * The price mirror of `acceptUnitField`, and it exists for the identical
   * reason: the parsed receipt used to `setValue` the converted price and leave
   * the load-time origin in place, so the next submit read the rounded display
   * as an edit and reconverted it. Its basis is `per_volume` because that is
   * what the parser reports; passing it explicitly is what makes the origin
   * comparable against whatever basis the user submits under.
   *
   * @param canonical The price in canonical $/L, or undefined for none.
   */
  const acceptPriceField = (canonical: number | undefined) => {
    const origin = seedPriceField(canonical, units, 'per_volume')
    const display = readNumber(origin.display)
    if (display === undefined) return
    setValue('price_per_unit', display, { shouldValidate: true })
    setPriceOrigin(origin)
  }

  const acceptObcSuggestion = () => {
    if (!obcSuggestion) return
    // The suggestion is canonical by contract: `routes/fuel.py` derives
    // L/100km from the drive session's own litres and kilometres and reads its
    // km/h average.
    acceptUnitField('obc_l_per_100km', readNumber(obcSuggestion.obc_l_per_100km), u.consumption)
    acceptUnitField('obc_avg_speed_kmh', readNumber(obcSuggestion.obc_avg_speed_kmh), u.speed)
    if (obcSuggestion.obc_trip_duration_s != null) {
      // Field is now a string (Phase 3.7); coerce the suggested seconds.
      setValue('obc_trip_duration_s', String(obcSuggestion.obc_trip_duration_s))
    }
    setObcSuggestion(null)
  }

  const parseReceipt = async (file?: File | null) => {
    setReceiptMessage(null)
    setReceiptDraft(null)
    if (!receiptText.trim() && !file) {
      setReceiptMessage(t('fuel.receiptNeedInput'))
      return
    }
    const formData = new FormData()
    if (receiptText.trim()) formData.append('text', receiptText.trim())
    if (file) formData.append('file', file)
    try {
      const result = await parseReceiptMutation.mutateAsync(formData)
      setReceiptDraft(result.draft)
    } catch (e: unknown) {
      const err = e as { response?: { status?: number; data?: { detail?: string } } }
      if (err?.response?.status === 403) {
        setReceiptMessage(t('fuel.receiptDisabled'))
      } else {
        setReceiptMessage(err.response?.data?.detail || t('fuel.receiptParseError'))
      }
    } finally {
      if (receiptFileRef.current) receiptFileRef.current.value = ''
    }
  }

  const acceptReceiptDraft = () => {
    if (!receiptDraft) return
    if (receiptDraft.date) setValue('date', receiptDraft.date, { shouldValidate: true })
    // Through the SAME adapter and the same presentation the seed uses, so an
    // accepted draft lands the value a seeded field would have shown. This
    // used to be an inline copy of that, and the copy set the value without
    // moving the ORIGIN, so a draft odometer between two whole miles came back
    // rounded on save: 72420.5 km shows as 45000 mi and re-converts to
    // 72420.3. Both of Task 2's surviving mutants lived in this function, and
    // it is now the same call the OBC suggestion makes.
    acceptUnitField('odometer_km', readNumber(receiptDraft.odometer_km), u.distance)
    // Through `acceptUnitField` for the same reason the odometer is: the draft's
    // litres are CANONICAL, so landing them is a second SEED and needs a fresh
    // origin as well as a converted value. This used to be an inline copy that
    // set the value alone, which left the load-time origin behind and made the
    // next submit reconvert the display it had just written.
    acceptUnitField('liters', readNumber(receiptDraft.liters), u.volume)
    if (receiptDraft.kwh != null) {
      setValue('kwh', Number(receiptDraft.kwh), { shouldValidate: true })
    }
    if (receiptDraft.cost != null) {
      setValue('cost', Number(receiptDraft.cost), { shouldValidate: true })
    }
    acceptPriceField(readNumber(receiptDraft.price_per_unit))
    if (isFuelType(receiptDraft.fuel_type_used)) {
      setValue('fuel_type_used', receiptDraft.fuel_type_used, { shouldValidate: true })
    }
    if (receiptDraft.notes) {
      setValue('notes', receiptDraft.notes, { shouldValidate: true })
    }
    if (receiptDraft.station_name) {
      setStationText(receiptDraft.station_name)
      setValue('station_name_freetext', receiptDraft.station_name, { shouldValidate: true })
      setValue('station_address_book_id', undefined, { shouldValidate: true })
    }
    setReceiptDraft(null)
    setReceiptText('')
  }

  // Total cost follows volume/energy, price and rebate on user edits only
  // (see useOnUserEdit). Reopening a record must leave its stored total
  // alone: a receipt is often not exactly volume by price, because a car
  // wash or a bag of ice rode along on the same swipe.
  useOnUserEdit(subscribe, ['liters', 'kwh', 'price_per_unit', 'rebate'], (values) => {
    const volumeNum = readNumber(values.liters) ?? readNumber(values.kwh)
    const priceNum = readNumber(values.price_per_unit)
    if (volumeNum === undefined || priceNum === undefined) return

    // Total Cost is the NET the driver actually paid: gross minus any
    // rebate/points. Clamp at 0 so an over-large rebate can't go negative.
    const net = volumeNum * priceNum - (readNumber(values.rebate) ?? 0)
    setValue('cost', parseFloat(Math.max(0, net).toFixed(2)))
  })

  const onSubmit = async (data: FuelRecordFormData) => {
    setError(null)
    // Authoritative recompute — independent of blur/Enter having fired (#109).
    const rawTime = filledTime.trim()
    const normTime = normalizeTime(filledTime, timeFormat)
    // A non-empty but INVALID/incomplete time must NOT be silently dropped to
    // null — block instead (Codex R1-H1). Empty is fine (means "no timestamp").
    if (rawTime !== '' && normTime === '') {
      setError(t('fuel.invalidFilledTime'))
      return
    }
    // filled_at = record date + entered time. Edit-safety (review R1-H2): if
    // neither the record date nor the time changed from the stored values,
    // resubmit the stored timestamp verbatim so an untouched record — including
    // a rare imported one whose date diverges from `date` — keeps its exact
    // filled_at. Otherwise recompute from the record's own date + the time.
    let filledAtValue: string | null
    if (isEdit && record?.filled_at) {
      const initialDate = formatDateForInput(record.date)
      const initialTime = splitFilledAt(record.filled_at).time
      const untouched = data.date === initialDate && normTime === initialTime
      filledAtValue = untouched
        ? record.filled_at
        : normTime
          ? joinFilledAt(data.date, normTime)
          : null
    } else {
      filledAtValue = normTime ? joinFilledAt(data.date, normTime) : null
    }

    // The three `registerDecimal` fields the origin arbitrates. `readNumber`
    // absorbs the INVALID_NUMBER symbol, which throws on implicit coercion.
    // The verbose `canonicalFromUnitField(String(x ?? ''), ...)` shape below is
    // repeated rather than wrapped on purpose: nine call sites across seven
    // forms spell the boundary exactly that way, and a local shorthand here
    // would make this the one form that reads differently. The shape's real
    // fix is a number-accepting overload on the helper, swept across all nine.
    const odometerTyped = readNumber(data.odometer_km)
    const obcConsumptionTyped = readNumber(data.obc_l_per_100km)
    const obcSpeedTyped = readNumber(data.obc_avg_speed_kmh)
    const litersTyped = readNumber(data.liters)
    const propaneTyped = readNumber(data.propane_liters)
    const priceTyped = readNumber(data.price_per_unit)

    try {
      // Convert user-entered values to canonical metric (SI) for the API.
      const payload: FuelRecordCreate | FuelRecordUpdate = {
        vin,
        date: data.date,
        filled_at: filledAtValue,
        // Back through `units.distance`, and an untouched field returns the
        // canonical value it was seeded from rather than a re-conversion of a
        // rounded display. `readNumber` also absorbs `registerDecimal`'s
        // INVALID_NUMBER symbol, which throws on every implicit coercion.
        // `?? ''` and not a separate undefined branch: an absent value then
        // takes `canonicalFromUnitField`'s own blank path instead of arriving
        // as the string "undefined" and reaching null by way of NaN. Same
        // result either way, which is why no test can tell them apart, so the
        // one that says what it means wins.
        odometer_km:
          canonicalFromUnitField(
            String(odometerTyped ?? ''),
            unitOrigins.odometer_km,
            u.distance
          ) ?? undefined,
        // Dimensionless — submitted verbatim, no canonical conversion.
        engine_hours: data.engine_hours,
        // ★ Volume and price convert through ONE resolved set. Splitting them
        // stores 10 gal as 37.85 L against an imperial-gallon price: one
        // payload, internally inconsistent, and worse than being uniformly
        // wrong. See utils/decimalSafe.ts. Both now go back through the origin
        // they were seeded from, so an untouched field returns its stored value
        // instead of a re-conversion of the rounding the seed applied.
        // `toLitersWirePrecision` is the API's declared 3 decimals, which the
        // protocol deliberately leaves to the caller: pydantic 422s a fourth.
        liters:
          toLitersWirePrecision(
            canonicalFromUnitField(String(litersTyped ?? ''), unitOrigins.liters, u.volume)
          ) ?? undefined,
        propane_liters:
          toLitersWirePrecision(
            canonicalFromUnitField(
              String(propaneTyped ?? ''),
              unitOrigins.propane_liters,
              u.volume
            )
          ) ?? undefined,
        kwh: data.kwh,
        soc_start_pct: data.soc_start_pct,
        soc_end_pct: data.soc_end_pct,
        charge_level: data.charge_level,
        charge_location: data.charge_location,
        battery_soh_pct: data.battery_soh_pct,
        price_per_unit:
          canonicalFromPriceField(
            String(priceTyped ?? ''),
            priceOrigin,
            units,
            data.price_basis
          ) ?? undefined,
        price_basis: data.price_basis,
        cost: data.cost,
        rebate: data.rebate,
        fuel_type_used: data.fuel_type_used,
        is_full_tank: data.is_full_tank,
        missed_fillup: data.missed_fillup,
        is_hauling: data.is_hauling,
        notes: data.notes,
        def_fill_level: data.def_fill_level !== undefined
          ? data.def_fill_level / 100
          : undefined,
        // Issue #69 — extended fuel tracking.
        // Send null, not undefined: the update path drops omitted keys
        // (exclude_unset), so an undefined here left a cleared or retyped
        // station's old value in place (issue #108).
        station_address_book_id: data.station_address_book_id ?? null,
        station_name_freetext: data.station_name_freetext || null,
        one_time_visit: data.one_time_visit ?? false,
        driver_user_id: data.driver_user_id,
        driver_name_freetext: data.driver_name_freetext || undefined,
        payment_method: data.payment_method,
        trip_type: data.trip_type,
        outside_temp_c: data.outside_temp_c,
        // Back through `units.consumption` and `units.speed`. An untouched
        // field returns the canonical value it was seeded from: 100 km/h shows
        // as 62 mph and 62 mph converts back to 99.77908 km/h, so a user who
        // opened a record to fix its notes would otherwise shave the recorded
        // average speed every time.
        obc_l_per_100km:
          canonicalFromUnitField(
            String(obcConsumptionTyped ?? ''),
            unitOrigins.obc_l_per_100km,
            u.consumption
          ) ?? undefined,
        obc_avg_speed_kmh:
          canonicalFromUnitField(
            String(obcSpeedTyped ?? ''),
            unitOrigins.obc_avg_speed_kmh,
            u.speed
          ) ?? undefined,
        // The backend pre-validator (app/schemas/fuel.py) accepts the
        // raw HH:MM/HH:MM:SS string and parses it to seconds. The
        // openapi-generated FuelRecordCreate still types this as
        // number | null because openapi can't express the
        // string-or-number union. The cast below is the explicit
        // acknowledgement that the wire format is broader than the
        // type. Will normalize when openapi types regenerate.
        obc_trip_duration_s:
          data.obc_trip_duration_s && data.obc_trip_duration_s.length > 0
            ? (data.obc_trip_duration_s as unknown as number)
            : undefined,
      } as FuelRecordCreate | FuelRecordUpdate

      if (isEdit) {
        await updateMutation.mutateAsync({ id: record.id, ...payload })
      } else {
        await createMutation.mutateAsync(payload as FuelRecordCreate)
      }

      onSuccess()
      onClose()
    } catch (err) {
      // attached.length === 0 catches a non-422 failure (network drop, 500):
      // it carries no field problems at all, so `unhandled` alone would stay
      // empty and this banner would never show.
      const { attached, unhandled } = applyServerErrors<FuelRecordFormData>(setFieldError, err, [
        'date',
        'odometer_km',
        'engine_hours',
        'liters',
        'kwh',
        'propane_liters',
        'price_per_unit',
        'price_basis',
        'rebate',
        'cost',
        'is_full_tank',
        'missed_fillup',
        'is_hauling',
        'def_fill_level',
        'fuel_type_used',
        'one_time_visit',
        'driver_name_freetext',
        'payment_method',
        'trip_type',
        'outside_temp_c',
        'obc_l_per_100km',
        'obc_avg_speed_kmh',
        'obc_trip_duration_s',
        'notes',
      ])
      if (attached.length === 0 || unhandled.length > 0) {
        setError(getActionErrorMessage(err, t('fuel.saveAction')))
      }
    }
  }

  // Task 13 — which usage dimension(s) drive the odometer vs. engine-hours
  // field visibility (a dual vehicle shows both).
  const { tracksDistance, tracksHours } = getUsageTracking({
    usage_unit: vehicleUsageUnit,
    secondary_usage_enabled: vehicleSecondaryUsageEnabled,
  })

  // Conditional field visibility based on fuel_type
  const isElectric = vehicleFuelType?.toLowerCase().includes('electric')
  const isHybrid = vehicleFuelType?.toLowerCase().includes('hybrid')
  const isPropane = vehicleFuelType?.toLowerCase().includes('propane')

  const isDiesel = isDieselFuelType(vehicleFuelType)
  const showGallons = !isElectric || isHybrid
  const showKwh = isElectric || isHybrid
  const showPropane = isPropane
  const showFullTankCheckbox = !isElectric
  const showHaulingCheckbox = !isElectric
  const showDefLevel = isDiesel

  // Dynamic labels. The denominator follows the PRICE BASIS, not the volume
  // unit alone: `priceToDisplay` scales a `per_weight` price by the resolved
  // MASS token, and a label that says "/gal" over a $/lb value is the
  // same-screen disagreement this change exists to remove. `per_kwh` and
  // `per_tank` convert nothing in either direction and are left as they were.
  const priceBasis = watch('price_basis')
  const priceDenominator =
    priceBasis === 'per_weight' ? UnitFormatter.getMassUnit(units) : UnitFormatter.getVolumeUnit(units)
  const priceLabel = isElectric ? t('fuel.pricePerKwh') : `${t('fuel.pricePer')} ${priceDenominator}`

  return (
    <FormModalWrapper
      title={isEdit ? t('fuel.editTitle') : t('fuel.createTitle')}
      onClose={onClose}
      width="lg"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            {t('common:cancel')}
          </Button>
          <Button
            type="submit"
            form="fuel-record-form"
            variant="primary"
            icon={Save}
            loading={isSubmitting}
          >
            {isSubmitting ? t('common:saving') : isEdit ? t('common:update') : t('common:create')}
          </Button>
        </>
      }
    >
        <form id="fuel-record-form" onSubmit={handleSubmit(onSubmit, (validationErrors) => {
          const fields = Object.keys(validationErrors).join(', ')
          setError(t('common:checkFields', { fields }))
        })} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          {!isEdit && llmReceiptEnabled && (
            <div className="rounded-lg border border-garage-border bg-garage-bg/40 p-4 space-y-3">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-primary" />
                <h4 className="text-sm font-semibold text-garage-text">{t('fuel.parseReceipt')}</h4>
              </div>
              <p className="text-xs text-garage-text-muted">{t('fuel.parseReceiptHint')}</p>
              <Textarea
                id="receipt_text"
                value={receiptText}
                onChange={(e) => setReceiptText(e.target.value)}
                placeholder={t('fuel.receiptTextPlaceholder')}
                rows={3}
                disabled={isSubmitting || parseReceiptMutation.isPending}
              />
              <div className="flex flex-wrap gap-2">
                <input
                  ref={receiptFileRef}
                  type="file"
                  accept="image/*,.pdf,application/pdf"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0]
                    void parseReceipt(file)
                  }}
                />
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={() => receiptFileRef.current?.click()}
                  loading={parseReceiptMutation.isPending}
                  disabled={isSubmitting}
                >
                  {t('fuel.receiptUpload')}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="primary"
                  icon={Sparkles}
                  onClick={() => void parseReceipt()}
                  loading={parseReceiptMutation.isPending}
                  disabled={isSubmitting || !receiptText.trim()}
                >
                  {t('fuel.parseReceipt')}
                </Button>
              </div>
              {receiptMessage && <p className="text-sm text-danger">{receiptMessage}</p>}
              {receiptDraft && (
                <div className="rounded-lg border border-primary/40 bg-primary/5 p-3 space-y-2">
                  <p className="text-sm text-garage-text">
                    {[
                      receiptDraft.date,
                      receiptDraft.station_name,
                      // R7: the draft's `liters` is CANONICAL litres, which is why
                      // `acceptReceiptDraft` seeds the field through
                      // `acceptUnitField` -> `seedUnitField` -> `u.volume`,
                      // recording an origin as it converts. (It converted
                      // through `litersToVolumeUnit` and recorded nothing until
                      // task 7.) This preview rendered it with a
                      // hardcoded 'L' beside it, so a gallons account read the
                      // canonical number under the wrong unit and then watched the
                      // field it accepted into show a different one. Same adapter as
                      // the field, `formatPrimary` because this line is a compact
                      // dot-separated summary with no room for a counterpart.
                      receiptDraft.liters != null
                        ? u.volume.formatPrimary(Number(receiptDraft.liters))
                        : null,
                      receiptDraft.kwh != null ? `${receiptDraft.kwh} kWh` : null,
                      receiptDraft.cost != null ? String(receiptDraft.cost) : null,
                    ]
                      .filter(Boolean)
                      .join(' · ') || t('fuel.receiptDraftEmpty')}
                  </p>
                  <div className="flex gap-2">
                    <Button size="sm" variant="primary" onClick={acceptReceiptDraft}>
                      {t('fuel.receiptDraftAccept')}
                    </Button>
                    <Button size="sm" variant="secondary" onClick={() => setReceiptDraft(null)}>
                      {t('fuel.receiptDraftDismiss')}
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <Field id="date" label={t('common:date')} required error={errors.date}>
              <Input type="date" id="date" {...register('date')} invalid={!!errors.date} disabled={isSubmitting} />
            </Field>
            {/* The placeholder below reads `units.distance` and is EXEMPT rather
                than migrated: ruling R5, a placeholder is a plausible EXAMPLE
                value with nothing canonical behind it to convert, and it reads
                the quantity of the field it sits in. The units gate exempted
                that shape on its comparison leg from the start; it sat in the
                baseline as phase 3b work for the whole phase only because the
                token-branch leg did not ask the same question. Task 8 wired the
                exemption to both legs, so this is structural and carries no
                pragma. */}
            {tracksDistance && (
              <Field id="odometer_km" label={t('common:mileage')} unit={u.distance.label} error={errors.odometer_km}>
                <NumberInput
                  id="odometer_km"
                  {...registerDecimal(register, 'odometer_km')}
                  placeholder={units.distance === 'mi' ? '45000' : '72420'}
                  invalid={!!errors.odometer_km}
                  disabled={isSubmitting}
                />
              </Field>
            )}
          </div>

          {/* Task 13 — engine-hours reading (hour-metered vehicles). Dimensionless:
              NO unit conversion regardless of system, unlike odometer_km above. */}
          {tracksHours && (
            <Field id="engine_hours" label={t('common:engineHours')} unit="hr" error={errors.engine_hours}>
              <NumberInput
                id="engine_hours"
                {...registerDecimal(register, 'engine_hours')}
                placeholder="812.4"
                invalid={!!errors.engine_hours}
                disabled={isSubmitting}
              />
            </Field>
          )}

          <div className="grid grid-cols-3 gap-4">
            {showGallons && (
              <Field id="liters" label={t('fuel.volume')} unit={UnitFormatter.getVolumeUnit(units)} error={errors.liters}>
                <NumberInput id="liters" {...registerDecimal(register, 'liters')} placeholder={VOLUME_EXAMPLES[units.volume].volume} invalid={!!errors.liters} disabled={isSubmitting} />
              </Field>
            )}
            {showKwh && (
              <Field id="kwh" label={t('fuel.energy')} unit="kWh" error={errors.kwh}>
                <NumberInput id="kwh" {...registerDecimal(register, 'kwh')} placeholder="45.500" invalid={!!errors.kwh} disabled={isSubmitting} />
              </Field>
            )}
            {showPropane && (
              <Field id="propane_liters" label={t('fuel.propane')} unit={UnitFormatter.getVolumeUnit(units)} error={errors.propane_liters}>
                <NumberInput id="propane_liters" {...registerDecimal(register, 'propane_liters')} placeholder="0.000" invalid={!!errors.propane_liters} disabled={isSubmitting} />
              </Field>
            )}
            <Field id="price_per_unit" label={priceLabel} error={errors.price_per_unit}>
              <div className="relative">
                <CurrencyInputPrefix />
                <NumberInput
                  id="price_per_unit"
                  {...registerDecimal(register, 'price_per_unit')}
                  placeholder={isElectric ? '0.130' : VOLUME_EXAMPLES[units.volume].price}
                  invalid={!!errors.price_per_unit}
                  disabled={isSubmitting}
                  className="pl-7"
                />
              </div>
            </Field>
          </div>

          {showKwh && (
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              <Field id="soc_start_pct" label={t('fuel.socStart')} unit="%" error={errors.soc_start_pct}>
                <NumberInput id="soc_start_pct" {...registerDecimal(register, 'soc_start_pct')} invalid={!!errors.soc_start_pct} disabled={isSubmitting} />
              </Field>
              <Field id="soc_end_pct" label={t('fuel.socEnd')} unit="%" error={errors.soc_end_pct}>
                <NumberInput id="soc_end_pct" {...registerDecimal(register, 'soc_end_pct')} invalid={!!errors.soc_end_pct} disabled={isSubmitting} />
              </Field>
              <Field id="battery_soh_pct" label={t('fuel.batterySoh')} unit="%" error={errors.battery_soh_pct}>
                <NumberInput id="battery_soh_pct" {...registerDecimal(register, 'battery_soh_pct')} invalid={!!errors.battery_soh_pct} disabled={isSubmitting} />
              </Field>
              {/* placeholder must be truthy: Select renders the empty option only
                  when it is, so placeholder="" showed 'L1' while submitting
                  undefined, and the field could never be cleared back to null. */}
              <Field id="charge_level" label={t('fuel.chargeLevel')} error={errors.charge_level}>
                <Select
                  id="charge_level"
                  {...register('charge_level')}
                  disabled={isSubmitting}
                  placeholder={t('fuel.chargeLevelPlaceholder')}
                  options={[
                    { value: 'L1', label: 'L1' },
                    { value: 'L2', label: 'L2' },
                    { value: 'DCFC', label: 'DCFC' },
                  ]}
                />
              </Field>
              <Field id="charge_location" label={t('fuel.chargeLocation')} error={errors.charge_location}>
                <Select
                  id="charge_location"
                  {...register('charge_location')}
                  disabled={isSubmitting}
                  placeholder={t('fuel.chargeLocationPlaceholder')}
                  options={[
                    { value: 'home', label: t('fuel.chargeHome') },
                    { value: 'public', label: t('fuel.chargePublic') },
                  ]}
                />
              </Field>
            </div>
          )}

          <Field id="price_basis" label={t('fuel.priceBasis')} error={errors.price_basis}>
            {/* Phase 3.6 — labels respect the user's unit preference.
                Was hardcoded "L/gal" / "kg/lb" regardless of system,
                per issue #69. */}
            <Select
              id="price_basis"
              {...register('price_basis')}
              disabled={isSubmitting}
              invalid={!!errors.price_basis}
              defaultValue={isElectric ? 'per_kwh' : 'per_volume'}
              options={[
                { value: 'per_volume', label: t('fuel.priceBasisPerVolume', { unit: UnitFormatter.getVolumeUnit(units) }) },
                { value: 'per_weight', label: t('fuel.priceBasisPerWeight', { unit: UnitFormatter.getMassUnit(units) }) },
                { value: 'per_kwh', label: t('fuel.priceBasisPerKwh') },
                { value: 'per_tank', label: t('fuel.priceBasisPerTank') },
              ]}
            />
          </Field>

          <div className="grid grid-cols-2 gap-4">
            <Field id="rebate" label={t('fuel.rebate')} error={errors.rebate} hint={t('fuel.rebateHint')}>
              <div className="relative">
                <CurrencyInputPrefix />
                <NumberInput id="rebate" {...registerDecimal(register, 'rebate')} placeholder="0.00" invalid={!!errors.rebate} disabled={isSubmitting} className="pl-7" />
              </div>
            </Field>
            <Field id="cost" label={t('common:totalCost')} error={errors.cost} hint={t('fuel.autoCalculatedHint')}>
              <div className="relative">
                <CurrencyInputPrefix />
                <NumberInput id="cost" {...registerDecimal(register, 'cost')} placeholder="42.99" invalid={!!errors.cost} disabled={isSubmitting} className="pl-7" />
              </div>
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-4">
            {showFullTankCheckbox && (
              <Checkbox id="is_full_tank" label={t('fuel.fullTankFillup')} {...register('is_full_tank')} disabled={isSubmitting} />
            )}
            <Checkbox id="missed_fillup" label={isElectric ? t('fuel.missedChargingSession') : t('fuel.missedFillup')} {...register('missed_fillup')} disabled={isSubmitting} />
          </div>

          {showHaulingCheckbox && (
            <div className="space-y-1">
              <Checkbox id="is_hauling" label={t('fuel.towingHaulingLoad')} {...register('is_hauling')} disabled={isSubmitting} />
              {hasLinkedTrailers && (
                <p className="text-xs text-text-mute">
                  {t('fuel.towPairHint')}
                </p>
              )}
            </div>
          )}

          {/* DEF Level - diesel vehicles only; the server rejects DEF data on non-diesel */}
          {showDefLevel && (
            <div className="rounded-lg border border-border p-4 space-y-2">
              <label className="block text-sm font-medium text-text">{t('fuel.defTankLevel')}</label>
              <div className="flex gap-2 mb-2">
                {FILL_LEVEL_PRESETS.map((preset) => (
                  <Button
                    key={preset.value}
                    size="sm"
                    variant={watch('def_fill_level') === preset.value ? 'primary' : 'secondary'}
                    onClick={() => setValue('def_fill_level', preset.value)}
                  >
                    {preset.labelKey ? t(preset.labelKey) : preset.label}
                  </Button>
                ))}
                <Button size="sm" variant="ghost" onClick={() => setValue('def_fill_level', undefined)}>
                  {t('common:clear')}
                </Button>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-24 shrink-0">
                  <NumberInput
                    {...registerDecimal(register, 'def_fill_level')}
                    placeholder="75"
                    invalid={!!errors.def_fill_level}
                    disabled={isSubmitting}
                  />
                </div>
                <span className="text-sm text-text-mute">%</span>
                {watch('def_fill_level') !== undefined && !isNaN(watch('def_fill_level') ?? NaN) && (
                  <div className="flex-1 h-4 rounded-full border border-border bg-surface-2 overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${
                        (watch('def_fill_level') ?? 0) > 50 ? 'bg-success' :
                        (watch('def_fill_level') ?? 0) > 25 ? 'bg-warning' : 'bg-danger'
                      }`}
                      style={{ width: `${Math.min(100, Math.max(0, watch('def_fill_level') ?? 0))}%` }}
                    />
                  </div>
                )}
              </div>
              <FormError error={errors.def_fill_level} />
              <p className="text-xs text-text-mute">{t('fuel.defAutoCreatesHint')}</p>
            </div>
          )}

          {!isElectric && (
            <div className="rounded-lg border border-(--accent-line) bg-(--accent-soft) p-3">
              <p className="text-sm text-(--accent-fg)"><strong>{t('common:tip')}:</strong> {t('fuel.mpgTip', { unit: u.consumption.label })}</p>
            </div>
          )}

          {isElectric && (
            <div className="rounded-lg border border-(--accent-line) bg-(--accent-soft) p-3">
              <p className="text-sm text-(--accent-fg)"><strong>{t('common:tip')}:</strong> {t('fuel.electricTip')}</p>
            </div>
          )}

          {/* Multi-fuel: only render when the vehicle has fuel_type_secondary set */}
          {isMultiFuel && (
            <Field id="fuel_type_used" label={t('fuel.fuelTypeUsed')} error={errors.fuel_type_used} hint={t('fuel.fuelTypeUsedHint')}>
              <Select
                id="fuel_type_used"
                {...register('fuel_type_used')}
                disabled={isSubmitting}
                invalid={!!errors.fuel_type_used}
                placeholder={t('common:select') || '—'}
                options={FUEL_TYPE_VALUES.map((value) => ({ value, label: t(`fuel.fuelTypes.${value}`) }))}
              />
            </Field>
          )}

          {/* "More details" — extended fuel tracking metadata (issue #69) */}
          <div className="rounded-lg border border-border overflow-hidden">
            <button
              type="button"
              onClick={toggleMoreDetails}
              className="w-full flex items-center justify-between px-4 py-3 bg-surface-2 hover:bg-surface-3 transition-colors"
              aria-expanded={moreDetailsOpen}
            >
              <span className="text-sm font-medium text-text flex items-center gap-2">
                {moreDetailsOpen ? <ChevronUp aria-hidden="true" className="w-4 h-4" /> : <ChevronDown aria-hidden="true" className="w-4 h-4" />}
                {t('fuel.moreDetails')}
              </span>
              <span className="text-xs text-text-mute">{t('fuel.moreDetailsHint')}</span>
            </button>

            {moreDetailsOpen && (
              <div className="p-4 space-y-4 border-t border-border">
                {/* Fill-up time — TimeInput24 untouched (owns the AM/PM control) */}
                <fieldset>
                  <legend className="block text-sm font-medium text-text mb-1">{t('fuel.filledAt')}</legend>
                  <TimeInput24
                    id="filled_at_time"
                    ariaLabel={t('fuel.filledAtTimeLabel')}
                    value={filledTime}
                    onChange={setFilledTime}
                    timeFormat={timeFormat}
                    disabled={isSubmitting}
                  />
                  <p className="text-xs text-text-mute mt-1">{t('fuel.filledAtTimeOnlyHint')}</p>
                </fieldset>

                {/* Station autocomplete + one-time-visit (AddressBookAutocomplete OUT of scope — only its className retokenized) */}
                <div>
                  <label htmlFor="station_name_freetext" className="block text-sm font-medium text-text mb-1">{t('fuel.station')}</label>
                  <AddressBookAutocomplete
                    id="station_name_freetext"
                    value={stationText}
                    onChange={handleStationTextChange}
                    onSelectEntry={handleStationSelect}
                    poiCategoryFilter="gas_station"
                    placeholder={t('fuel.stationPlaceholder')}
                    helperText={hasLinkedStation ? t('fuel.stationPicked') : t('fuel.stationCreatedHint')}
                    className="ui-focus-input ui-motion w-full rounded-control border border-border bg-surface-2 px-3 py-2 text-sm text-text"
                    onClear={() => {
                      setStationText('')
                      setLinkedStation(null)
                      setValue('station_address_book_id', undefined, { shouldValidate: true })
                      setValue('station_name_freetext', '', { shouldValidate: true })
                    }}
                    onAddNew={(typedName) => {
                      setQuickAddName(typedName)
                      setQuickAddOpen(true)
                    }}
                  />
                  <div className="mt-2">
                    <Checkbox id="one_time_visit" label={t('fuel.stationOneTimeVisit')} {...register('one_time_visit')} disabled={isSubmitting || hasLinkedStation} />
                  </div>
                </div>

                {/* Driver freetext */}
                <Field id="driver_name_freetext" label={t('fuel.driver')}>
                  <Input type="text" id="driver_name_freetext" {...register('driver_name_freetext')} placeholder={t('fuel.driverFreetextPlaceholder')} disabled={isSubmitting} />
                </Field>

                {/* Payment method + trip type — native selects, retokenized */}
                <div className="grid grid-cols-2 gap-4">
                  <Field id="payment_method" label={t('fuel.paymentMethod')} error={errors.payment_method}>
                    <Select
                      id="payment_method"
                      {...register('payment_method')}
                      disabled={isSubmitting}
                      invalid={!!errors.payment_method}
                      placeholder={t('fuel.paymentMethodPlaceholder')}
                      options={PAYMENT_METHOD_VALUES.map((value) => ({ value, label: t(`fuel.paymentMethods.${value}`) }))}
                    />
                  </Field>
                  <Field id="trip_type" label={t('fuel.tripType')} error={errors.trip_type}>
                    <Select
                      id="trip_type"
                      {...register('trip_type')}
                      disabled={isSubmitting}
                      invalid={!!errors.trip_type}
                      placeholder={t('fuel.tripTypePlaceholder')}
                      options={TRIP_TYPE_VALUES.map((value) => ({ value, label: t(`fuel.tripTypes.${value}`) }))}
                    />
                  </Field>
                </div>

                {/* Outside temp — controlled input (value/onChange). M1: compose <Input>
                    (it forwards value/onChange/step/id via ...rest). This IS a real
                    display-boundary field: the label, the step and the conversion all
                    come from `units.temperature`, which is an independent choice from
                    the volume `system` collapses.

                    ★ AND IT IS NOW THE ONLY ONE OF FOUR SHAPED THIS WAY, which is a
                    deferral rather than an oversight. The odometer and the two OBC
                    fields are react-hook-form NUMBER fields holding a display value the
                    origin arbitrates at submit, matching every sibling form in the repo;
                    this one keeps its canonical Celsius in react-hook-form and its
                    display in a separate string state, converting on each keystroke. It
                    is therefore the one origin `acceptUnitField` cannot take. Unifying
                    it is task-sized, not a rider: `makeFuelRecordSchema` bounds
                    `outside_temp_c` at -60..70 CANONICAL degrees, so moving the field to
                    display values changes what that range means, and
                    FuelRecordForm.mixedUnits.test.tsx pins the current behaviour. */}
                <Field id="outside_temp_display" label={t('fuel.outsideTemp')} unit={u.temperature.label} error={errors.outside_temp_c}>
                  <Input
                    type="number"
                    id="outside_temp_display"
                    mono
                    step={u.temperature.step}
                    value={outsideTempDisplay}
                    onChange={(e) => {
                      const raw = e.target.value
                      setOutsideTempDisplay(raw)
                      if (raw === '') {
                        setValue('outside_temp_c', undefined as unknown as number)
                        return
                      }
                      if (Number.isNaN(parseFloat(raw))) return
                      // Re-typing the seeded reading is not an edit of the
                      // quantity, so it returns the stored Celsius rather than
                      // a value round-tripped through the display precision.
                      const canonical = canonicalFromUnitField(
                        raw,
                        unitOrigins.outside_temp_c,
                        u.temperature
                      )
                      setValue('outside_temp_c', canonical ?? (undefined as unknown as number), {
                        shouldValidate: true,
                      })
                    }}
                    invalid={!!errors.outside_temp_c}
                    disabled={isSubmitting}
                  />
                </Field>

                {/* OBC subsection — box + buttons retokenized (G4c). B9: these three are
                    genuine USER-INPUT fields (not display-of-canonical), so they compose
                    <Input> inside <Field> (M1).

                    The two numeric ones are UNIT-BEARING. Storage is L/100km and km/h,
                    but the reading the user copies off their trip computer is in
                    `units.consumption` and `units.speed`, so the labels come from those
                    tokens and both fields go through the origin-preserving pair. This
                    note used to say the round trip was canonical-symmetric and that no
                    conversion was needed in either direction; that claim is what let an
                    MPH client type 60 and have 60 km/h stored, a 38% error on a field
                    nothing on the screen said was metric. THE SURFACE survived three
                    phases because it reports to neither leg of the units gate: it holds
                    no numeric literal and calls no formatter, so nothing enumerated it.

                    `obc_trip_duration_s` genuinely is invariant — seconds are not one of
                    the ten quantities — so it keeps a bare label and its own rendering. */}
                <div className="rounded-md border border-border bg-surface-2 p-3 space-y-3">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-medium text-text">{t('fuel.obcTitle')}</h4>
                    <Button
                      size="sm"
                      variant="secondary"
                      icon={Sparkles}
                      onClick={fetchObcSuggestion}
                      disabled={!obcAvailable || obcLoading || isSubmitting}
                      title={!obcAvailable ? t('fuel.obcAutoFillHint') : undefined}
                      loading={obcLoading}
                    >
                      {obcLoading ? t('common:loading') : t('fuel.obcAutoFill')}
                    </Button>
                  </div>
                  <p className="text-xs text-text-mute">{t('fuel.obcHint')}</p>

                  {obcSuggestion && (
                    <div className="rounded-md border border-(--accent-line) bg-(--accent-soft) p-2 flex items-center justify-between gap-2">
                      {/* The suggestion is canonical on the wire, so it is
                          rendered through the same tokens the fields below are
                          labelled with. A preview in L/100km over a field
                          labelled MPG is the same-screen disagreement, and this
                          line is what the user is being asked to approve.

                          Two of the three `?? '—'` markers that used to be here
                          went as a side effect: `format` carries its own absent
                          marker. The third is the trip duration, which is
                          seconds and has no formatter, so it borrows the same
                          constant rather than a matching literal that could
                          drift away from its two neighbours. */}
                      <div id="obc_suggestion_preview" className="text-xs text-text">
                        {u.consumption.format(readNumber(obcSuggestion.obc_l_per_100km))} ·{' '}
                        {u.speed.format(readNumber(obcSuggestion.obc_avg_speed_kmh))} · s:{' '}
                        {obcSuggestion.obc_trip_duration_s ?? NOT_AVAILABLE}
                      </div>
                      <div className="flex gap-1">
                        <Button size="sm" variant="primary" onClick={acceptObcSuggestion}>{t('fuel.obcSuggestionAccept')}</Button>
                        <Button size="sm" variant="secondary" onClick={() => setObcSuggestion(null)}>{t('fuel.obcSuggestionDismiss')}</Button>
                      </div>
                    </div>
                  )}

                  {obcMessage && <p className="text-xs text-text-mute">{obcMessage}</p>}

                  <div className="grid grid-cols-3 gap-2">
                    <Field id="obc_l_per_100km" label={t('fuel.obcConsumption')} unit={u.consumption.label}>
                      <NumberInput id="obc_l_per_100km" {...registerDecimal(register, 'obc_l_per_100km')} disabled={isSubmitting} />
                    </Field>
                    <Field id="obc_avg_speed_kmh" label={t('fuel.obcAvgSpeed')} unit={u.speed.label}>
                      <NumberInput id="obc_avg_speed_kmh" {...registerDecimal(register, 'obc_avg_speed_kmh')} disabled={isSubmitting} />
                    </Field>
                    <Field id="obc_trip_duration_s" label={t('fuel.obcDuration')}>
                      <Input type="text" id="obc_trip_duration_s" inputMode="text" placeholder={t('fuelRecordForm.obcDurationPlaceholder')} {...register('obc_trip_duration_s')} disabled={isSubmitting} />
                    </Field>
                  </div>
                </div>
              </div>
            )}
          </div>

          <Field id="notes" label={t('common:notes')} error={errors.notes}>
            <Textarea id="notes" rows={3} {...register('notes')} placeholder={t('common:additionalNotes')} invalid={!!errors.notes} disabled={isSubmitting} />
          </Field>
        </form>

        <AddressBookQuickAddModal
          isOpen={quickAddOpen}
          nested
          onClose={() => setQuickAddOpen(false)}
          initialName={quickAddName}
          poiCategory="gas_station"
          title={t('fuel.addStation')}
          onAdded={(entry) => {
            handleStationSelect(entry)
            setStationText(entry.business_name || entry.name || '')
          }}
        />
    </FormModalWrapper>
  )
}
