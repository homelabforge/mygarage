import { useState } from 'react'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { X, Save } from 'lucide-react'
import type { WarrantyRecord, WarrantyRecordCreate, WarrantyRecordUpdate } from '../types/warranty'
import { warrantySchema, type WarrantyFormData, WARRANTY_TYPES } from '../schemas/warranty'
import { FormError } from './FormError'
import api from '../services/api'

interface WarrantyFormProps {
  vin: string
  record?: WarrantyRecord
  onClose: () => void
  onSuccess: () => void
}

export default function WarrantyForm({ vin, record, onClose, onSuccess }: WarrantyFormProps) {
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
  } = useForm<WarrantyFormData>({
    resolver: zodResolver(warrantySchema) as Resolver<WarrantyFormData>,
    defaultValues: {
      warranty_type: record?.warranty_type || '',
      provider: record?.provider || '',
      start_date: formatDateForInput(record?.start_date),
      end_date: formatDateForInput(record?.end_date === '' || record?.end_date === null ? undefined : record?.end_date),
      mileage_limit: record?.mileage_limit ?? undefined,
      coverage_details: record?.coverage_details || '',
      policy_number: record?.policy_number || '',
      notes: record?.notes || '',
    },
  })

  const onSubmit = async (data: WarrantyFormData) => {
    setError(null)

    try {
      // Zod has already validated and coerced mileage_limit - no parseInt/isNaN needed!
      const payload: WarrantyRecordCreate | WarrantyRecordUpdate = {
        warranty_type: data.warranty_type,
        provider: data.provider,
        start_date: data.start_date,
        end_date: data.end_date,
        mileage_limit: data.mileage_limit,
        coverage_details: data.coverage_details,
        policy_number: data.policy_number,
        notes: data.notes,
      }

      const url = isEdit
        ? `/vehicles/${vin}/warranties/${record.id}`
        : `/vehicles/${vin}/warranties`

      if (isEdit) {
        await api.put(url, payload)
      } else {
        await api.post(url, payload)
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
            {isEdit ? 'Edit Warranty' : 'Add Warranty'}
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
              <label htmlFor="warranty_type" className="block text-sm font-medium text-garage-text mb-1">
                Warranty Type <span className="text-danger">*</span>
              </label>
              <select
                id="warranty_type"
                {...register('warranty_type')}
                className={`input w-full ${errors.warranty_type ? 'border-red-500' : ''}`}
                disabled={isSubmitting}
              >
                <option value="">Select type...</option>
                {WARRANTY_TYPES.map((type) => (
                  <option key={type} value={type}>{type}</option>
                ))}
              </select>
              <FormError error={errors.warranty_type} />
            </div>

            <div>
              <label htmlFor="provider" className="block text-sm font-medium text-garage-text mb-1">
                Provider
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
                Start Date <span className="text-danger">*</span>
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
                End Date
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
              <label htmlFor="mileage_limit" className="block text-sm font-medium text-garage-text mb-1">
                Mileage Limit
              </label>
              <input
                type="number"
                id="mileage_limit"
                {...register('mileage_limit', { valueAsNumber: true })}
                className={`input w-full ${errors.mileage_limit ? 'border-red-500' : ''}`}
                placeholder="e.g., 100000"
                min="0"
                disabled={isSubmitting}
              />
              <FormError error={errors.mileage_limit} />
            </div>

            <div>
              <label htmlFor="policy_number" className="block text-sm font-medium text-garage-text mb-1">
                Policy Number
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
              Coverage Details
            </label>
            <textarea
              id="coverage_details"
              {...register('coverage_details')}
              className={`input w-full ${errors.coverage_details ? 'border-red-500' : ''}`}
              rows={3}
              placeholder="What's covered by this warranty..."
              disabled={isSubmitting}
            />
            <FormError error={errors.coverage_details} />
          </div>

          <div>
            <label htmlFor="notes" className="block text-sm font-medium text-garage-text mb-1">
              Notes
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
              {isSubmitting ? 'Saving...' : isEdit ? 'Update' : 'Create'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
