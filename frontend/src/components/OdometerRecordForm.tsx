import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Save } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import type { OdometerRecord, OdometerRecordCreate, OdometerRecordUpdate } from '../types/odometer'
import { odometerRecordSchema, type OdometerRecordFormData } from '../schemas/odometer'
import { FormError } from './FormError'
import { useCreateOdometerRecord, useUpdateOdometerRecord } from '../hooks/queries/useOdometerRecords'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitConverter, UnitFormatter } from '../utils/units'
import { toCanonicalKm } from '../utils/decimalSafe'
import { formatDateForInput } from '../utils/dateUtils'
import { useFormSubmit } from '../hooks/useFormSubmit'

interface OdometerRecordFormProps {
  vin: string
  record?: OdometerRecord
  onClose: () => void
  onSuccess: () => void
}

export default function OdometerRecordForm({ vin, record, onClose, onSuccess }: OdometerRecordFormProps) {
  const { t } = useTranslation('forms')
  const isEdit = !!record
  const createMutation = useCreateOdometerRecord(vin)
  const updateMutation = useUpdateOdometerRecord(vin)
  const { system } = useUnitPreference()

  const submitFn = useCallback(async (data: OdometerRecordFormData) => {
    // Convert user-entered value to canonical km for the API.
    const payload: OdometerRecordCreate | OdometerRecordUpdate = {
      vin,
      date: data.date,
      odometer_km: toCanonicalKm(data.odometer_km, system) ?? undefined,
      notes: data.notes,
    }

    if (isEdit) {
      await updateMutation.mutateAsync({ id: record.id, ...payload })
    } else {
      await createMutation.mutateAsync(payload as OdometerRecordCreate)
    }
  }, [isEdit, vin, record, system, createMutation, updateMutation])

  const { error, handleSubmit: onSubmit } = useFormSubmit(submitFn, { onSuccess, onClose })

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<OdometerRecordFormData>({
    resolver: zodResolver(odometerRecordSchema) as Resolver<OdometerRecordFormData>,
    defaultValues: {
      date: formatDateForInput(record?.date),
      odometer_km: (() => {
        const stored = record?.odometer_km
        const num = stored == null ? undefined : (typeof stored === 'string' ? parseFloat(stored) : stored)
        if (num == null || isNaN(num)) return undefined
        return system === 'imperial' ? UnitConverter.kmToMiles(num) ?? undefined : num
      })(),
      notes: record?.notes || '',
    },
  })

  return (
    <FormModalWrapper title={isEdit ? t('odometer.editTitle') : t('odometer.createTitle')} onClose={onClose} maxWidth="max-w-lg">
        <form onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

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
              {t('common:mileage')} ({UnitFormatter.getDistanceUnit(system)}) <span className="text-danger">*</span>
            </label>
            <input
              type="number"
              id="odometer_km"
              {...register('odometer_km', { valueAsNumber: true })}
              step="0.1"
              placeholder={system === 'imperial' ? '45000' : '72420'}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.odometer_km ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <FormError error={errors.odometer_km} />
          </div>

          <div>
            <label htmlFor="notes" className="block text-sm font-medium text-garage-text mb-1">
              Notes
            </label>
            <textarea
              id="notes"
              rows={3}
              {...register('notes')}
              placeholder={t('odometer.notesPlaceholder')}
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
              disabled={isSubmitting}
              className="btn btn-primary rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Cancel
            </button>
          </div>
        </form>
    </FormModalWrapper>
  )
}
