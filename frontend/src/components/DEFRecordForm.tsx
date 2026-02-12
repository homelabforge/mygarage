import { useState, useEffect } from 'react'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { X, Save } from 'lucide-react'
import type { DEFRecord } from '../types/def'
import { defRecordSchema, type DefRecordFormData } from '../schemas/def'
import { FormError } from './FormError'
import api from '../services/api'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitConverter, UnitFormatter } from '../utils/units'

const FILL_LEVEL_PRESETS = [
  { label: 'Full', value: 100 },
  { label: '3/4', value: 75 },
  { label: '1/2', value: 50 },
  { label: '1/4', value: 25 },
] as const

const SOURCE_SUGGESTIONS = [
  'Truck Stop / Station Nozzle',
  'Auto Parts Store',
  'Walmart',
  'Amazon',
  'Other Store',
] as const

const BRAND_SUGGESTIONS = [
  'BlueDEF',
  'Peak Blue',
  'Prestone',
  'Mopar',
  'Fleetguard',
] as const

interface DEFRecordFormProps {
  vin: string
  record?: DEFRecord
  onClose: () => void
  onSuccess: () => void
}

export default function DEFRecordForm({
  vin,
  record,
  onClose,
  onSuccess
}: DEFRecordFormProps) {
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

  const parseDecimal = (val?: number | string): number | undefined => {
    if (val === undefined || val === null) return undefined
    const num = typeof val === 'string' ? parseFloat(val) : val
    return isNaN(num) ? undefined : num
  }

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    setValue,
    watch,
  } = useForm<DefRecordFormData>({
    resolver: zodResolver(defRecordSchema) as Resolver<DefRecordFormData>,
    defaultValues: {
      date: formatDateForInput(record?.date),
      mileage: record?.mileage ?? undefined,
      gallons: (() => {
        const g = parseDecimal(record?.gallons)
        if (g === undefined) return undefined
        return system === 'metric' ? (UnitConverter.gallonsToLiters(g) ?? g) : g
      })(),
      price_per_unit: parseDecimal(record?.price_per_unit),
      cost: parseDecimal(record?.cost),
      fill_level: (() => {
        const fl = parseDecimal(record?.fill_level)
        return fl !== undefined ? fl * 100 : undefined // Store as 0.00-1.00, display as 0-100
      })(),
      source: record?.source || '',
      brand: record?.brand || '',
      notes: record?.notes || '',
    },
  })

  // Watch gallons and price for auto-calculation
  const gallons = watch('gallons')
  const pricePerUnit = watch('price_per_unit')

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

  const onSubmit = async (data: DefRecordFormData) => {
    setError(null)

    try {
      const payload = {
        vin,
        date: data.date,
        mileage: data.mileage,
        gallons: system === 'metric' && data.gallons
          ? UnitConverter.litersToGallons(data.gallons) ?? data.gallons
          : data.gallons,
        price_per_unit: data.price_per_unit,
        cost: data.cost,
        fill_level: data.fill_level !== undefined ? data.fill_level / 100 : undefined, // Convert % to 0.00-1.00
        source: data.source || undefined,
        brand: data.brand || undefined,
        notes: data.notes || undefined,
      }

      if (isEdit && record) {
        await api.put(`/vehicles/${vin}/def/${record.id}`, payload)
      } else {
        await api.post(`/vehicles/${vin}/def`, payload)
      }

      onSuccess()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    }
  }

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center p-4 z-50">
      <div className="bg-garage-surface rounded-lg shadow-2xl max-w-lg w-full border border-garage-border max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border px-6 py-4 flex justify-between items-center rounded-t-lg">
          <h2 className="text-xl font-semibold text-garage-text">
            {isEdit ? 'Edit DEF Record' : 'Add DEF Record'}
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

            <div>
              <label htmlFor="mileage" className="block text-sm font-medium text-garage-text mb-1">
                Mileage
              </label>
              <input
                type="number"
                id="mileage"
                {...register('mileage', { valueAsNumber: true })}
                min="0"
                step="1"
                placeholder="55000"
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.mileage ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
              <FormError error={errors.mileage} />
            </div>
          </div>

          {/* Fill Level */}
          <div>
            <label className="block text-sm font-medium text-garage-text mb-2">
              Tank Level After Fill
            </label>
            <div className="flex gap-2 mb-2">
              {FILL_LEVEL_PRESETS.map(preset => (
                <button
                  key={preset.value}
                  type="button"
                  onClick={() => setValue('fill_level', preset.value)}
                  className={`px-3 py-1.5 text-sm rounded-md border transition-colors ${
                    watch('fill_level') === preset.value
                      ? 'bg-primary text-white border-primary'
                      : 'bg-garage-bg text-garage-text border-garage-border hover:border-primary'
                  }`}
                >
                  {preset.label}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <input
                type="number"
                id="fill_level"
                {...register('fill_level', { valueAsNumber: true })}
                min="0"
                max="100"
                step="1"
                placeholder="75"
                className={`w-24 px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.fill_level ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
              <span className="text-sm text-garage-text-muted">%</span>
              {/* Visual gauge */}
              {watch('fill_level') !== undefined && !isNaN(watch('fill_level') ?? NaN) && (
                <div className="flex-1 h-4 bg-garage-bg rounded-full border border-garage-border overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${
                      (watch('fill_level') ?? 0) > 50 ? 'bg-success' :
                      (watch('fill_level') ?? 0) > 25 ? 'bg-warning' : 'bg-danger'
                    }`}
                    style={{ width: `${Math.min(100, Math.max(0, watch('fill_level') ?? 0))}%` }}
                  />
                </div>
              )}
            </div>
            <FormError error={errors.fill_level} />
          </div>

          {/* Volume and Pricing */}
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label htmlFor="gallons" className="block text-sm font-medium text-garage-text mb-1">
                {UnitFormatter.getVolumeUnit(system)}
              </label>
              <input
                type="number"
                id="gallons"
                {...register('gallons', { valueAsNumber: true })}
                min="0"
                step="0.001"
                placeholder="5.500"
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.gallons ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
              <FormError error={errors.gallons} />
            </div>

            <div>
              <label htmlFor="price_per_unit" className="block text-sm font-medium text-garage-text mb-1">
                Price/{UnitFormatter.getVolumeUnit(system)}
              </label>
              <div className="relative">
                <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
                <input
                  type="number"
                  id="price_per_unit"
                  {...register('price_per_unit', { valueAsNumber: true })}
                  min="0"
                  step="0.001"
                  placeholder="4.500"
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
                  placeholder="24.75"
                  className={`w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.cost ? 'border-red-500' : 'border-garage-border'
                  }`}
                  disabled={isSubmitting}
                />
              </div>
              <FormError error={errors.cost} />
              <p className="text-xs text-garage-text-muted mt-1">Auto-calculated</p>
            </div>
          </div>

          {/* Source */}
          <div>
            <label htmlFor="source" className="block text-sm font-medium text-garage-text mb-1">
              Where Purchased
            </label>
            <input
              type="text"
              id="source"
              list="source-suggestions"
              {...register('source')}
              placeholder="e.g., Truck Stop / Station Nozzle"
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.source ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <datalist id="source-suggestions">
              {SOURCE_SUGGESTIONS.map(s => (
                <option key={s} value={s} />
              ))}
            </datalist>
            <FormError error={errors.source} />
          </div>

          {/* Brand */}
          <div>
            <label htmlFor="brand" className="block text-sm font-medium text-garage-text mb-1">
              Brand
            </label>
            <input
              type="text"
              id="brand"
              list="brand-suggestions"
              {...register('brand')}
              placeholder="e.g., BlueDEF"
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.brand ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <datalist id="brand-suggestions">
              {BRAND_SUGGESTIONS.map(b => (
                <option key={b} value={b} />
              ))}
            </datalist>
            <FormError error={errors.brand} />
          </div>

          {/* Notes */}
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
