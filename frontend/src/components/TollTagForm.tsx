import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { X, Save } from 'lucide-react'
import type { TollTag, TollTagCreate, TollTagUpdate } from '../types/toll'
import { tollTagSchema, type TollTagFormData, TOLL_SYSTEMS } from '../schemas/tollTag'
import { FormError } from './FormError'
import api from '../services/api'

interface TollTagFormProps {
  vin: string
  tag?: TollTag
  onClose: () => void
  onSuccess: () => void
}

export default function TollTagForm({ vin, tag, onClose, onSuccess }: TollTagFormProps) {
  const isEdit = !!tag
  const [error, setError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<TollTagFormData>({
    resolver: zodResolver(tollTagSchema),
    defaultValues: {
      toll_system: (tag?.toll_system as (typeof TOLL_SYSTEMS)[number]) ?? 'EZ TAG',
      tag_number: tag?.tag_number || '',
      status: tag?.status || 'active',
      notes: tag?.notes || '',
    },
  })

  const onSubmit = async (data: TollTagFormData) => {
    setError(null)

    try {
      const payload: TollTagCreate | TollTagUpdate = {
        toll_system: data.toll_system,
        tag_number: data.tag_number,
        status: data.status,
        notes: data.notes,
      }

      if (!isEdit) {
        (payload as TollTagCreate).vin = vin
      }

      if (isEdit) {
        await api.put(`/vehicles/${vin}/toll-tags/${tag.id}`, payload)
      } else {
        await api.post(`/vehicles/${vin}/toll-tags`, payload)
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
            {isEdit ? 'Edit Toll Tag' : 'Add Toll Tag'}
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
              <label htmlFor="toll_system" className="block text-sm font-medium text-garage-text mb-1">
                Toll System <span className="text-danger">*</span>
              </label>
              <select
                id="toll_system"
                {...register('toll_system')}
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.toll_system ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              >
                <option value="">Select toll system...</option>
                {TOLL_SYSTEMS.map((system) => (
                  <option key={system} value={system}>{system}</option>
                ))}
              </select>
              <FormError error={errors.toll_system} />
            </div>

            <div>
              <label htmlFor="tag_number" className="block text-sm font-medium text-garage-text mb-1">
                Tag Number <span className="text-danger">*</span>
              </label>
              <input
                type="text"
                id="tag_number"
                {...register('tag_number')}
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text font-mono ${
                  errors.tag_number ? 'border-red-500' : 'border-garage-border'
                }`}
                placeholder="e.g., 0012345678"
                disabled={isSubmitting}
              />
              <FormError error={errors.tag_number} />
            </div>
          </div>

          <div>
            <label htmlFor="status" className="block text-sm font-medium text-garage-text mb-1">
              Status
            </label>
            <select
              id="status"
              {...register('status')}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.status ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            >
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
            <FormError error={errors.status} />
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
              rows={3}
              placeholder="Additional notes about this toll tag..."
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
              className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50"
              disabled={isSubmitting}
            >
              <Save className="w-4 h-4" />
              {isSubmitting ? 'Saving...' : isEdit ? 'Update Tag' : 'Add Tag'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
