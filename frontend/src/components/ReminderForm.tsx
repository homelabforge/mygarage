import { X, Save } from 'lucide-react'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { toast } from 'sonner'
import type { Reminder, ReminderCreate, ReminderUpdate } from '../types/reminder'
import { reminderSchema, type ReminderFormData } from '../schemas/reminder'
import { FormError } from './FormError'
import api from '../services/api'

interface ReminderFormProps {
  vin: string
  reminder?: Reminder
  onClose: () => void
  onSuccess: () => void
}

export default function ReminderForm({ vin, reminder, onClose, onSuccess }: ReminderFormProps) {
  const isEdit = !!reminder

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    watch,
  } = useForm<ReminderFormData>({
    resolver: zodResolver(reminderSchema) as Resolver<ReminderFormData>,
    defaultValues: {
      description: reminder?.description || '',
      due_date: reminder?.due_date,
      due_mileage: reminder?.due_mileage,
      is_recurring: reminder?.is_recurring ?? false,
      recurrence_days: reminder?.recurrence_days,
      recurrence_miles: reminder?.recurrence_miles,
      notes: reminder?.notes,
    },
  })

  const isRecurring = watch('is_recurring')

  const onSubmit = async (data: ReminderFormData) => {
    try {
      const payload: ReminderCreate | ReminderUpdate = {
        vin,
        description: data.description,
        due_date: data.due_date || undefined,
        due_mileage: data.due_mileage,
        is_recurring: data.is_recurring,
        recurrence_days: data.recurrence_days,
        recurrence_miles: data.recurrence_miles,
        notes: data.notes || undefined,
      }

      if (isEdit) {
        await api.put(`/vehicles/${vin}/reminders/${reminder.id}`, payload)
      } else {
        await api.post(`/vehicles/${vin}/reminders`, payload)
      }

      onSuccess()
      onClose()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save reminder')
    }
  }

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center p-4 z-50">
      <div className="bg-garage-surface rounded-lg shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto border border-garage-border">
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border px-6 py-4 flex justify-between items-center rounded-t-lg">
          <h2 className="text-xl font-semibold text-garage-text">
            {isEdit ? 'Edit Reminder' : 'Add Reminder'}
          </h2>
          <button
            onClick={onClose}
            className="text-garage-text-muted hover:text-garage-text"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-4">

          <div>
            <label htmlFor="description" className="block text-sm font-medium text-garage-text mb-1">
              Description <span className="text-danger">*</span>
            </label>
            <input
              type="text"
              id="description"
              maxLength={200}
              {...register('description')}
              disabled={isSubmitting}
              placeholder="Oil change, tire rotation, registration renewal, etc."
              className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
            />
            <FormError error={errors.description} />
          </div>

          <div className="bg-primary/10 border border-primary rounded-lg p-4">
            <h3 className="text-sm font-medium text-garage-text mb-3">Due Conditions</h3>
            <p className="text-xs text-garage-text-muted mb-3">
              Set at least one condition. The reminder will trigger when any condition is met.
            </p>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label htmlFor="due_date" className="block text-sm font-medium text-garage-text mb-1">
                  Due Date
                </label>
                <input
                  type="date"
                  id="due_date"
                  {...register('due_date')}
                  disabled={isSubmitting}
                  className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                />
                <FormError error={errors.due_date} />
              </div>

              <div>
                <label htmlFor="due_mileage" className="block text-sm font-medium text-garage-text mb-1">
                  Due Mileage
                </label>
                <input
                  type="number"
                  id="due_mileage"
                  {...register('due_mileage', { valueAsNumber: true })}
                  disabled={isSubmitting}
                  placeholder="e.g., 50000"
                  className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                />
                <FormError error={errors.due_mileage} />
              </div>
            </div>
          </div>

          <div className="bg-garage-bg border border-garage-border rounded-lg p-4">
            <div className="flex items-center mb-3">
              <input
                type="checkbox"
                id="is_recurring"
                {...register('is_recurring')}
                disabled={isSubmitting}
                className="h-4 w-4 text-primary focus:ring-primary border-garage-border rounded bg-garage-bg"
              />
              <label htmlFor="is_recurring" className="ml-2 block text-sm font-medium text-garage-text">
                Recurring Reminder
              </label>
            </div>

            {isRecurring && (
              <>
                <p className="text-xs text-garage-text-muted mb-3">
                  Set at least one recurrence interval. A new reminder will be created when this one is completed.
                </p>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="recurrence_days" className="block text-sm font-medium text-garage-text mb-1">
                      Every X Days
                    </label>
                    <input
                      type="number"
                      id="recurrence_days"
                      {...register('recurrence_days', { valueAsNumber: true })}
                      disabled={isSubmitting}
                      placeholder="e.g., 90"
                      className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                    />
                    <FormError error={errors.recurrence_days} />
                  </div>

                  <div>
                    <label htmlFor="recurrence_miles" className="block text-sm font-medium text-garage-text mb-1">
                      Every X Miles
                    </label>
                    <input
                      type="number"
                      id="recurrence_miles"
                      {...register('recurrence_miles', { valueAsNumber: true })}
                      disabled={isSubmitting}
                      placeholder="e.g., 5000"
                      className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                    />
                    <FormError error={errors.recurrence_miles} />
                  </div>
                </div>
              </>
            )}
          </div>

          <div>
            <label htmlFor="notes" className="block text-sm font-medium text-garage-text mb-1">
              Notes
            </label>
            <textarea
              id="notes"
              rows={3}
              {...register('notes')}
              disabled={isSubmitting}
              placeholder="Additional details..."
              className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
            />
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
              className="btn btn-primary rounded-lg transition-colors"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
