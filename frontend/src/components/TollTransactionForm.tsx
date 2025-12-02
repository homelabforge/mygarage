import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { X, Save } from 'lucide-react'
import type { TollTransaction, TollTransactionCreate, TollTransactionUpdate, TollTag } from '../types/toll'
import { tollTransactionSchema, type TollTransactionFormData } from '../schemas/tollTransaction'
import { FormError } from './FormError'
import api from '../services/api'

interface TollTransactionFormProps {
  vin: string
  tollTags: TollTag[]
  transaction?: TollTransaction
  onClose: () => void
  onSuccess: () => void
}

export default function TollTransactionForm({ vin, tollTags, transaction, onClose, onSuccess }: TollTransactionFormProps) {
  const isEdit = !!transaction
  const [error, setError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<TollTransactionFormData>({
    resolver: zodResolver(tollTransactionSchema),
    defaultValues: {
      transaction_date: transaction?.transaction_date || new Date().toISOString().split('T')[0],
      amount: transaction?.amount?.toString() || '',
      location: transaction?.location || '',
      toll_tag_id: transaction?.toll_tag_id?.toString() || '',
      notes: transaction?.notes || '',
    },
  })

  const onSubmit = async (data: TollTransactionFormData) => {
    setError(null)

    try {
      // Zod has already validated and coerced amount and toll_tag_id - no parseFloat/parseInt needed!
      const payload: TollTransactionCreate | TollTransactionUpdate = {
        transaction_date: data.transaction_date,
        amount: data.amount,
        location: data.location,
        toll_tag_id: data.toll_tag_id,
        notes: data.notes,
      }

      if (!isEdit) {
        (payload as TollTransactionCreate).vin = vin
      }

      if (isEdit) {
        await api.put(`/vehicles/${vin}/toll-transactions/${transaction.id}`, payload)
      } else {
        await api.post(`/vehicles/${vin}/toll-transactions`, payload)
      }

      onSuccess()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    }
  }

  const activeTollTags = tollTags.filter(tag => tag.status === 'active')

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center p-4 z-50">
      <div className="bg-garage-surface rounded-lg shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto border border-garage-border">
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border px-6 py-4 flex justify-between items-center rounded-t-lg">
          <h2 className="text-xl font-semibold text-garage-text">
            {isEdit ? 'Edit Toll Transaction' : 'Add Toll Transaction'}
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
              <label htmlFor="transaction_date" className="block text-sm font-medium text-garage-text mb-1">
                Date <span className="text-danger">*</span>
              </label>
              <input
                type="date"
                id="transaction_date"
                {...register('transaction_date')}
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.transaction_date ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
              <FormError error={errors.transaction_date} />
            </div>

            <div>
              <label htmlFor="amount" className="block text-sm font-medium text-garage-text mb-1">
                Amount <span className="text-danger">*</span>
              </label>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-garage-text-muted">$</span>
                <input
                  type="number"
                  id="amount"
                  {...register('amount')}
                  className={`w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.amount ? 'border-red-500' : 'border-garage-border'
                  }`}
                  placeholder="0.00"
                  step="0.01"
                  disabled={isSubmitting}
                />
              </div>
              <FormError error={errors.amount} />
            </div>
          </div>

          <div>
            <label htmlFor="location" className="block text-sm font-medium text-garage-text mb-1">
              Location <span className="text-danger">*</span>
            </label>
            <input
              type="text"
              id="location"
              {...register('location')}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.location ? 'border-red-500' : 'border-garage-border'
              }`}
              placeholder="e.g., Hardy Toll Road - Spring, I-45 North Tollway"
              disabled={isSubmitting}
            />
            <FormError error={errors.location} />
          </div>

          <div>
            <label htmlFor="toll_tag_id" className="block text-sm font-medium text-garage-text mb-1">
              Toll Tag
            </label>
            <select
              id="toll_tag_id"
              {...register('toll_tag_id')}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.toll_tag_id ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            >
              <option value="">None / Manual Payment</option>
              {activeTollTags.map((tag) => (
                <option key={tag.id} value={tag.id}>
                  {tag.toll_system} - {tag.tag_number}
                </option>
              ))}
            </select>
            <FormError error={errors.toll_tag_id} />
            {activeTollTags.length === 0 && (
              <p className="text-xs text-garage-text-muted mt-1">
                No active toll tags configured. Add a toll tag first to link transactions.
              </p>
            )}
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
              placeholder="Additional notes about this toll transaction..."
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
              <Save className="w-4 h-4" />
              {isSubmitting ? 'Saving...' : isEdit ? 'Update Transaction' : 'Add Transaction'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
