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
import { FormError } from './FormError'
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
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
          <h2 className="text-xl font-semibold text-gray-900">
            {isEdit ? 'Edit Billing Entry' : 'Add Billing Entry'}
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-500 transition-colors"
            aria-label="Close"
          >
            <X className="h-6 w-6" />
          </button>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-6">
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
              {error}
            </div>
          )}

          {/* Billing Date */}
          <div>
            <label htmlFor="billing_date" className="block text-sm font-medium text-gray-700">
              Billing Date <span className="text-red-500">*</span>
            </label>
            <input
              type="date"
              id="billing_date"
              {...register('billing_date')}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
            />
            {errors.billing_date && (
              <p className="mt-1 text-sm text-red-600">{errors.billing_date.message}</p>
            )}
          </div>

          {/* Monthly Rate */}
          <div>
            <label htmlFor="monthly_rate" className="block text-sm font-medium text-gray-700">
              Monthly Rate ($)
            </label>
            <input
              type="number"
              id="monthly_rate"
              step="0.01"
              {...register('monthly_rate')}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
              placeholder="0.00"
            />
            {errors.monthly_rate && (
              <p className="mt-1 text-sm text-red-600">{errors.monthly_rate.message}</p>
            )}
          </div>

          {/* Utilities Grid */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Electric */}
            <div>
              <label htmlFor="electric" className="block text-sm font-medium text-gray-700">
                Electric ($)
              </label>
              <input
                type="number"
                id="electric"
                step="0.01"
                {...register('electric')}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                placeholder="0.00"
              />
              {errors.electric && (
                <p className="mt-1 text-sm text-red-600">{errors.electric.message}</p>
              )}
            </div>

            {/* Water */}
            <div>
              <label htmlFor="water" className="block text-sm font-medium text-gray-700">
                Water ($)
              </label>
              <input
                type="number"
                id="water"
                step="0.01"
                {...register('water')}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                placeholder="0.00"
              />
              {errors.water && (
                <p className="mt-1 text-sm text-red-600">{errors.water.message}</p>
              )}
            </div>

            {/* Waste */}
            <div>
              <label htmlFor="waste" className="block text-sm font-medium text-gray-700">
                Waste ($)
              </label>
              <input
                type="number"
                id="waste"
                step="0.01"
                {...register('waste')}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                placeholder="0.00"
              />
              {errors.waste && (
                <p className="mt-1 text-sm text-red-600">{errors.waste.message}</p>
              )}
            </div>
          </div>

          {/* Total (Auto-calculated) */}
          <div>
            <label htmlFor="total" className="block text-sm font-medium text-gray-700">
              Total ($)
            </label>
            <input
              type="number"
              id="total"
              step="0.01"
              {...register('total')}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm bg-gray-50"
              placeholder="Auto-calculated"
              readOnly
            />
            {errors.total && (
              <p className="mt-1 text-sm text-red-600">{errors.total.message}</p>
            )}
            <p className="mt-1 text-xs text-gray-500">
              Automatically calculated from Monthly Rate + Electric + Water + Waste
            </p>
          </div>

          {/* Notes */}
          <div>
            <label htmlFor="notes" className="block text-sm font-medium text-gray-700">
              Notes
            </label>
            <textarea
              id="notes"
              rows={4}
              {...register('notes')}
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
              placeholder="Any additional notes about this billing period..."
            />
            {errors.notes && (
              <p className="mt-1 text-sm text-red-600">{errors.notes.message}</p>
            )}
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-4 border-t border-gray-200">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-md shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              <Save className="h-4 w-4" />
              {isSubmitting ? 'Saving...' : 'Save Billing Entry'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
