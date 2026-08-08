import { useMemo, useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Save, ChevronDown, ChevronUp, Sparkles } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import AddressBookAutocomplete from './AddressBookAutocomplete'
import AddressBookQuickAddModal from './AddressBookQuickAddModal'
import type { FuelRecord, FuelRecordCreate, FuelRecordUpdate } from '../types/fuel'
import type { Vehicle } from '../types/vehicle'
import type { AddressBookEntry } from '../types/addressBook'
import { makeFuelRecordSchema, type FuelRecordFormData } from '../schemas/fuel'
import {
  FUEL_TYPE_VALUES,
  PAYMENT_METHOD_VALUES,
  TRIP_TYPE_VALUES,
  isDieselFuelType,
} from '../constants/fuel'
import { FormError } from './FormError'
import api from '../services/api'
import { useCreateFuelRecord, useUpdateFuelRecord } from '../hooks/queries/useFuelRecords'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { useAuth } from '../contexts/AuthContext'
import { UnitConverter, UnitFormatter } from '../utils/units'
import { toCanonicalKm, toCanonicalLiters, priceToDisplay, priceToCanonical } from '../utils/decimalSafe'
import { getUsageTracking } from '../utils/usageTracking'
import CurrencyInputPrefix from './common/CurrencyInputPrefix'
import { Button, Field, Input, Select, Textarea, Checkbox } from './ui'
import { formatDateForInput } from '../utils/dateUtils'
import TimeInput24, { normalizeTime, formatTimeForInput } from './common/TimeInput24'
import { useTimeFormat } from '../hooks/useTimeFormat'

const MORE_DETAILS_KEY = 'fuel_form:more_details_expanded'

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

interface ObcSuggestion {
  session_id: number
  ended_at: string
  distance_km: number | string | null
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
  const [vehicleFuelType, setVehicleFuelType] = useState<string>('')
  const [vehicleFuelTypeSecondary, setVehicleFuelTypeSecondary] = useState<string>('')
  // Task 13 — which usage dimension(s) this vehicle tracks, driving the
  // odometer vs. engine-hours field visibility below. Defaults mirror
  // getUsageTracking's own distance-primary default so the form doesn't
  // flash the wrong field before the vehicle fetch resolves.
  const [vehicleUsageUnit, setVehicleUsageUnit] = useState<string>('distance')
  const [vehicleSecondaryUsageEnabled, setVehicleSecondaryUsageEnabled] = useState<boolean>(false)
  const { system } = useUnitPreference()
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

  // `labelKey` is translated at render time; the fraction labels are numerals
  // and stay as-is (they are not prose).
  const FILL_LEVEL_PRESETS = [
    { label: null, labelKey: 'fuelRecordForm.fillLevelFull', value: 100 },
    { label: '3/4', labelKey: null, value: 75 },
    { label: '1/2', labelKey: null, value: 50 },
    { label: '1/4', labelKey: null, value: 25 },
  ] as const

  // Helper to convert string | number to number (handles null from PostgreSQL API responses)
  const toNumber = (val: number | string | null | undefined): number | undefined => {
    if (val == null) return undefined
    const num = typeof val === 'string' ? parseFloat(val) : val
    return isNaN(num) ? undefined : num
  }

  // Zod bakes its messages in at construction, so the schema is rebuilt when
  // the language changes. Only the resolver depends on it — no fetch, no
  // reset() — so a rebuild can't discard what the user typed.
  const schema = useMemo(() => makeFuelRecordSchema(t), [t])

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    setValue,
    watch,
    getValues,
  } = useForm<FuelRecordFormData>({
    resolver: zodResolver(schema) as Resolver<FuelRecordFormData>,
    defaultValues: {
      date: formatDateForInput(record?.date),
      // Immediately overwritten by the sub-field mirror effect below once
      // filledTime seeds on mount — this is just the RHF key placeholder.
      filled_at: '',
      odometer_km: system === 'imperial' && record?.odometer_km != null
        ? UnitConverter.kmToMiles(toNumber(record.odometer_km)!) ?? undefined
        : toNumber(record?.odometer_km),
      // Engine hours are dimensionless — no unit conversion regardless of system.
      engine_hours: toNumber(record?.engine_hours),
      liters: system === 'imperial' && record?.liters != null
        ? UnitConverter.litersToGallons(toNumber(record.liters)!) ?? undefined
        : toNumber(record?.liters),
      propane_liters: system === 'imperial' && record?.propane_liters != null
        ? UnitConverter.litersToGallons(toNumber(record.propane_liters)!) ?? undefined
        : toNumber(record?.propane_liters),
      kwh: toNumber(record?.kwh),
      price_per_unit: priceToDisplay(record?.price_per_unit, system, record?.price_basis) ?? undefined,
      price_basis: (record?.price_basis as 'per_volume' | 'per_weight' | 'per_kwh' | 'per_tank' | undefined) ?? undefined,
      cost: toNumber(record?.cost),
      rebate: toNumber(record?.rebate),
      fuel_type: record?.fuel_type || '',
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
      station_address_book_id: toNumber(record?.station_address_book_id),
      station_name_freetext: record?.station_name_freetext || '',
      // A station with freetext and no FK IS a one-time visit — the flag isn't
      // stored, it's implied by that shape. Seeding a flat `false` left the box
      // unchecked on such a record, so editing it promoted a stop the user had
      // deliberately kept out of the address book (issue #108).
      one_time_visit: !record?.station_address_book_id && !!record?.station_name_freetext,
      driver_user_id: toNumber(record?.driver_user_id),
      driver_name_freetext: record?.driver_name_freetext || '',
      outside_temp_c: toNumber(record?.outside_temp_c),
      obc_l_per_100km: toNumber(record?.obc_l_per_100km),
      obc_avg_speed_kmh: toNumber(record?.obc_avg_speed_kmh),
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

  // Watch for auto-calculation
  const liters = watch('liters')
  const kwh = watch('kwh')
  const pricePerUnit = watch('price_per_unit')
  const rebate = watch('rebate')

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

        // Auto-populate fuel_type from vehicle if not editing
        if (!record && vehicleData.fuel_type) {
          setValue('fuel_type', vehicleData.fuel_type || '')
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

  // Phase 3.6 follow-up — outside temperature display state. Backend
  // stores canonical Celsius (`outside_temp_c`); imperial users see and
  // type Fahrenheit. The form's actual ``outside_temp_c`` field receives
  // the converted canonical value via setValue. Initialized from the
  // record's stored Celsius (converted to °F when imperial).
  const [outsideTempDisplay, setOutsideTempDisplay] = useState<string>(() => {
    if (record?.outside_temp_c == null) return ''
    const c = Number(record.outside_temp_c)
    if (Number.isNaN(c)) return ''
    const display = system === 'imperial' ? (c * 9) / 5 + 32 : c
    return String(Math.round(display * 10) / 10)
  })
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

  const acceptObcSuggestion = () => {
    if (!obcSuggestion) return
    if (obcSuggestion.obc_l_per_100km != null) {
      setValue('obc_l_per_100km', Number(obcSuggestion.obc_l_per_100km))
    }
    if (obcSuggestion.obc_avg_speed_kmh != null) {
      setValue('obc_avg_speed_kmh', Number(obcSuggestion.obc_avg_speed_kmh))
    }
    if (obcSuggestion.obc_trip_duration_s != null) {
      // Field is now a string (Phase 3.7); coerce the suggested seconds.
      setValue('obc_trip_duration_s', String(obcSuggestion.obc_trip_duration_s))
    }
    setObcSuggestion(null)
  }

  // Auto-calculate total cost when volume/energy and price per unit change
  // Skip auto-calc on mount when editing to preserve manually entered cost
  const [isInitialMount, setIsInitialMount] = useState(true)

  useEffect(() => {
    if (isInitialMount) {
      setIsInitialMount(false)
      return
    }

    // Auto-calculate based on liters or kwh
    const volumeOrEnergy = liters || kwh

    if (volumeOrEnergy && pricePerUnit) {
      const volumeNum = typeof volumeOrEnergy === 'number' ? volumeOrEnergy : parseFloat(volumeOrEnergy)
      const priceNum = typeof pricePerUnit === 'number' ? pricePerUnit : parseFloat(pricePerUnit)
      const rebateNum = typeof rebate === 'number' ? rebate : parseFloat(rebate ?? '')

      if (!isNaN(volumeNum) && !isNaN(priceNum)) {
        // Total Cost is the NET the driver actually paid: gross minus any
        // rebate/points. Clamp at 0 so an over-large rebate can't go negative.
        const gross = volumeNum * priceNum
        const net = gross - (isNaN(rebateNum) ? 0 : rebateNum)
        setValue('cost', parseFloat(Math.max(0, net).toFixed(2)))
      }
    }
  }, [liters, kwh, pricePerUnit, rebate, setValue, isInitialMount])

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

    try {
      // Convert user-entered values to canonical metric (SI) for the API.
      const payload: FuelRecordCreate | FuelRecordUpdate = {
        vin,
        date: data.date,
        filled_at: filledAtValue,
        odometer_km: toCanonicalKm(data.odometer_km, system) ?? undefined,
        // Dimensionless — submitted verbatim, no canonical conversion.
        engine_hours: data.engine_hours,
        liters: toCanonicalLiters(data.liters, system) ?? undefined,
        propane_liters: toCanonicalLiters(data.propane_liters, system) ?? undefined,
        kwh: data.kwh,
        price_per_unit: priceToCanonical(data.price_per_unit, system, data.price_basis) ?? undefined,
        price_basis: data.price_basis,
        cost: data.cost,
        rebate: data.rebate,
        fuel_type: data.fuel_type,
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
        obc_l_per_100km: data.obc_l_per_100km,
        obc_avg_speed_kmh: data.obc_avg_speed_kmh,
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
      setError(err instanceof Error ? err.message : t('common:error'))
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

  // Dynamic labels
  const priceLabel = isElectric ? t('fuel.pricePerKwh') : `${t('fuel.pricePer')} ${UnitFormatter.getVolumeUnit(system)}`

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

          <div className="grid grid-cols-2 gap-4">
            <Field id="date" label={t('common:date')} required error={errors.date}>
              <Input type="date" id="date" {...register('date')} invalid={!!errors.date} disabled={isSubmitting} />
            </Field>
            {tracksDistance && (
              <Field id="odometer_km" label={t('common:mileage')} unit={UnitFormatter.getDistanceUnit(system)} error={errors.odometer_km}>
                <Input
                  type="number"
                  id="odometer_km"
                  mono
                  {...register('odometer_km', { valueAsNumber: true })}
                  min="0"
                  placeholder={system === 'imperial' ? '45000' : '72420'}
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
              <Input
                type="number"
                id="engine_hours"
                mono
                {...register('engine_hours', { valueAsNumber: true })}
                min="0"
                step="0.1"
                placeholder="812.4"
                invalid={!!errors.engine_hours}
                disabled={isSubmitting}
              />
            </Field>
          )}

          <div className="grid grid-cols-3 gap-4">
            {showGallons && (
              <Field id="liters" label={t('fuel.volume')} unit={UnitFormatter.getVolumeUnit(system)} error={errors.liters}>
                <Input type="number" id="liters" mono {...register('liters', { valueAsNumber: true })} min="0" step="0.001" placeholder={system === 'imperial' ? '12.500' : '47.318'} invalid={!!errors.liters} disabled={isSubmitting} />
              </Field>
            )}
            {showKwh && (
              <Field id="kwh" label={t('fuel.energy')} unit="kWh" error={errors.kwh}>
                <Input type="number" id="kwh" mono {...register('kwh', { valueAsNumber: true })} min="0" step="0.001" placeholder="45.500" invalid={!!errors.kwh} disabled={isSubmitting} />
              </Field>
            )}
            {showPropane && (
              <Field id="propane_liters" label={t('fuel.propane')} unit={UnitFormatter.getVolumeUnit(system)} error={errors.propane_liters}>
                <Input type="number" id="propane_liters" mono {...register('propane_liters', { valueAsNumber: true })} min="0" step="0.001" placeholder="0.000" invalid={!!errors.propane_liters} disabled={isSubmitting} />
              </Field>
            )}
            <Field id="price_per_unit" label={priceLabel} error={errors.price_per_unit}>
              <div className="relative">
                <CurrencyInputPrefix />
                <input
                  type="number"
                  id="price_per_unit"
                  {...register('price_per_unit', { valueAsNumber: true })}
                  min="0"
                  step="0.001"
                  placeholder={isElectric ? '0.130' : (system === 'imperial' ? '3.499' : '0.924')}
                  aria-invalid={errors.price_per_unit ? true : undefined}
                  className={`ui-focus-input ui-motion w-full rounded-control border bg-surface-2 pl-7 pr-3 py-2 text-sm text-text font-mono tabular-nums ${errors.price_per_unit ? 'border-danger' : 'border-border'}`}
                  disabled={isSubmitting}
                />
              </div>
            </Field>
          </div>

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
                { value: 'per_volume', label: t('fuel.priceBasisPerVolume', { unit: system === 'imperial' ? 'gal' : 'L' }) },
                { value: 'per_weight', label: t('fuel.priceBasisPerWeight', { unit: system === 'imperial' ? 'lb' : 'kg' }) },
                { value: 'per_kwh', label: t('fuel.priceBasisPerKwh') },
                { value: 'per_tank', label: t('fuel.priceBasisPerTank') },
              ]}
            />
          </Field>

          <div className="grid grid-cols-2 gap-4">
            <Field id="rebate" label={t('fuel.rebate')} error={errors.rebate} hint={t('fuel.rebateHint')}>
              <div className="relative">
                <CurrencyInputPrefix />
                <input type="number" id="rebate" {...register('rebate', { valueAsNumber: true })} min="0" step="0.01" placeholder="0.00" aria-invalid={errors.rebate ? true : undefined} className={`ui-focus-input ui-motion w-full rounded-control border bg-surface-2 pl-7 pr-3 py-2 text-sm text-text font-mono tabular-nums ${errors.rebate ? 'border-danger' : 'border-border'}`} disabled={isSubmitting} />
              </div>
            </Field>
            <Field id="cost" label={t('common:totalCost')} error={errors.cost} hint={t('fuel.autoCalculatedHint')}>
              <div className="relative">
                <CurrencyInputPrefix />
                <input type="number" id="cost" {...register('cost', { valueAsNumber: true })} min="0" step="0.01" placeholder="42.99" aria-invalid={errors.cost ? true : undefined} className={`ui-focus-input ui-motion w-full rounded-control border bg-surface-2 pl-7 pr-3 py-2 text-sm text-text font-mono tabular-nums ${errors.cost ? 'border-danger' : 'border-border'}`} disabled={isSubmitting} />
              </div>
            </Field>
          </div>

          <Field id="fuel_type" label={t('fuel.fuelType')} error={errors.fuel_type} hint={t('fuel.autoPopulatedHint')}>
            <Input type="text" id="fuel_type" {...register('fuel_type')} placeholder={t('fuelRecordForm.fuelTypePlaceholder')} invalid={!!errors.fuel_type} disabled={isSubmitting} />
          </Field>

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
                  {t('fuel.towPairHint', {
                    defaultValue: 'This vehicle has linked trailers — consider marking hauling if you were towing.',
                  })}
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
                  <Input
                    type="number"
                    mono
                    {...register('def_fill_level', { valueAsNumber: true })}
                    min="0"
                    max="100"
                    step="1"
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
              <p className="text-sm text-(--accent-fg)"><strong>{t('common:tip')}:</strong> {t('fuel.mpgTip')}</p>
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
                    display-boundary field: the label unit varies (°F/°C) AND onChange
                    converts F→C to canonical — unchanged from today. */}
                <Field id="outside_temp_display" label={t('fuel.outsideTemp')} unit={system === 'imperial' ? '°F' : '°C'} error={errors.outside_temp_c}>
                  <Input
                    type="number"
                    id="outside_temp_display"
                    mono
                    step="0.1"
                    value={outsideTempDisplay}
                    onChange={(e) => {
                      const raw = e.target.value
                      setOutsideTempDisplay(raw)
                      if (raw === '') {
                        setValue('outside_temp_c', undefined as unknown as number)
                        return
                      }
                      const num = parseFloat(raw)
                      if (Number.isNaN(num)) return
                      const canonical = system === 'imperial' ? ((num - 32) * 5) / 9 : num
                      setValue('outside_temp_c', canonical, { shouldValidate: true })
                    }}
                    invalid={!!errors.outside_temp_c}
                    disabled={isSubmitting}
                  />
                </Field>

                {/* OBC subsection — box + buttons retokenized (G4c). B9: these three are
                    genuine USER-INPUT fields (not display-of-canonical), so they compose
                    <Input> inside <Field> (M1) with FIXED canonical unit labels (B9 — see
                    the note after this block). The two numeric fields carry unit="L/100km"
                    / unit="km/h" because the round-trip is canonical-symmetric (no
                    conversion either direction). */}
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
                      <div className="text-xs text-text">
                        L/100km: {obcSuggestion.obc_l_per_100km ?? '—'} · km/h:{' '}
                        {obcSuggestion.obc_avg_speed_kmh ?? '—'} · s:{' '}
                        {obcSuggestion.obc_trip_duration_s ?? '—'}
                      </div>
                      <div className="flex gap-1">
                        <Button size="sm" variant="primary" onClick={acceptObcSuggestion}>{t('fuel.obcSuggestionAccept')}</Button>
                        <Button size="sm" variant="secondary" onClick={() => setObcSuggestion(null)}>{t('fuel.obcSuggestionDismiss')}</Button>
                      </div>
                    </div>
                  )}

                  {obcMessage && <p className="text-xs text-text-mute">{obcMessage}</p>}

                  <div className="grid grid-cols-3 gap-2">
                    <Field id="obc_l_per_100km" label={t('fuel.obcConsumption')} unit="L/100km">
                      <Input type="number" id="obc_l_per_100km" mono step="0.01" {...register('obc_l_per_100km', { valueAsNumber: true })} disabled={isSubmitting} />
                    </Field>
                    <Field id="obc_avg_speed_kmh" label={t('fuel.obcAvgSpeed')} unit="km/h">
                      <Input type="number" id="obc_avg_speed_kmh" mono step="0.1" {...register('obc_avg_speed_kmh', { valueAsNumber: true })} disabled={isSubmitting} />
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
