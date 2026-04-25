import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Save } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import type { FuelRecord, FuelRecordCreate, FuelRecordUpdate } from '../types/fuel'
import type { Vehicle } from '../types/vehicle'
import { fuelRecordSchema, type FuelRecordFormData } from '../schemas/fuel'
import { FormError } from './FormError'
import api from '../services/api'
import { useCreateFuelRecord, useUpdateFuelRecord } from '../hooks/queries/useFuelRecords'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitConverter, UnitFormatter } from '../utils/units'
import { toCanonicalKm, toCanonicalLiters, priceToDisplay, priceToCanonical } from '../utils/decimalSafe'
import CurrencyInputPrefix from './common/CurrencyInputPrefix'
import { formatDateForInput } from '../utils/dateUtils'

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
  const [defTankCapacity, setDefTankCapacity] = useState<number>(0)
  const { system } = useUnitPreference()

  const FILL_LEVEL_PRESETS = [
    { label: 'Full', value: 100 },
    { label: '3/4', value: 75 },
    { label: '1/2', value: 50 },
    { label: '1/4', value: 25 },
  ] as const

  // Helper to convert string | number to number (handles null from PostgreSQL API responses)
  const toNumber = (val: number | string | null | undefined): number | undefined => {
    if (val == null) return undefined
    const num = typeof val === 'string' ? parseFloat(val) : val
    return isNaN(num) ? undefined : num
  }

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    setValue,
    watch,
  } = useForm<FuelRecordFormData>({
    resolver: zodResolver(fuelRecordSchema) as Resolver<FuelRecordFormData>,
    defaultValues: {
      date: formatDateForInput(record?.date),
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
      fuel_type: record?.fuel_type || '',
      is_full_tank: record?.is_full_tank ?? true,
      missed_fillup: record?.missed_fillup ?? false,
      is_hauling: record?.is_hauling ?? false,
      notes: record?.notes || '',
    },
  })

  // Watch for auto-calculation
  const liters = watch('liters')
  const kwh = watch('kwh')
  const pricePerUnit = watch('price_per_unit')

  // Fetch vehicle data to get fuel_type
  useEffect(() => {
    const fetchVehicle = async () => {
      try {
        const response = await api.get(`/vehicles/${vin}`)
        const vehicleData: Vehicle = response.data

        // Store fuel_type and DEF tank capacity for conditional rendering
        setVehicleFuelType(vehicleData.fuel_type || '')
        const cap = vehicleData.def_tank_capacity_liters
        setDefTankCapacity(cap ? (typeof cap === 'string' ? parseFloat(cap) : cap) : 0)

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

      if (!isNaN(volumeNum) && !isNaN(priceNum)) {
        const total = volumeNum * priceNum
        setValue('cost', parseFloat(total.toFixed(2)))
      }
    }
  }, [liters, kwh, pricePerUnit, setValue, isInitialMount])

  const onSubmit = async (data: FuelRecordFormData) => {
    setError(null)

    try {
      // Convert user-entered values to canonical metric (SI) for the API.
      const payload: FuelRecordCreate | FuelRecordUpdate = {
        vin,
        date: data.date,
        odometer_km: toCanonicalKm(data.odometer_km, system) ?? undefined,
        liters: toCanonicalLiters(data.liters, system) ?? undefined,
        propane_liters: toCanonicalLiters(data.propane_liters, system) ?? undefined,
        kwh: data.kwh,
        price_per_unit: priceToCanonical(data.price_per_unit, system, data.price_basis) ?? undefined,
        price_basis: data.price_basis,
        cost: data.cost,
        fuel_type: data.fuel_type,
        is_full_tank: data.is_full_tank,
        missed_fillup: data.missed_fillup,
        is_hauling: data.is_hauling,
        notes: data.notes,
        def_fill_level: data.def_fill_level !== undefined
          ? data.def_fill_level / 100
          : undefined,
      }

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

  const isDiesel = vehicleFuelType?.toLowerCase().includes('diesel')
  const showGallons = !isElectric || isHybrid
  const showKwh = isElectric || isHybrid
  const showPropane = isPropane
  const showFullTankCheckbox = !isElectric
  const showHaulingCheckbox = !isElectric
  const showDefLevel = isDiesel || defTankCapacity > 0

  // Dynamic labels
  const priceLabel = isElectric ? t('fuel.pricePerKwh') : `${t('fuel.pricePer')} ${UnitFormatter.getVolumeUnit(system)}`

  return (
    <FormModalWrapper title={isEdit ? t('fuel.editTitle') : t('fuel.createTitle')} onClose={onClose}>
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
              {t('fuel.priceBasis', { defaultValue: 'Price basis' })}
            </label>
            <select
              id="price_basis"
              {...register('price_basis')}
              className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text border-garage-border"
              disabled={isSubmitting}
              defaultValue={isElectric ? 'per_kwh' : 'per_volume'}
            >
              <option value="per_volume">{t('fuel.priceBasisPerVolume', { defaultValue: 'Per volume (L/gal)' })}</option>
              <option value="per_weight">{t('fuel.priceBasisPerWeight', { defaultValue: 'Per weight (kg/lb)' })}</option>
              <option value="per_kwh">{t('fuel.priceBasisPerKwh', { defaultValue: 'Per kWh' })}</option>
              <option value="per_tank">{t('fuel.priceBasisPerTank', { defaultValue: 'Per tank' })}</option>
            </select>
            <FormError error={errors.price_basis} />
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

          <div>
            <label htmlFor="fuel_type" className="block text-sm font-medium text-garage-text mb-1">
              {t('fuel.fuelType')}
            </label>
            <input
              type="text"
              id="fuel_type"
              {...register('fuel_type')}
              placeholder="Gasoline, Diesel, etc."
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

          {/* DEF Level - shown for diesel vehicles or vehicles with DEF tank capacity */}
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
                        ? 'bg-primary text-white border-primary'
                        : 'bg-garage-bg text-garage-text border-garage-border hover:border-primary'
                    }`}
                  >
                    {preset.label}
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
    </FormModalWrapper>
  )
}
