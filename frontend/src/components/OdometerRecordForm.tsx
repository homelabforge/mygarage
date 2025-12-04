import { useState } from 'react'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { X, Save } from 'lucide-react'
import type { OdometerRecord, OdometerRecordCreate, OdometerRecordUpdate } from '../types/odometer'
import { odometerRecordSchema, type OdometerRecordFormData } from '../schemas/odometer'
import { FormError } from './FormError'
import api from '../services/api'

interface OdometerRecordFormProps {
  vin: string
  record?: OdometerRecord
  onClose: () => void
  onSuccess: () => void
}

export default function OdometerRecordForm({ vin, record, onClose, onSuccess }: OdometerRecordFormProps) {
  const isEdit = !!record
  const [error, setError] = useState<string | null>(null)

  // Helper to format date for input[type="date"]
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
    formState: { errors, isSubmitting },
  } = useForm<OdometerRecordFormData>({
    resolver: zodResolver(odometerRecordSchema) as Resolver<OdometerRecordFormData>,
    defaultValues: {
      date: formatDateForInput(record?.date),
      mileage: record?.mileage ?? undefined,
      notes: record?.notes || '',
    },
  })

  const onSubmit = async (data: OdometerRecordFormData) => {
    setError(null)

    try {
      // Zod has already validated mileage - no parseInt/isNaN needed!
      const payload: OdometerRecordCreate | OdometerRecordUpdate = {
        vin,
        date: data.date,
        mileage: data.mileage,
        notes: data.notes,
      }

      if (isEdit) {
        await api.put(`/vehicles/${vin}/odometer/${record.id}`, payload)
      } else {
        await api.post(`/vehicles/${vin}/odometer`, payload)
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
        <div className="bg-garage-surface border-b border-garage-border px-6 py-4 flex justify-between items-center rounded-t-lg">
          <h2 className="text-xl font-semibold text-garage-text">
            {isEdit ? 'Edit Odometer Reading' : 'Add Odometer Reading'}
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
              Mileage <span className="text-danger">*</span>
            </label>
            <input
              type="number"
              id="mileage"
              {...register('mileage')}
              placeholder="45000"
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
      </div>
    </div>
  )
}
