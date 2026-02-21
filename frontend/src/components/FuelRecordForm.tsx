import { useState, useEffect } from 'react'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { X, Save } from 'lucide-react'
import type { FuelRecord, FuelRecordCreate, FuelRecordUpdate } from '../types/fuel'
import type { Vehicle } from '../types/vehicle'
import { fuelRecordSchema, type FuelRecordFormData } from '../schemas/fuel'
import { FormError } from './FormError'
import api from '../services/api'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitConverter, UnitFormatter } from '../utils/units'

interface FuelRecordFormProps {
  vin: string
  record?: FuelRecord
  onClose: () => void
  onSuccess: () => void
}

export default function FuelRecordForm({ vin, record, onClose, onSuccess }: FuelRecordFormProps) {
  const isEdit = !!record
  const [error, setError] = useState<string | null>(null)
  const [vehicleFuelType, setVehicleFuelType] = useState<string>('')
  const [defTankCapacity, setDefTankCapacity] = useState<number>(0)
  const { system } = useUnitPreference()

  const FILL_LEVEL_PRESETS = [
    { label: 'Full', value: 100 },
    { label: '3/4', value: 75 },
    { label: '1/2', value: 50 },
    { label: '1/4', value: 25 },
  ] as const

  // Helper to format date for input[type="date"] without timezone issues
  const formatDateForInput = (dateString?: string): string => {
    if (!dateString) {
      const now = new Date()
      const year = now.getFullYear()
      const month = String(now.getMonth() + 1).padStart(2, '0')
      const day = String(now.getDate()).padStart(2, '0')
      return `${year}-${month}-${day}`
    }
    // If it's already in YYYY-MM-DD format, return as-is
    if (/^\d{4}-\d{2}-\d{2}$/.test(dateString)) {
      return dateString
    }
    // Otherwise parse and format without timezone conversion
    const date = new Date(dateString + 'T00:00:00')
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
  }

  // Helper to convert string | number to number
  const toNumber = (val: number | string | undefined): number | undefined => {
    if (val === undefined) return undefined
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
      mileage: system === 'metric' && record?.mileage
        ? UnitConverter.milesToKm(toNumber(record.mileage)!) ?? undefined
        : toNumber(record?.mileage),
      gallons: system === 'metric' && record?.gallons
        ? UnitConverter.gallonsToLiters(toNumber(record.gallons)!) ?? undefined
        : toNumber(record?.gallons),
      propane_gallons: system === 'metric' && record?.propane_gallons
        ? UnitConverter.gallonsToLiters(toNumber(record.propane_gallons)!) ?? undefined
        : toNumber(record?.propane_gallons),
      kwh: toNumber(record?.kwh),
      price_per_unit: toNumber(record?.price_per_unit),
      cost: toNumber(record?.cost),
      fuel_type: record?.fuel_type || '',
      is_full_tank: record?.is_full_tank ?? true,
      missed_fillup: record?.missed_fillup ?? false,
      is_hauling: record?.is_hauling ?? false,
      notes: record?.notes || '',
    },
  })

  // Watch for auto-calculation
  const gallons = watch('gallons')
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
        const cap = vehicleData.def_tank_capacity_gallons
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

    // Auto-calculate based on gallons or kwh
    const volumeOrEnergy = gallons || kwh

    if (volumeOrEnergy && pricePerUnit) {
      const volumeNum = typeof volumeOrEnergy === 'number' ? volumeOrEnergy : parseFloat(volumeOrEnergy)
      const priceNum = typeof pricePerUnit === 'number' ? pricePerUnit : parseFloat(pricePerUnit)

      if (!isNaN(volumeNum) && !isNaN(priceNum)) {
        const total = volumeNum * priceNum
        setValue('cost', parseFloat(total.toFixed(2)))
      }
    }
  }, [gallons, kwh, pricePerUnit, setValue, isInitialMount])

  const onSubmit = async (data: FuelRecordFormData) => {
    setError(null)

    try {
      // Convert from user's unit system to imperial (canonical storage format)
      // Mileage must be rounded to integer - backend stores as INT
      const convertedMileage = system === 'metric' && data.mileage
        ? UnitConverter.kmToMiles(data.mileage)
        : data.mileage
      const payload: FuelRecordCreate | FuelRecordUpdate = {
        vin,
        date: data.date,
        mileage: convertedMileage != null ? Math.round(convertedMileage) : undefined,
        gallons: system === 'metric' && data.gallons
          ? UnitConverter.litersToGallons(data.gallons) ?? data.gallons
          : data.gallons,
        propane_gallons: system === 'metric' && data.propane_gallons
          ? UnitConverter.litersToGallons(data.propane_gallons) ?? data.propane_gallons
          : data.propane_gallons,
        kwh: data.kwh,
        price_per_unit: data.price_per_unit,
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
        await api.put(`/vehicles/${vin}/fuel/${record.id}`, payload)
      } else {
        await api.post(`/vehicles/${vin}/fuel`, payload)
      }

      onSuccess()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
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
  const priceLabel = isElectric ? 'Price per kWh' : `Price per ${UnitFormatter.getVolumeUnit(system)}`

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center p-4 z-50">
      <div className="bg-garage-surface rounded-lg shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto border border-garage-border">
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border px-6 py-4 flex justify-between items-center rounded-t-lg">
          <h2 className="text-xl font-semibold text-garage-text">
            {isEdit ? 'Edit Fuel Record' : 'Add Fuel Record'}
          </h2>
          <button
            onClick={onClose}
            className="text-garage-text-muted hover:text-garage-text"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="date" className="block text-sm font-medium text-garage-text mb-1">
                Date <span className="text-danger">*</span>
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
              <label htmlFor="mileage" className="block text-sm font-medium text-garage-text mb-1">
                Mileage ({UnitFormatter.getDistanceUnit(system)})
              </label>
              <input
                type="number"
                id="mileage"
                {...register('mileage', { valueAsNumber: true })}
                min="0"
                placeholder={system === 'imperial' ? '45000' : '72420'}
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.mileage ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
              <FormError error={errors.mileage} />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4">
            {/* Regular Fuel (Gallons) - Show for gas/diesel/hybrid */}
            {showGallons && (
              <div>
                <label htmlFor="gallons" className="block text-sm font-medium text-garage-text mb-1">
                  Volume ({UnitFormatter.getVolumeUnit(system)})
                </label>
                <input
                  type="number"
                  id="gallons"
                  {...register('gallons', { valueAsNumber: true })}
                  min="0"
                  step="0.001"
                  placeholder={system === 'imperial' ? '12.500' : '47.318'}
                  className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.gallons ? 'border-red-500' : 'border-garage-border'
                  }`}
                  disabled={isSubmitting}
                />
                <FormError error={errors.gallons} />
              </div>
            )}

            {/* Electric Energy (kWh) - Show for electric/hybrid */}
            {showKwh && (
              <div>
                <label htmlFor="kwh" className="block text-sm font-medium text-garage-text mb-1">
                  Energy (kWh)
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
                <label htmlFor="propane_gallons" className="block text-sm font-medium text-garage-text mb-1">
                  Propane ({UnitFormatter.getVolumeUnit(system)})
                </label>
                <input
                  type="number"
                  id="propane_gallons"
                  {...register('propane_gallons', { valueAsNumber: true })}
                  min="0"
                  step="0.001"
                  placeholder="0.000"
                  className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.propane_gallons ? 'border-red-500' : 'border-garage-border'
                  }`}
                  disabled={isSubmitting}
                />
                <FormError error={errors.propane_gallons} />
              </div>
            )}

            {/* Price per unit */}
            <div>
              <label htmlFor="price_per_unit" className="block text-sm font-medium text-garage-text mb-1">
                {priceLabel}
              </label>
              <div className="relative">
                <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
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
            <label htmlFor="cost" className="block text-sm font-medium text-garage-text mb-1">
              Total Cost
            </label>
            <div className="relative">
              <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
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
              Auto-calculated when gallons and price are entered
            </p>
          </div>

          <div>
            <label htmlFor="fuel_type" className="block text-sm font-medium text-garage-text mb-1">
              Fuel Type
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
              Auto-populated from vehicle information
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
                  Full Tank Fill-up
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
                {isElectric ? 'Missed Charging Session' : 'Missed Fill-up'}
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
                Towing/Hauling Load
              </label>
            </div>
          )}

          {/* DEF Level - shown for diesel vehicles or vehicles with DEF tank capacity */}
          {showDefLevel && (
            <div className="border border-garage-border rounded-lg p-4 space-y-2">
              <label className="block text-sm font-medium text-garage-text">
                DEF Tank Level
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
                  Clear
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
                Auto-creates a DEF observation record for analytics
              </p>
            </div>
          )}

          {!isElectric && (
            <div className="bg-primary/10 border border-primary rounded-lg p-3">
              <p className="text-sm text-primary">
                <strong>Tip:</strong> MPG is only calculated for full tank fill-ups.
                Check "Full Tank Fill-up" to enable MPG calculation.
              </p>
            </div>
          )}

          {isElectric && (
            <div className="bg-primary/10 border border-primary rounded-lg p-3">
              <p className="text-sm text-primary">
                <strong>Tip:</strong> Efficiency metrics (kWh/100mi) are calculated from charging records.
              </p>
            </div>
          )}

          <div>
            <label htmlFor="notes" className="block text-sm font-medium text-garage-text mb-1">
              Notes
            </label>
            <textarea
              id="notes"
              rows={3}
              {...register('notes')}
              placeholder="Additional notes..."
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
              <span>{isSubmitting ? 'Saving...' : isEdit ? 'Update' : 'Create'}</span>
            </button>

            <button
              type="button"
              onClick={onClose}
              className="btn btn-primary rounded-lg transition-colors"
              disabled={isSubmitting}
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
