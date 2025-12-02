import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { X, Save } from 'lucide-react'
import type { Recall, RecallCreate, RecallUpdate } from '../types/recall'
import { recallSchema, type RecallFormData } from '../schemas/recall'
import { FormError } from './FormError'
import api from '../services/api'

interface RecallFormProps {
  vin: string
  recall?: Recall
  onClose: () => void
  onSuccess: () => void
}

export default function RecallForm({ vin, recall, onClose, onSuccess }: RecallFormProps) {
  const isEdit = !!recall
  const [error, setError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<RecallFormData>({
    resolver: zodResolver(recallSchema),
    defaultValues: {
      nhtsa_campaign_number: recall?.nhtsa_campaign_number || '',
      component: recall?.component || '',
      summary: recall?.summary || '',
      consequence: recall?.consequence || '',
      remedy: recall?.remedy || '',
      date_announced: recall?.date_announced || '',
      is_resolved: recall?.is_resolved || false,
      notes: recall?.notes || '',
    },
  })

  const onSubmit = async (data: RecallFormData) => {
    setError(null)

    try {
      const payload: RecallCreate | RecallUpdate = {
        nhtsa_campaign_number: data.nhtsa_campaign_number,
        component: data.component,
        summary: data.summary,
        consequence: data.consequence,
        remedy: data.remedy,
        date_announced: data.date_announced,
        is_resolved: data.is_resolved,
        notes: data.notes,
      }

      if (!isEdit) {
        (payload as RecallCreate).vin = vin
      }

      const url = isEdit
        ? `/vehicles/${vin}/recalls/${recall.id}`
        : `/vehicles/${vin}/recalls`

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
      <div className="bg-garage-surface rounded-lg shadow-2xl max-w-3xl w-full max-h-[90vh] overflow-y-auto border border-garage-border">
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border px-6 py-4 flex justify-between items-center rounded-t-lg">
          <h2 className="text-xl font-semibold text-garage-text">
            {isEdit ? 'Edit Recall' : 'Add Recall'}
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
              <label htmlFor="nhtsa_campaign_number" className="block text-sm font-medium text-garage-text mb-1">
                NHTSA Campaign Number
              </label>
              <input
                type="text"
                id="nhtsa_campaign_number"
                {...register('nhtsa_campaign_number')}
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text font-mono ${
                  errors.nhtsa_campaign_number ? 'border-red-500' : 'border-garage-border'
                }`}
                placeholder="e.g., 23V123000"
                disabled={isSubmitting}
              />
              <FormError error={errors.nhtsa_campaign_number} />
            </div>

            <div>
              <label htmlFor="date_announced" className="block text-sm font-medium text-garage-text mb-1">
                Date Announced
              </label>
              <input
                type="date"
                id="date_announced"
                {...register('date_announced')}
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.date_announced ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
              <FormError error={errors.date_announced} />
            </div>
          </div>

          <div>
            <label htmlFor="component" className="block text-sm font-medium text-garage-text mb-1">
              Component <span className="text-danger">*</span>
            </label>
            <input
              type="text"
              id="component"
              {...register('component')}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.component ? 'border-red-500' : 'border-garage-border'
              }`}
              placeholder="e.g., Air Bags, Brakes, Fuel System"
              disabled={isSubmitting}
            />
            <FormError error={errors.component} />
          </div>

          <div>
            <label htmlFor="summary" className="block text-sm font-medium text-garage-text mb-1">
              Summary <span className="text-danger">*</span>
            </label>
            <textarea
              id="summary"
              {...register('summary')}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.summary ? 'border-red-500' : 'border-garage-border'
              }`}
              rows={3}
              placeholder="Brief description of the recall issue..."
              disabled={isSubmitting}
            />
            <FormError error={errors.summary} />
          </div>

          <div>
            <label htmlFor="consequence" className="block text-sm font-medium text-garage-text mb-1">
              Consequence
            </label>
            <textarea
              id="consequence"
              {...register('consequence')}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.consequence ? 'border-red-500' : 'border-garage-border'
              }`}
              rows={2}
              placeholder="Potential consequences if not addressed..."
              disabled={isSubmitting}
            />
            <FormError error={errors.consequence} />
          </div>

          <div>
            <label htmlFor="remedy" className="block text-sm font-medium text-garage-text mb-1">
              Remedy
            </label>
            <textarea
              id="remedy"
              {...register('remedy')}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.remedy ? 'border-red-500' : 'border-garage-border'
              }`}
              rows={2}
              placeholder="How to fix or address the issue..."
              disabled={isSubmitting}
            />
            <FormError error={errors.remedy} />
          </div>

          <div>
            <label htmlFor="notes" className="block text-sm font-medium text-garage-text mb-1">
              Notes
            </label>
            <textarea
              id="notes"
              {...register('notes')}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.notes ? 'border-red-500' : 'border-garage-border'
              }`}
              rows={2}
              placeholder="Additional notes..."
              disabled={isSubmitting}
            />
            <FormError error={errors.notes} />
          </div>

          <div className="flex items-center">
            <input
              type="checkbox"
              id="is_resolved"
              {...register('is_resolved')}
              className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2"
              disabled={isSubmitting}
            />
            <label htmlFor="is_resolved" className="ml-2 text-sm text-garage-text">
              Mark as resolved
            </label>
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
              className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50"
              disabled={isSubmitting}
            >
              <Save className="w-4 h-4" />
              {isSubmitting ? 'Saving...' : isEdit ? 'Update Recall' : 'Add Recall'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
