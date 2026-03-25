import { useTranslation } from 'react-i18next'
import { useState, useEffect } from 'react'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Save } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import type {
  SpotRentalBilling,
  SpotRentalBillingCreate,
  SpotRentalBillingUpdate
} from '../types/spotRental'
import {
  spotRentalBillingSchema,
  type SpotRentalBillingFormData
} from '../schemas/spotRentalBilling'
import { useCreateBillingEntry, useUpdateBillingEntry } from '../hooks/queries/useSpotRentals'
import { formatDateForInput } from '../utils/dateUtils'

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
  const { t } = useTranslation('forms')
  const isEdit = !!billing
  const [error, setError] = useState<string | null>(null)
  const createMutation = useCreateBillingEntry(vin, rentalId)
  const updateMutation = useUpdateBillingEntry(vin, rentalId)

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
      monthly_rate: billing?.monthly_rate != null ? Number(billing.monthly_rate) : undefined,
      electric: billing?.electric != null ? Number(billing.electric) : undefined,
      water: billing?.water != null ? Number(billing.water) : undefined,
      waste: billing?.waste != null ? Number(billing.waste) : undefined,
      total: billing?.total != null ? Number(billing.total) : undefined,
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
        await updateMutation.mutateAsync({ id: billing.id, ...payload })
      } else {
        await createMutation.mutateAsync(payload as SpotRentalBillingCreate)
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
          setError(t('billing.spotRentalNotFound'))
        } else {
          setError(t('billing.failedToSave'))
        }
      } else {
        setError(t('billing.failedToSave'))
      }
    }
  }

  return (
    <FormModalWrapper title={isEdit ? t('billing.editTitle') : t('billing.createTitle')} onClose={onClose}>
        <form onSubmit={handleSubmit(onSubmit as Parameters<typeof handleSubmit>[0])} className="p-6 space-y-6">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          {/* Billing Date */}
          <div>
            <label htmlFor="billing_date" className="block text-sm font-medium text-garage-text mb-1">
              {t('billing.billingDate')} <span className="text-danger">*</span>
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
              {t('spotRental.monthlyRate')}
            </label>
            <div className="relative">
              <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
              <input
                type="number"
                id="monthly_rate"
                step="0.01"
                {...register('monthly_rate', { valueAsNumber: true })}
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
                  {...register('electric', { valueAsNumber: true })}
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
                  {...register('water', { valueAsNumber: true })}
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
                  {...register('waste', { valueAsNumber: true })}
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
              {t('common:total')}
            </label>
            <div className="relative">
              <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
              <input
                type="number"
                id="total"
                step="0.01"
                {...register('total', { valueAsNumber: true })}
                placeholder="Auto-calculated"
                className="w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg/50 text-garage-text border-garage-border"
                readOnly
              />
            </div>
            {errors.total && (
              <p className="mt-1 text-sm text-danger">{errors.total.message}</p>
            )}
            <p className="mt-1 text-xs text-garage-text-muted">
              {t('billing.autoCalculatedHint')}
            </p>
          </div>

          {/* Notes */}
          <div>
            <label htmlFor="notes" className="block text-sm font-medium text-garage-text mb-1">
              {t('common:notes')}
            </label>
            <textarea
              id="notes"
              rows={4}
              {...register('notes')}
              placeholder={t('billing.notesPlaceholder')}
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
              <span>{isSubmitting ? t('common:saving') : isEdit ? t('common:update') : t('common:create')}</span>
            </button>

            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="btn btn-primary rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {t('common:cancel')}
            </button>
          </div>
        </form>
    </FormModalWrapper>
  )
}
