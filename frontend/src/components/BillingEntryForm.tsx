import { useState, useEffect } from 'react'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { X, Save } from 'lucide-react'
import type {
  SpotRentalBilling,
  SpotRentalBillingCreate,
  SpotRentalBillingUpdate
} from '../types/spotRental'
import {
  spotRentalBillingSchema,
  type SpotRentalBillingFormData
} from '../schemas/spotRentalBilling'
import api from '../services/api'

interface BillingEntryFormProps {
  vin: string
  rentalId: number
  billing?: SpotRentalBilling
  onClose: () => void
  onSuccess: () => void
}

export default function BillingEntryForm({
  vin,
  rentalId,
  billing,
  onClose,
  onSuccess
}: BillingEntryFormProps) {
  const isEdit = !!billing
  const [error, setError] = useState<string | null>(null)

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

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    formState: { errors, isSubmitting }
  } = useForm<SpotRentalBillingFormData>({
    resolver: zodResolver(spotRentalBillingSchema) as Resolver<SpotRentalBillingFormData>,
    defaultValues: {
      billing_date: formatDateForInput(billing?.billing_date),
      monthly_rate: billing?.monthly_rate ?? undefined,
      electric: billing?.electric ?? undefined,
      water: billing?.water ?? undefined,
      waste: billing?.waste ?? undefined,
      total: billing?.total ?? undefined,
      notes: billing?.notes ?? undefined
    }
  })

  // Auto-calculate total from monthly_rate + electric + water + waste
  const monthlyRate = watch('monthly_rate')
  const electric = watch('electric')
  const water = watch('water')
  const waste = watch('waste')

  useEffect(() => {
    const monthly = monthlyRate || 0
    const elec = electric || 0
    const wat = water || 0
    const wst = waste || 0
    const calculatedTotal = monthly + elec + wat + wst

    // Only set if there's a meaningful value
    if (calculatedTotal > 0) {
      setValue('total', calculatedTotal)
    }
  }, [monthlyRate, electric, water, waste, setValue])

  const onSubmit = async (data: SpotRentalBillingFormData) => {
    try {
      setError(null)

      const payload: SpotRentalBillingCreate | SpotRentalBillingUpdate = {
        billing_date: data.billing_date,
        monthly_rate: data.monthly_rate ?? null,
        electric: data.electric ?? null,
        water: data.water ?? null,
        waste: data.waste ?? null,
        total: data.total ?? null,
        notes: data.notes ?? null
      }

      if (isEdit && billing) {
        await api.put(
          `/vehicles/${vin}/spot-rentals/${rentalId}/billings/${billing.id}`,
          payload
        )
      } else {
        await api.post(
          `/vehicles/${vin}/spot-rentals/${rentalId}/billings`,
          payload
        )
      }

      onSuccess()
      onClose()
    } catch (err: unknown) {
      console.error('Failed to save billing entry:', err)
      if (err && typeof err === 'object' && 'response' in err) {
        const axiosError = err as {
          response?: { data?: { detail?: string }; status?: number }
        }
        if (axiosError.response?.data?.detail) {
          setError(axiosError.response.data.detail)
        } else if (axiosError.response?.status === 404) {
          setError('Spot rental not found')
        } else {
          setError('Failed to save billing entry. Please try again.')
        }
      } else {
        setError('Failed to save billing entry. Please try again.')
      }
    }
  }

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center p-4 z-50">
      <div className="bg-garage-surface rounded-lg shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto border border-garage-border">
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border px-6 py-4 flex items-center justify-between rounded-t-lg">
          <h2 className="text-xl font-semibold text-garage-text">
            {isEdit ? 'Edit Billing Entry' : 'Add Billing Entry'}
          </h2>
          <button
            onClick={onClose}
            className="text-garage-text-muted hover:text-garage-text transition-colors"
            aria-label="Close"
          >
            <X className="h-6 w-6" />
          </button>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-6">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          {/* Billing Date */}
          <div>
            <label htmlFor="billing_date" className="block text-sm font-medium text-garage-text mb-1">
              Billing Date <span className="text-danger">*</span>
            </label>
            <input
              type="date"
              id="billing_date"
              {...register('billing_date')}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.billing_date ? 'border-red-500' : 'border-garage-border'
              }`}
            />
            {errors.billing_date && (
              <p className="mt-1 text-sm text-danger">{errors.billing_date.message}</p>
            )}
          </div>

          {/* Monthly Rate */}
          <div>
            <label htmlFor="monthly_rate" className="block text-sm font-medium text-garage-text mb-1">
              Monthly Rate
            </label>
            <div className="relative">
              <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
              <input
                type="number"
                id="monthly_rate"
                step="0.01"
                {...register('monthly_rate')}
                placeholder="0.00"
                className={`w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.monthly_rate ? 'border-red-500' : 'border-garage-border'
                }`}
              />
            </div>
            {errors.monthly_rate && (
              <p className="mt-1 text-sm text-danger">{errors.monthly_rate.message}</p>
            )}
          </div>

          {/* Utilities Grid */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Electric */}
            <div>
              <label htmlFor="electric" className="block text-sm font-medium text-garage-text mb-1">
                Electric
              </label>
              <div className="relative">
                <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
                <input
                  type="number"
                  id="electric"
                  step="0.01"
                  {...register('electric')}
                  placeholder="0.00"
                  className={`w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.electric ? 'border-red-500' : 'border-garage-border'
                  }`}
                />
              </div>
              {errors.electric && (
                <p className="mt-1 text-sm text-danger">{errors.electric.message}</p>
              )}
            </div>

            {/* Water */}
            <div>
              <label htmlFor="water" className="block text-sm font-medium text-garage-text mb-1">
                Water
              </label>
              <div className="relative">
                <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
                <input
                  type="number"
                  id="water"
                  step="0.01"
                  {...register('water')}
                  placeholder="0.00"
                  className={`w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.water ? 'border-red-500' : 'border-garage-border'
                  }`}
                />
              </div>
              {errors.water && (
                <p className="mt-1 text-sm text-danger">{errors.water.message}</p>
              )}
            </div>

            {/* Waste */}
            <div>
              <label htmlFor="waste" className="block text-sm font-medium text-garage-text mb-1">
                Waste
              </label>
              <div className="relative">
                <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
                <input
                  type="number"
                  id="waste"
                  step="0.01"
                  {...register('waste')}
                  placeholder="0.00"
                  className={`w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.waste ? 'border-red-500' : 'border-garage-border'
                  }`}
                />
              </div>
              {errors.waste && (
                <p className="mt-1 text-sm text-danger">{errors.waste.message}</p>
              )}
            </div>
          </div>

          {/* Total (Auto-calculated) */}
          <div>
            <label htmlFor="total" className="block text-sm font-medium text-garage-text mb-1">
              Total
            </label>
            <div className="relative">
              <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
              <input
                type="number"
                id="total"
                step="0.01"
                {...register('total')}
                placeholder="Auto-calculated"
                className="w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg/50 text-garage-text border-garage-border"
                readOnly
              />
            </div>
            {errors.total && (
              <p className="mt-1 text-sm text-danger">{errors.total.message}</p>
            )}
            <p className="mt-1 text-xs text-garage-text-muted">
              Automatically calculated from Monthly Rate + Electric + Water + Waste
            </p>
          </div>

          {/* Notes */}
          <div>
            <label htmlFor="notes" className="block text-sm font-medium text-garage-text mb-1">
              Notes
            </label>
            <textarea
              id="notes"
              rows={4}
              {...register('notes')}
              placeholder="Any additional notes about this billing period..."
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.notes ? 'border-red-500' : 'border-garage-border'
              }`}
            />
            {errors.notes && (
              <p className="mt-1 text-sm text-danger">{errors.notes.message}</p>
            )}
          </div>

          {/* Actions */}
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
              disabled={isSubmitting}
              className="btn btn-primary rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
