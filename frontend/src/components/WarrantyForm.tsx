import { useTranslation } from 'react-i18next'
import { useCallback } from 'react'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Save } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import type { WarrantyRecord, WarrantyRecordCreate, WarrantyRecordUpdate } from '../types/warranty'
import { warrantySchema, type WarrantyFormData, WARRANTY_TYPES } from '../schemas/warranty'
import { FormError } from './FormError'
import { useCreateWarrantyRecord, useUpdateWarrantyRecord } from '../hooks/queries/useWarrantyRecords'
import { formatDateForInput } from '../utils/dateUtils'
import { useFormSubmit } from '../hooks/useFormSubmit'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitConverter, UnitFormatter } from '../utils/units'
import { toCanonicalKm } from '../utils/decimalSafe'

interface WarrantyFormProps {
  vin: string
  record?: WarrantyRecord
  onClose: () => void
  onSuccess: () => void
}

export default function WarrantyForm({ vin, record, onClose, onSuccess }: WarrantyFormProps) {
  const { t } = useTranslation('forms')
  const isEdit = !!record
  const createMutation = useCreateWarrantyRecord(vin)
  const updateMutation = useUpdateWarrantyRecord(vin)
  const { system } = useUnitPreference()

  const submitFn = useCallback(async (data: WarrantyFormData) => {
    // Convert user-entered mileage limit to canonical km.
    const payload: WarrantyRecordCreate | WarrantyRecordUpdate = {
      warranty_type: data.warranty_type,
      provider: data.provider,
      start_date: data.start_date,
      end_date: data.end_date,
      mileage_limit_km: toCanonicalKm(data.mileage_limit_km, system) ?? undefined,
      coverage_details: data.coverage_details,
      policy_number: data.policy_number,
      notes: data.notes,
    }

    if (isEdit) {
      await updateMutation.mutateAsync({ id: record.id, ...payload })
    } else {
      await createMutation.mutateAsync(payload as WarrantyRecordCreate)
    }
  }, [isEdit, record, system, createMutation, updateMutation])

  const { error, handleSubmit: onSubmit } = useFormSubmit(submitFn, { onSuccess, onClose })

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<WarrantyFormData>({
    resolver: zodResolver(warrantySchema) as Resolver<WarrantyFormData>,
    defaultValues: {
      warranty_type: record?.warranty_type || '',
      provider: record?.provider || '',
      start_date: formatDateForInput(record?.start_date),
      end_date: formatDateForInput(record?.end_date === '' || record?.end_date === null ? undefined : record?.end_date),
      mileage_limit_km: (() => {
        const lim = record?.mileage_limit_km
        if (lim == null) return undefined
        const num = typeof lim === 'string' ? parseFloat(lim) : lim
        if (isNaN(num)) return undefined
        return system === 'imperial'
          ? Math.round(UnitConverter.kmToMiles(num) ?? num)
          : Math.round(num)
      })(),
      coverage_details: record?.coverage_details || '',
      policy_number: record?.policy_number || '',
      notes: record?.notes || '',
    },
  })

  return (
    <FormModalWrapper title={isEdit ? t('warranty.editTitle') : t('warranty.createTitle')} onClose={onClose}>
        <form onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="warranty_type" className="block text-sm font-medium text-garage-text mb-1">
                {t('warranty.warrantyType')} <span className="text-danger">*</span>
              </label>
              <select
                id="warranty_type"
                {...register('warranty_type')}
                className={`input w-full ${errors.warranty_type ? 'border-red-500' : ''}`}
                disabled={isSubmitting}
              >
                <option value="">{t('common:selectType')}</option>
                {WARRANTY_TYPES.map((type) => (
                  <option key={type} value={type}>{type}</option>
                ))}
              </select>
              <FormError error={errors.warranty_type} />
            </div>

            <div>
              <label htmlFor="provider" className="block text-sm font-medium text-garage-text mb-1">
                {t('insurance.provider')}
              </label>
              <input
                type="text"
                id="provider"
                {...register('provider')}
                className={`input w-full ${errors.provider ? 'border-red-500' : ''}`}
                placeholder="e.g., Honda, ACME Warranty Co"
                disabled={isSubmitting}
              />
              <FormError error={errors.provider} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="start_date" className="block text-sm font-medium text-garage-text mb-1">
                {t('common:startDate')} <span className="text-danger">*</span>
              </label>
              <input
                type="date"
                id="start_date"
                {...register('start_date')}
                className={`input w-full ${errors.start_date ? 'border-red-500' : ''}`}
                disabled={isSubmitting}
              />
              <FormError error={errors.start_date} />
            </div>

            <div>
              <label htmlFor="end_date" className="block text-sm font-medium text-garage-text mb-1">
                {t('common:endDate')}
              </label>
              <input
                type="date"
                id="end_date"
                {...register('end_date')}
                className={`input w-full ${errors.end_date ? 'border-red-500' : ''}`}
                disabled={isSubmitting}
              />
              <FormError error={errors.end_date} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="mileage_limit_km" className="block text-sm font-medium text-garage-text mb-1">
                {t('warranty.mileageLimit')} ({UnitFormatter.getDistanceUnit(system)})
              </label>
              <input
                type="number"
                id="mileage_limit_km"
                {...register('mileage_limit_km', { valueAsNumber: true })}
                className={`input w-full ${errors.mileage_limit_km ? 'border-red-500' : ''}`}
                placeholder="e.g., 100000"
                min="0"
                disabled={isSubmitting}
              />
              <FormError error={errors.mileage_limit_km} />
            </div>

            <div>
              <label htmlFor="policy_number" className="block text-sm font-medium text-garage-text mb-1">
                {t('insurance.policyNumber')}
              </label>
              <input
                type="text"
                id="policy_number"
                {...register('policy_number')}
                className={`input w-full ${errors.policy_number ? 'border-red-500' : ''}`}
                placeholder="e.g., WAR-12345"
                disabled={isSubmitting}
              />
              <FormError error={errors.policy_number} />
            </div>
          </div>

          <div>
            <label htmlFor="coverage_details" className="block text-sm font-medium text-garage-text mb-1">
              {t('warranty.coverageDetails')}
            </label>
            <textarea
              id="coverage_details"
              {...register('coverage_details')}
              className={`input w-full ${errors.coverage_details ? 'border-red-500' : ''}`}
              rows={3}
              placeholder={t('warranty.coverageDetailsPlaceholder')}
              disabled={isSubmitting}
            />
            <FormError error={errors.coverage_details} />
          </div>

          <div>
            <label htmlFor="notes" className="block text-sm font-medium text-garage-text mb-1">
              {t('common:notes')}
            </label>
            <textarea
              id="notes"
              {...register('notes')}
              className={`input w-full ${errors.notes ? 'border-red-500' : ''}`}
              rows={2}
              placeholder="Additional notes..."
              disabled={isSubmitting}
            />
            <FormError error={errors.notes} />
          </div>

          <div className="flex justify-end gap-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="btn btn-primary rounded-lg transition-colors"
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              disabled={isSubmitting}
            >
              <Save size={16} />
              {isSubmitting ? t('common:saving') : isEdit ? t('common:update') : t('common:create')}
            </button>
          </div>
        </form>
    </FormModalWrapper>
  )
}
