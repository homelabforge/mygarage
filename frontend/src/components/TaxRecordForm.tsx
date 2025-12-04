import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { X, Save } from 'lucide-react'
import type { TaxRecord, TaxRecordCreate, TaxRecordUpdate } from '../types/tax'
import { taxRecordSchema, type TaxRecordFormData, TAX_TYPES } from '../schemas/tax'
import { FormError } from './FormError'
import api from '../services/api'

interface TaxRecordFormProps {
  vin: string
  record?: TaxRecord
  onClose: () => void
  onSuccess: () => void
}

export default function TaxRecordForm({ vin, record, onClose, onSuccess }: TaxRecordFormProps) {
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
  } = useForm<TaxRecordFormData>({
    resolver: zodResolver(taxRecordSchema),
    defaultValues: {
      date: formatDateForInput(record?.date),
      tax_type: record?.tax_type ?? undefined,
      amount: record?.amount ?? undefined,
      renewal_date: record?.renewal_date ? formatDateForInput(record.renewal_date) : '',
      notes: record?.notes || '',
    },
  })

  const onSubmit = async (data: TaxRecordFormData) => {
    setError(null)

    try {
      // Zod has already validated amount - no parseFloat/isNaN needed!
      const payload: TaxRecordCreate | TaxRecordUpdate = {
        vin,
        date: data.date,
        tax_type: data.tax_type,
        amount: data.amount,
        renewal_date: data.renewal_date,
        notes: data.notes,
      }

      if (isEdit) {
        await api.put(`/vehicles/${vin}/tax-records/${record.id}`, payload)
      } else {
        await api.post(`/vehicles/${vin}/tax-records`, payload)
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
            {isEdit ? 'Edit Tax/Registration Record' : 'Add Tax/Registration Record'}
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
              <label htmlFor="date" className="block text-sm font-medium text-garage-text mb-1">
                Date Paid <span className="text-danger">*</span>
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
              <label htmlFor="tax_type" className="block text-sm font-medium text-garage-text mb-1">
                Type
              </label>
              <select
                id="tax_type"
                {...register('tax_type')}
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.tax_type ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              >
                <option value="" className="bg-garage-bg text-garage-text">Select type</option>
                {TAX_TYPES.map((type) => (
                  <option key={type} value={type} className="bg-garage-bg text-garage-text">{type}</option>
                ))}
              </select>
              <FormError error={errors.tax_type} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="amount" className="block text-sm font-medium text-garage-text mb-1">
                Amount <span className="text-danger">*</span>
              </label>
              <div className="relative">
                <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
                <input
                  type="number"
                  id="amount"
                  step="0.01"
                  {...register('amount')}
                  placeholder="85.50"
                  className={`w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.amount ? 'border-red-500' : 'border-garage-border'
                  }`}
                  disabled={isSubmitting}
                />
              </div>
              <FormError error={errors.amount} />
            </div>

            <div>
              <label htmlFor="renewal_date" className="block text-sm font-medium text-garage-text mb-1">
                Renewal Date
              </label>
              <input
                type="date"
                id="renewal_date"
                {...register('renewal_date')}
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.renewal_date ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
              <FormError error={errors.renewal_date} />
              <p className="text-xs text-garage-text-muted mt-1">
                When is this due next?
              </p>
            </div>
          </div>

          <div>
            <label htmlFor="notes" className="block text-sm font-medium text-garage-text mb-1">
              Notes
            </label>
            <textarea
              id="notes"
              rows={3}
              {...register('notes')}
              placeholder="Additional notes..."
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
