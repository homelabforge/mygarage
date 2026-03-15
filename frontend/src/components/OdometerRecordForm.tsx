import { useCallback } from 'react'
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
import { formatDateForInput } from '../utils/dateUtils'
import { useFormSubmit } from '../hooks/useFormSubmit'

interface OdometerRecordFormProps {
  vin: string
  record?: OdometerRecord
  onClose: () => void
  onSuccess: () => void
}

export default function OdometerRecordForm({ vin, record, onClose, onSuccess }: OdometerRecordFormProps) {
  const isEdit = !!record
  const createMutation = useCreateOdometerRecord(vin)
  const updateMutation = useUpdateOdometerRecord(vin)
  const { system } = useUnitPreference()

  const submitFn = useCallback(async (data: OdometerRecordFormData) => {
    // Convert from user's unit system to imperial (canonical storage format)
    // Mileage must be rounded to integer - backend stores as INT
    const convertedMileage = system === 'metric' && data.mileage
      ? UnitConverter.kmToMiles(data.mileage)
      : data.mileage
    const payload: OdometerRecordCreate | OdometerRecordUpdate = {
      vin,
      date: data.date,
      mileage: convertedMileage != null ? Math.round(convertedMileage) : undefined,
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
      mileage: system === 'metric' && record?.mileage
        ? (() => {
            const km = UnitConverter.milesToKm(record.mileage)
            return km != null ? Math.round(km) : undefined
          })()
        : record?.mileage ?? undefined,
      notes: record?.notes || '',
    },
  })

  return (
    <FormModalWrapper title={isEdit ? 'Edit Odometer Reading' : 'Add Odometer Reading'} onClose={onClose} maxWidth="max-w-lg">
        <form onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

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
              Mileage ({UnitFormatter.getDistanceUnit(system)}) <span className="text-danger">*</span>
            </label>
            <input
              type="number"
              id="mileage"
              {...register('mileage', { valueAsNumber: true })}
              placeholder={system === 'imperial' ? '45000' : '72420'}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.mileage ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <FormError error={errors.mileage} />
          </div>

          <div>
            <label htmlFor="notes" className="block text-sm font-medium text-garage-text mb-1">
              Notes
            </label>
            <textarea
              id="notes"
              rows={3}
              {...register('notes')}
              placeholder="Monthly reading, trip odometer, etc..."
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
