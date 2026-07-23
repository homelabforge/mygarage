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
import CurrencyInputPrefix from './common/CurrencyInputPrefix'
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
    <FormModalWrapper title={isEdit ? t('fuel.editTitle') : t('fuel.createTitle')} onClose={onClose} width="lg">
        <form onSubmit={handleSubmit(onSubmit, (validationErrors) => {
          const fields = Object.keys(validationErrors).join(', ')
          setError(t('common:checkFields', { fields }))
        })} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="date" className="block text-sm font-medium text-garage-text mb-1">
                {t('common:date')} <span className="text-danger">*</span>
              </label>
              <input
                type="date"
                id="date"
                {...register('date')}
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.date ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
              <FormError error={errors.date} />
            </div>

            <div>
              <label htmlFor="odometer_km" className="block text-sm font-medium text-garage-text mb-1">
                {t('common:mileage')} ({UnitFormatter.getDistanceUnit(system)})
              </label>
              <input
                type="number"
                id="odometer_km"
                {...register('odometer_km', { valueAsNumber: true })}
                min="0"
                placeholder={system === 'imperial' ? '45000' : '72420'}
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.odometer_km ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
              <FormError error={errors.odometer_km} />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4">
            {/* Regular Fuel (Gallons) - Show for gas/diesel/hybrid */}
            {showGallons && (
              <div>
                <label htmlFor="liters" className="block text-sm font-medium text-garage-text mb-1">
                  {t('fuel.volume')} ({UnitFormatter.getVolumeUnit(system)})
                </label>
                <input
                  type="number"
                  id="liters"
                  {...register('liters', { valueAsNumber: true })}
                  min="0"
                  step="0.001"
                  placeholder={system === 'imperial' ? '12.500' : '47.318'}
                  className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.liters ? 'border-red-500' : 'border-garage-border'
                  }`}
                  disabled={isSubmitting}
                />
                <FormError error={errors.liters} />
              </div>
            )}

            {/* Electric Energy (kWh) - Show for electric/hybrid */}
            {showKwh && (
              <div>
                <label htmlFor="kwh" className="block text-sm font-medium text-garage-text mb-1">
                  {t('fuel.energy')} (kWh)
                </label>
                <input
                  type="number"
                  id="kwh"
                  {...register('kwh', { valueAsNumber: true })}
                  min="0"
                  step="0.001"
                  placeholder="45.500"
                  className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.kwh ? 'border-red-500' : 'border-garage-border'
                  }`}
                  disabled={isSubmitting}
                />
                <FormError error={errors.kwh} />
              </div>
            )}

            {/* Propane - Show for propane vehicles */}
            {showPropane && (
              <div>
                <label htmlFor="propane_liters" className="block text-sm font-medium text-garage-text mb-1">
                  {t('fuel.propane')} ({UnitFormatter.getVolumeUnit(system)})
                </label>
                <input
                  type="number"
                  id="propane_liters"
                  {...register('propane_liters', { valueAsNumber: true })}
                  min="0"
                  step="0.001"
                  placeholder="0.000"
                  className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.propane_liters ? 'border-red-500' : 'border-garage-border'
                  }`}
                  disabled={isSubmitting}
                />
                <FormError error={errors.propane_liters} />
              </div>
            )}

            {/* Price per unit */}
            <div>
              <label htmlFor="price_per_unit" className="block text-sm font-medium text-garage-text mb-1">
                {priceLabel}
              </label>
              <div className="relative">
                <CurrencyInputPrefix />
                <input
                  type="number"
                  id="price_per_unit"
                  {...register('price_per_unit', { valueAsNumber: true })}
                  min="0"
                  step="0.001"
                  placeholder={isElectric ? '0.130' : (system === 'imperial' ? '3.499' : '0.924')}
                  className={`w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.price_per_unit ? 'border-red-500' : 'border-garage-border'
                  }`}
                  disabled={isSubmitting}
                />
              </div>
              <FormError error={errors.price_per_unit} />
            </div>
          </div>

          <div>
            <label htmlFor="price_basis" className="block text-sm font-medium text-garage-text mb-1">
              {t('fuel.priceBasis')}
            </label>
            <select
              id="price_basis"
              {...register('price_basis')}
              className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text border-garage-border"
              disabled={isSubmitting}
              defaultValue={isElectric ? 'per_kwh' : 'per_volume'}
            >
              {/* Phase 3.6 — labels respect the user's unit preference.
                  Was hardcoded "L/gal" / "kg/lb" regardless of system,
                  per issue #69. */}
              <option value="per_volume">
                {t('fuel.priceBasisPerVolume', {
                  unit: system === 'imperial' ? 'gal' : 'L',
                })}
              </option>
              <option value="per_weight">
                {t('fuel.priceBasisPerWeight', {
                  unit: system === 'imperial' ? 'lb' : 'kg',
                })}
              </option>
              <option value="per_kwh">{t('fuel.priceBasisPerKwh')}</option>
              <option value="per_tank">{t('fuel.priceBasisPerTank')}</option>
            </select>
            <FormError error={errors.price_basis} />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="rebate" className="block text-sm font-medium text-garage-text mb-1">
                {t('fuel.rebate')}
              </label>
              <div className="relative">
                <CurrencyInputPrefix />
                <input
                  type="number"
                  id="rebate"
                  {...register('rebate', { valueAsNumber: true })}
                  min="0"
                  step="0.01"
                  placeholder="0.00"
                  className={`w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.rebate ? 'border-red-500' : 'border-garage-border'
                  }`}
                  disabled={isSubmitting}
                />
              </div>
              <FormError error={errors.rebate} />
              <p className="text-xs text-garage-text-muted mt-1">
                {t('fuel.rebateHint')}
              </p>
            </div>

            <div>
              <label htmlFor="cost" className="block text-sm font-medium text-garage-text mb-1">
                {t('common:totalCost')}
              </label>
              <div className="relative">
                <CurrencyInputPrefix />
                <input
                  type="number"
                  id="cost"
                  {...register('cost', { valueAsNumber: true })}
                  min="0"
                  step="0.01"
                  placeholder="42.99"
                  className={`w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.cost ? 'border-red-500' : 'border-garage-border'
                  }`}
                  disabled={isSubmitting}
                />
              </div>
              <FormError error={errors.cost} />
              <p className="text-xs text-garage-text-muted mt-1">
                {t('fuel.autoCalculatedHint')}
              </p>
            </div>
          </div>

          <div>
            <label htmlFor="fuel_type" className="block text-sm font-medium text-garage-text mb-1">
              {t('fuel.fuelType')}
            </label>
            <input
              type="text"
              id="fuel_type"
              {...register('fuel_type')}
              placeholder={t('fuelRecordForm.fuelTypePlaceholder')}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.fuel_type ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <FormError error={errors.fuel_type} />
            <p className="text-xs text-garage-text-muted mt-1">
              {t('fuel.autoPopulatedHint')}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            {showFullTankCheckbox && (
              <div className="flex items-center">
                <input
                  type="checkbox"
                  id="is_full_tank"
                  {...register('is_full_tank')}
                  className="h-4 w-4 text-primary focus:ring-primary border-garage-border rounded bg-garage-bg"
                  disabled={isSubmitting}
                />
                <label htmlFor="is_full_tank" className="ml-2 block text-sm text-garage-text">
                  {t('fuel.fullTankFillup')}
                </label>
              </div>
            )}

            <div className="flex items-center">
              <input
                type="checkbox"
                id="missed_fillup"
                {...register('missed_fillup')}
                className="h-4 w-4 text-primary focus:ring-primary border-garage-border rounded bg-garage-bg"
                disabled={isSubmitting}
              />
              <label htmlFor="missed_fillup" className="ml-2 block text-sm text-garage-text">
                {isElectric ? t('fuel.missedChargingSession') : t('fuel.missedFillup')}
              </label>
            </div>
          </div>

          {showHaulingCheckbox && (
            <div className="flex items-center">
              <input
                type="checkbox"
                id="is_hauling"
                {...register('is_hauling')}
                className="h-4 w-4 text-primary focus:ring-primary border-garage-border rounded bg-garage-bg"
                disabled={isSubmitting}
              />
              <label htmlFor="is_hauling" className="ml-2 block text-sm text-garage-text">
                {t('fuel.towingHaulingLoad')}
              </label>
            </div>
          )}

          {/* DEF Level - diesel vehicles only; the server rejects DEF data on non-diesel */}
          {showDefLevel && (
            <div className="border border-garage-border rounded-lg p-4 space-y-2">
              <label className="block text-sm font-medium text-garage-text">
                {t('fuel.defTankLevel')}
              </label>
              <div className="flex gap-2 mb-2">
                {FILL_LEVEL_PRESETS.map(preset => (
                  <button
                    key={preset.value}
                    type="button"
                    onClick={() => setValue('def_fill_level', preset.value)}
                    className={`px-3 py-1.5 text-sm rounded-md border transition-colors ${
                      watch('def_fill_level') === preset.value
                        ? 'bg-primary text-(--accent-on-solid) border-primary'
                        : 'bg-garage-bg text-garage-text border-garage-border hover:border-primary'
                    }`}
                  >
                    {preset.labelKey ? t(preset.labelKey) : preset.label}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => setValue('def_fill_level', undefined)}
                  className="px-3 py-1.5 text-sm rounded-md border border-garage-border bg-garage-bg text-garage-text-muted hover:border-danger"
                >
                  {t('common:clear')}
                </button>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  {...register('def_fill_level', { valueAsNumber: true })}
                  min="0"
                  max="100"
                  step="1"
                  placeholder="75"
                  className={`w-24 px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.def_fill_level ? 'border-red-500' : 'border-garage-border'
                  }`}
                  disabled={isSubmitting}
                />
                <span className="text-sm text-garage-text-muted">%</span>
                {watch('def_fill_level') !== undefined && !isNaN(watch('def_fill_level') ?? NaN) && (
                  <div className="flex-1 h-4 bg-garage-bg rounded-full border border-garage-border overflow-hidden">
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
              <p className="text-xs text-garage-text-muted">
                {t('fuel.defAutoCreatesHint')}
              </p>
            </div>
          )}

          {!isElectric && (
            <div className="bg-primary/10 border border-primary rounded-lg p-3">
              <p className="text-sm text-primary">
                <strong>{t('common:tip')}:</strong> {t('fuel.mpgTip')}
              </p>
            </div>
          )}

          {isElectric && (
            <div className="bg-primary/10 border border-primary rounded-lg p-3">
              <p className="text-sm text-primary">
                <strong>{t('common:tip')}:</strong> {t('fuel.electricTip')}
              </p>
            </div>
          )}

          {/* Multi-fuel: only render when the vehicle has fuel_type_secondary set */}
          {isMultiFuel && (
            <div>
              <label htmlFor="fuel_type_used" className="block text-sm font-medium text-garage-text mb-1">
                {t('fuel.fuelTypeUsed')}
              </label>
              <select
                id="fuel_type_used"
                {...register('fuel_type_used')}
                className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text border-garage-border"
                disabled={isSubmitting}
              >
                <option value="">{t('common:select') || '—'}</option>
                {FUEL_TYPE_VALUES.map((value) => (
                  <option key={value} value={value}>
                    {t(`fuel.fuelTypes.${value}`)}
                  </option>
                ))}
              </select>
              <FormError error={errors.fuel_type_used} />
              <p className="text-xs text-garage-text-muted mt-1">{t('fuel.fuelTypeUsedHint')}</p>
            </div>
          )}

          {/* "More details" — extended fuel tracking metadata (issue #69) */}
          <div className="border border-garage-border rounded-lg overflow-hidden">
            <button
              type="button"
              onClick={toggleMoreDetails}
              className="w-full flex items-center justify-between px-4 py-3 bg-garage-bg hover:bg-garage-surface transition-colors"
              aria-expanded={moreDetailsOpen}
            >
              <span className="text-sm font-medium text-garage-text flex items-center gap-2">
                {moreDetailsOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                {t('fuel.moreDetails')}
              </span>
              <span className="text-xs text-garage-text-muted">{t('fuel.moreDetailsHint')}</span>
            </button>

            {moreDetailsOpen && (
              <div className="p-4 space-y-4 border-t border-garage-border">
                {/* Fill-up time (issue #109) — date comes from the record's date field */}
                <fieldset>
                  <legend className="block text-sm font-medium text-garage-text mb-1">
                    {t('fuel.filledAt')}
                  </legend>
                  <TimeInput24
                    id="filled_at_time"
                    ariaLabel={t('fuel.filledAtTimeLabel')}
                    value={filledTime}
                    onChange={setFilledTime}
                    timeFormat={timeFormat}
                    disabled={isSubmitting}
                  />
                  <p className="text-xs text-garage-text-muted mt-1">
                    {t('fuel.filledAtTimeOnlyHint')}
                  </p>
                </fieldset>

                {/* Station autocomplete + one-time-visit */}
                <div>
                  <label htmlFor="station_name_freetext" className="block text-sm font-medium text-garage-text mb-1">
                    {t('fuel.station')}
                  </label>
                  <AddressBookAutocomplete
                    id="station_name_freetext"
                    value={stationText}
                    onChange={handleStationTextChange}
                    onSelectEntry={handleStationSelect}
                    poiCategoryFilter="gas_station"
                    placeholder={t('fuel.stationPlaceholder')}
                    helperText={
                      hasLinkedStation
                        ? t('fuel.stationPicked')
                        : t('fuel.stationCreatedHint')
                    }
                    className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text border-garage-border"
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
                  <div className="mt-2 flex items-center">
                    <input
                      type="checkbox"
                      id="one_time_visit"
                      {...register('one_time_visit')}
                      disabled={isSubmitting || hasLinkedStation}
                      className="h-4 w-4 text-primary focus:ring-primary border-garage-border rounded bg-garage-bg disabled:opacity-50"
                    />
                    <label
                      htmlFor="one_time_visit"
                      className={`ml-2 block text-sm ${hasLinkedStation ? 'text-garage-text-muted' : 'text-garage-text'}`}
                    >
                      {t('fuel.stationOneTimeVisit')}
                    </label>
                  </div>
                </div>

                {/* Driver — freetext only for v1; user FK can be wired in a follow-up */}
                <div>
                  <label htmlFor="driver_name_freetext" className="block text-sm font-medium text-garage-text mb-1">
                    {t('fuel.driver')}
                  </label>
                  <input
                    type="text"
                    id="driver_name_freetext"
                    {...register('driver_name_freetext')}
                    placeholder={t('fuel.driverFreetextPlaceholder')}
                    className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text border-garage-border"
                    disabled={isSubmitting}
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="payment_method" className="block text-sm font-medium text-garage-text mb-1">
                      {t('fuel.paymentMethod')}
                    </label>
                    <select
                      id="payment_method"
                      {...register('payment_method')}
                      className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text border-garage-border"
                      disabled={isSubmitting}
                    >
                      <option value="">{t('fuel.paymentMethodPlaceholder')}</option>
                      {PAYMENT_METHOD_VALUES.map((value) => (
                        <option key={value} value={value}>
                          {t(`fuel.paymentMethods.${value}`)}
                        </option>
                      ))}
                    </select>
                    <FormError error={errors.payment_method} />
                  </div>

                  <div>
                    <label htmlFor="trip_type" className="block text-sm font-medium text-garage-text mb-1">
                      {t('fuel.tripType')}
                    </label>
                    <select
                      id="trip_type"
                      {...register('trip_type')}
                      className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text border-garage-border"
                      disabled={isSubmitting}
                    >
                      <option value="">{t('fuel.tripTypePlaceholder')}</option>
                      {TRIP_TYPE_VALUES.map((value) => (
                        <option key={value} value={value}>
                          {t(`fuel.tripTypes.${value}`)}
                        </option>
                      ))}
                    </select>
                    <FormError error={errors.trip_type} />
                  </div>
                </div>

                <div>
                  <label htmlFor="outside_temp_display" className="block text-sm font-medium text-garage-text mb-1">
                    {t('fuel.outsideTemp')} ({system === 'imperial' ? '°F' : '°C'})
                  </label>
                  <input
                    type="number"
                    id="outside_temp_display"
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
                      // Backend stores canonical Celsius; convert F → C on imperial.
                      const canonical = system === 'imperial' ? ((num - 32) * 5) / 9 : num
                      setValue('outside_temp_c', canonical, { shouldValidate: true })
                    }}
                    className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text border-garage-border"
                    disabled={isSubmitting}
                  />
                  <FormError error={errors.outside_temp_c} />
                </div>

                {/* OBC subsection */}
                <div className="border border-garage-border rounded-md p-3 bg-garage-bg space-y-3">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-medium text-garage-text">{t('fuel.obcTitle')}</h4>
                    <button
                      type="button"
                      onClick={fetchObcSuggestion}
                      disabled={!obcAvailable || obcLoading || isSubmitting}
                      title={!obcAvailable ? t('fuel.obcAutoFillHint') : undefined}
                      className="flex items-center gap-1 text-xs px-2 py-1 rounded border border-garage-border bg-garage-surface text-garage-text hover:border-primary disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <Sparkles className="w-3 h-3" />
                      {obcLoading ? t('common:loading') : t('fuel.obcAutoFill')}
                    </button>
                  </div>
                  <p className="text-xs text-garage-text-muted">{t('fuel.obcHint')}</p>

                  {obcSuggestion && (
                    <div className="bg-primary/10 border border-primary rounded-md p-2 flex items-center justify-between gap-2">
                      <div className="text-xs text-garage-text">
                        L/100km: {obcSuggestion.obc_l_per_100km ?? '—'} · km/h:{' '}
                        {obcSuggestion.obc_avg_speed_kmh ?? '—'} · s:{' '}
                        {obcSuggestion.obc_trip_duration_s ?? '—'}
                      </div>
                      <div className="flex gap-1">
                        <button
                          type="button"
                          onClick={acceptObcSuggestion}
                          className="text-xs px-2 py-1 rounded bg-primary text-(--accent-on-solid)"
                        >
                          {t('fuel.obcSuggestionAccept')}
                        </button>
                        <button
                          type="button"
                          onClick={() => setObcSuggestion(null)}
                          className="text-xs px-2 py-1 rounded border border-garage-border bg-garage-surface text-garage-text"
                        >
                          {t('fuel.obcSuggestionDismiss')}
                        </button>
                      </div>
                    </div>
                  )}

                  {obcMessage && (
                    <p className="text-xs text-garage-text-muted">{obcMessage}</p>
                  )}

                  <div className="grid grid-cols-3 gap-2">
                    <div>
                      <label htmlFor="obc_l_per_100km" className="block text-xs text-garage-text-muted mb-1">
                        {t('fuel.obcConsumption')}
                      </label>
                      <input
                        type="number"
                        id="obc_l_per_100km"
                        step="0.01"
                        {...register('obc_l_per_100km', { valueAsNumber: true })}
                        className="w-full px-2 py-1 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text border-garage-border"
                        disabled={isSubmitting}
                      />
                    </div>
                    <div>
                      <label htmlFor="obc_avg_speed_kmh" className="block text-xs text-garage-text-muted mb-1">
                        {t('fuel.obcAvgSpeed')}
                      </label>
                      <input
                        type="number"
                        id="obc_avg_speed_kmh"
                        step="0.1"
                        {...register('obc_avg_speed_kmh', { valueAsNumber: true })}
                        className="w-full px-2 py-1 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text border-garage-border"
                        disabled={isSubmitting}
                      />
                    </div>
                    <div>
                      <label htmlFor="obc_trip_duration_s" className="block text-xs text-garage-text-muted mb-1">
                        {t('fuel.obcDuration')}
                      </label>
                      <input
                        type="text"
                        id="obc_trip_duration_s"
                        inputMode="text"
                        placeholder={t('fuelRecordForm.obcDurationPlaceholder')}
                        {...register('obc_trip_duration_s')}
                        className="w-full px-2 py-1 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text border-garage-border"
                        disabled={isSubmitting}
                      />
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          <div>
            <label htmlFor="notes" className="block text-sm font-medium text-garage-text mb-1">
              {t('common:notes')}
            </label>
            <textarea
              id="notes"
              rows={3}
              {...register('notes')}
              placeholder={t('common:additionalNotes')}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.notes ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <FormError error={errors.notes} />
          </div>

          <div className="flex gap-3 pt-4">
            <button
              type="submit"
              disabled={isSubmitting}
              className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Save className="w-4 h-4" />
              <span>{isSubmitting ? t('common:saving') : isEdit ? t('common:update') : t('common:create')}</span>
            </button>

            <button
              type="button"
              onClick={onClose}
              className="btn btn-primary rounded-lg transition-colors"
              disabled={isSubmitting}
            >
              {t('common:cancel')}
            </button>
          </div>
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
