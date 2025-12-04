import { useState, useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { X, Save } from 'lucide-react'
import type { FuelRecord, FuelRecordCreate, FuelRecordUpdate } from '../types/fuel'
import type { Vehicle } from '../types/vehicle'
import { fuelRecordSchema, type FuelRecordFormData } from '../schemas/fuel'
import { FormError } from './FormError'
import api from '../services/api'

interface FuelRecordFormProps {
  vin: string
  record?: FuelRecord
  onClose: () => void
  onSuccess: () => void
}

export default function FuelRecordForm({ vin, record, onClose, onSuccess }: FuelRecordFormProps) {
  const isEdit = !!record
  const [error, setError] = useState<string | null>(null)

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

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    setValue,
    watch,
  } = useForm<FuelRecordFormData>({
    resolver: zodResolver(fuelRecordSchema),
    defaultValues: {
      date: formatDateForInput(record?.date),
      mileage: record?.mileage ?? undefined,
      gallons: record?.gallons ?? undefined,
      propane_gallons: record?.propane_gallons ?? undefined,
      price_per_unit: record?.price_per_unit ?? undefined,
      cost: record?.cost ?? undefined,
      fuel_type: record?.fuel_type || '',
      is_full_tank: record?.is_full_tank ?? true,
      missed_fillup: record?.missed_fillup ?? false,
      is_hauling: record?.is_hauling ?? false,
      notes: record?.notes || '',
    },
  })

  // Watch gallons and price_per_unit for auto-calculation
  const gallons = watch('gallons')
  const pricePerUnit = watch('price_per_unit')

  // Fetch vehicle data to get fuel_type
  useEffect(() => {
    const fetchVehicle = async () => {
      try {
        const response = await api.get(`/vehicles/${vin}`)
        const vehicleData: Vehicle = response.data
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

  // Auto-calculate total cost when gallons and price per unit change
  useEffect(() => {
    if (gallons && pricePerUnit) {
      const gallonsNum = typeof gallons === 'number' ? gallons : parseFloat(gallons)
      const priceNum = typeof pricePerUnit === 'number' ? pricePerUnit : parseFloat(pricePerUnit)

      if (!isNaN(gallonsNum) && !isNaN(priceNum)) {
        const total = gallonsNum * priceNum
        setValue('cost', parseFloat(total.toFixed(2)))
      }
    }
  }, [gallons, pricePerUnit, setValue])

  const onSubmit = async (data: FuelRecordFormData) => {
    setError(null)

    try {
      // Zod has already validated and coerced all numeric fields - no parseFloat/parseInt/isNaN needed!
      const payload: FuelRecordCreate | FuelRecordUpdate = {
        vin,
        date: data.date,
        mileage: data.mileage,
        gallons: data.gallons,
        propane_gallons: data.propane_gallons,
        price_per_unit: data.price_per_unit,
        cost: data.cost,
        fuel_type: data.fuel_type,
        is_full_tank: data.is_full_tank,
        missed_fillup: data.missed_fillup,
        is_hauling: data.is_hauling,
        notes: data.notes,
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
                Mileage
              </label>
              <input
                type="number"
                id="mileage"
                {...register('mileage')}
                min="0"
                placeholder="45000"
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.mileage ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
              <FormError error={errors.mileage} />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div>
              <label htmlFor="gallons" className="block text-sm font-medium text-garage-text mb-1">
                Gallons
              </label>
              <input
                type="number"
                id="gallons"
                {...register('gallons')}
                min="0"
                step="0.001"
                placeholder="12.500"
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.gallons ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
              <FormError error={errors.gallons} />
            </div>

            <div>
              <label htmlFor="propane_gallons" className="block text-sm font-medium text-garage-text mb-1">
                Propane (gal)
              </label>
              <input
                type="number"
                id="propane_gallons"
                {...register('propane_gallons')}
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

            <div>
              <label htmlFor="price_per_unit" className="block text-sm font-medium text-garage-text mb-1">
                Price per Gallon
              </label>
              <div className="relative">
                <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
                <input
                  type="number"
                  id="price_per_unit"
                  {...register('price_per_unit')}
                  min="0"
                  step="0.001"
                  placeholder="3.499"
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
                {...register('cost')}
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

            <div className="flex items-center">
              <input
                type="checkbox"
                id="missed_fillup"
                {...register('missed_fillup')}
                className="h-4 w-4 text-primary focus:ring-primary border-garage-border rounded bg-garage-bg"
                disabled={isSubmitting}
              />
              <label htmlFor="missed_fillup" className="ml-2 block text-sm text-garage-text">
                Missed Fill-up
              </label>
            </div>
          </div>

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

          <div className="bg-primary/10 border border-primary rounded-lg p-3">
            <p className="text-sm text-primary">
              <strong>Tip:</strong> MPG is only calculated for full tank fill-ups.
              Check "Full Tank Fill-up" to enable MPG calculation.
            </p>
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
