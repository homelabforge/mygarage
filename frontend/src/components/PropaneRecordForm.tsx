import { useState, useEffect } from 'react'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { X, Save } from 'lucide-react'
import type { FuelRecord, FuelRecordCreate, FuelRecordUpdate } from '../types/fuel'
import { propaneRecordSchema, type PropaneRecordFormData } from '../schemas/propane'
import { FormError } from './FormError'
import api from '../services/api'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitConverter, UnitFormatter } from '../utils/units'

const TANK_SIZES = [
  { label: '20 lb (portable)', value: 20, gallons: 4.7 },
  { label: '33 lb (portable)', value: 33, gallons: 7.8 },
  { label: '100 lb (RV)', value: 100, gallons: 23.6 },
  { label: '420 lb (RV)', value: 420, gallons: 99.1 },
] as const

interface PropaneRecordFormProps {
  vin: string
  record?: FuelRecord
  onClose: () => void
  onSuccess: () => void
}

export default function PropaneRecordForm({
  vin,
  record,
  onClose,
  onSuccess
}: PropaneRecordFormProps) {
  const isEdit = !!record
  const [error, setError] = useState<string | null>(null)
  const { system } = useUnitPreference()

  const formatDateForInput = (dateString?: string): string => {
    if (!dateString) {
      const now = new Date()
      const year = now.getFullYear()
      const month = String(now.getMonth() + 1).padStart(2, '0')
      const day = String(now.getDate()).padStart(2, '0')
      return `${year}-${month}-${day}`
    }
    if (/^\d{4}-\d{2}-\d{2}$/.test(dateString)) {
      return dateString
    }
    const date = new Date(dateString + 'T00:00:00')
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
  }

  // Extract vendor from notes if it was stored there
  const extractVendor = (notes?: string): string => {
    if (!notes) return ''
    const match = notes.match(/^Vendor: (.+?)(?:\n|$)/)
    return match ? match[1] : ''
  }

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    setValue,
    watch,
  } = useForm<PropaneRecordFormData>({
    resolver: zodResolver(propaneRecordSchema) as Resolver<PropaneRecordFormData>,
    defaultValues: {
      date: formatDateForInput(record?.date),
      propane_gallons: (() => {
        if (!record?.propane_gallons) return undefined
        const gallons = typeof record.propane_gallons === 'string'
          ? parseFloat(record.propane_gallons)
          : record.propane_gallons
        if (isNaN(gallons)) return undefined
        return system === 'metric'
          ? UnitConverter.gallonsToLiters(gallons) ?? undefined
          : gallons
      })(),
      price_per_unit: (() => {
        if (!record?.price_per_unit) return undefined
        const price = typeof record.price_per_unit === 'string'
          ? parseFloat(record.price_per_unit)
          : record.price_per_unit
        return isNaN(price) ? undefined : price
      })(),
      cost: (() => {
        if (!record?.cost) return undefined
        const cost = typeof record.cost === 'string'
          ? parseFloat(record.cost)
          : record.cost
        return isNaN(cost) ? undefined : cost
      })(),
      vendor: extractVendor(record?.notes) || '',
      notes: record?.notes?.replace(/^Vendor: .+?\n/, '') || '',
      tank_size_lb: record?.tank_size_lb ? parseFloat(record.tank_size_lb.toString()) : undefined,
      tank_quantity: record?.tank_quantity ?? undefined,
    },
  })

  // Watch gallons and price for auto-calculation
  const gallons = watch('propane_gallons')
  const pricePerUnit = watch('price_per_unit')
  const tankSizeLb = watch('tank_size_lb')
  const tankQuantity = watch('tank_quantity')

  const [isInitialMount, setIsInitialMount] = useState(true)

  useEffect(() => {
    if (isInitialMount) {
      setIsInitialMount(false)
      return
    }

    if (gallons && pricePerUnit) {
      const gallonsNum = typeof gallons === 'number' ? gallons : parseFloat(String(gallons))
      const priceNum = typeof pricePerUnit === 'number' ? pricePerUnit : parseFloat(String(pricePerUnit))

      if (!isNaN(gallonsNum) && !isNaN(priceNum)) {
        const total = gallonsNum * priceNum
        setValue('cost', parseFloat(total.toFixed(2)))
      }
    }
  }, [gallons, pricePerUnit, setValue, isInitialMount])

  // Auto-calculate propane_gallons from tank data
  useEffect(() => {
    if (isInitialMount) return

    if (tankSizeLb && tankQuantity) {
      const calculated = (parseFloat(tankSizeLb.toString()) / 4.24) * tankQuantity
      const convertedValue = system === 'metric'
        ? UnitConverter.gallonsToLiters(calculated)
        : calculated
      if (convertedValue !== null) {
        setValue('propane_gallons', parseFloat(convertedValue.toFixed(3)))
      }
    }
  }, [tankSizeLb, tankQuantity, system, setValue, isInitialMount])

  const onSubmit = async (data: PropaneRecordFormData) => {
    setError(null)

    try {
      // Construct notes with vendor prefix if vendor provided
      let finalNotes = data.notes || ''
      if (data.vendor && data.vendor.trim()) {
        finalNotes = `Vendor: ${data.vendor.trim()}\n${finalNotes}`.trim()
      }

      // We're using fuel_records table but ONLY propane_gallons field
      const payload: FuelRecordCreate | FuelRecordUpdate = {
        vin,
        date: data.date,
        mileage: undefined,  // Never set for propane
        gallons: undefined,  // Never set for propane
        propane_gallons: system === 'metric' && data.propane_gallons
          ? UnitConverter.litersToGallons(data.propane_gallons) ?? data.propane_gallons
          : data.propane_gallons,
        tank_size_lb: data.tank_size_lb,
        tank_quantity: data.tank_quantity,
        price_per_unit: data.price_per_unit,
        cost: data.cost,
        fuel_type: 'Propane',  // Always propane
        is_full_tank: false,  // Not relevant for propane
        missed_fillup: false,
        is_hauling: false,
        notes: finalNotes || undefined,
      }

      if (isEdit && record) {
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

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center p-4 z-50">
      <div className="bg-garage-surface rounded-lg shadow-2xl max-w-lg w-full border border-garage-border">
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border px-6 py-4 flex justify-between items-center rounded-t-lg">
          <h2 className="text-xl font-semibold text-garage-text">
            {isEdit ? 'Edit Propane Record' : 'Add Propane Record'}
          </h2>
          <button onClick={onClose} className="text-garage-text-muted hover:text-garage-text">
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
          </div>

          {/* Tank Information Section */}
          <div className="border-t border-garage-border pt-4 mt-4">
            <h3 className="text-sm font-medium text-garage-text mb-3">
              Tank Information (Optional)
            </h3>

            <div className="grid grid-cols-2 gap-4">
              {/* Tank Size */}
              <div>
                <label htmlFor="tank_size_lb" className="block text-sm font-medium text-garage-text mb-1">
                  Tank Size
                </label>
                <select
                  id="tank_size_lb"
                  {...register('tank_size_lb', { valueAsNumber: true })}
                  className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text border-garage-border"
                  disabled={isSubmitting}
                >
                  <option value="">Select tank size...</option>
                  {TANK_SIZES.map(tank => (
                    <option key={tank.value} value={tank.value}>
                      {tank.label}
                    </option>
                  ))}
                </select>
              </div>

              {/* Tank Quantity */}
              <div>
                <label htmlFor="tank_quantity" className="block text-sm font-medium text-garage-text mb-1">
                  Number of Tanks
                </label>
                <input
                  type="number"
                  id="tank_quantity"
                  {...register('tank_quantity', { valueAsNumber: true })}
                  min="1"
                  step="1"
                  className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.tank_quantity ? 'border-red-500' : 'border-garage-border'
                  }`}
                  disabled={isSubmitting}
                />
                <FormError error={errors.tank_quantity} />
              </div>
            </div>

            {/* Calculated Gallons Hint */}
            {tankSizeLb && tankQuantity && (
              <p className="text-xs text-garage-text-muted mt-2">
                Auto-calculated: {((parseFloat(tankSizeLb.toString()) / 4.24) * tankQuantity).toFixed(2)} gallons
                {system === 'metric' && UnitConverter.gallonsToLiters((parseFloat(tankSizeLb.toString()) / 4.24) * tankQuantity) && (
                  ` (${UnitConverter.gallonsToLiters((parseFloat(tankSizeLb.toString()) / 4.24) * tankQuantity)?.toFixed(2)} L)`
                )}
              </p>
            )}
          </div>

          {/* Propane Gallons Field */}
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
              placeholder={system === 'imperial' ? '10.500' : '39.750'}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.propane_gallons ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <FormError error={errors.propane_gallons} />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="price_per_unit" className="block text-sm font-medium text-garage-text mb-1">
                Price per {UnitFormatter.getVolumeUnit(system)}
              </label>
              <div className="relative">
                <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
                <input
                  type="number"
                  id="price_per_unit"
                  {...register('price_per_unit', { valueAsNumber: true })}
                  min="0"
                  step="0.001"
                  placeholder={system === 'imperial' ? '2.899' : '0.766'}
                  className={`w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.price_per_unit ? 'border-red-500' : 'border-garage-border'
                  }`}
                  disabled={isSubmitting}
                />
              </div>
              <FormError error={errors.price_per_unit} />
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
                  placeholder="30.44"
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
          </div>

          <div>
            <label htmlFor="vendor" className="block text-sm font-medium text-garage-text mb-1">
              Vendor/Location
            </label>
            <input
              type="text"
              id="vendor"
              {...register('vendor')}
              placeholder="e.g., AmeriGas, U-Haul Propane"
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.vendor ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <FormError error={errors.vendor} />
          </div>

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
