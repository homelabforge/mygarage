/**
 * Reminder create/edit form (standalone, for Tracking tab)
 *
 * Mileage input is always an interval ("miles until due"). When currentMileage
 * is available, the form converts interval → absolute on submit. On edit, it
 * reverse-computes the remaining interval for display.
 */

import { useTranslation } from 'react-i18next'
import { useState, type SyntheticEvent } from 'react'
import { Save, AlertTriangle } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import { toast } from 'sonner'
import { useCreateReminder, useUpdateReminder } from '../hooks/useReminders'
import type { Reminder, ReminderType } from '../types/reminder'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitConverter, UnitFormatter } from '../utils/units'
import { toCanonicalKm } from '../utils/decimalSafe'

interface ReminderFormProps {
  vin: string
  reminder?: Reminder
  currentMileage?: number | null
  onClose: () => void
  onSuccess: () => void
}

const REMINDER_TYPES: { value: ReminderType; label: string; description: string }[] = [
  { value: 'date', label: 'Date', description: 'Notify on a specific date' },
  { value: 'mileage', label: 'Mileage', description: 'Notify at a specific mileage' },
  { value: 'both', label: 'Both', description: 'Notify when either date or mileage is reached' },
  { value: 'smart', label: 'Smart', description: 'Uses driving history to estimate — date is the hard cap' },
]

export default function ReminderForm({ vin, reminder, currentMileage, onClose, onSuccess }: ReminderFormProps) {
  const { t } = useTranslation('forms')
  const isEdit = !!reminder
  const createMutation = useCreateReminder(vin)
  const updateMutation = useUpdateReminder(vin)
  const hasMileage = currentMileage != null && currentMileage > 0
  const { system } = useUnitPreference()
  // currentMileage is in canonical km. Convert to user display unit when present.
  const currentDisplay = currentMileage != null
    ? (system === 'imperial' ? UnitConverter.kmToMiles(currentMileage) ?? currentMileage : currentMileage)
    : null

  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [title, setTitle] = useState(reminder?.title ?? '')
  const [reminderType, setReminderType] = useState<ReminderType>(
    (reminder?.reminder_type as ReminderType) ?? 'date'
  )
  const [dueDate, setDueDate] = useState(reminder?.due_date ?? '')

  // For edits: reverse-compute interval (in user display unit) from absolute
  // canonical km target.
  const initialInterval = (() => {
    const dueKm = reminder?.due_mileage_km
    if (dueKm == null) return undefined
    const dueKmNum = typeof dueKm === 'string' ? parseFloat(dueKm) : dueKm
    if (isNaN(dueKmNum)) return undefined
    const remainingKm = currentMileage != null ? Math.max(0, dueKmNum - currentMileage) : dueKmNum
    if (system === 'imperial') {
      return Math.round(UnitConverter.kmToMiles(remainingKm) ?? remainingKm)
    }
    return Math.round(remainingKm)
  })()
  const [mileageInterval, setMileageInterval] = useState<number | undefined>(initialInterval)

  const [notes, setNotes] = useState(reminder?.notes ?? '')

  // Compute target for display in user's units
  const absoluteTarget = hasMileage && mileageInterval && currentDisplay != null
    ? currentDisplay + mileageInterval
    : mileageInterval

  const handleSubmit = async (e: SyntheticEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError(null)

    if (!title.trim()) {
      setError(t('reminder.titleRequired'))
      return
    }

    if (['date', 'both', 'smart'].includes(reminderType) && !dueDate) {
      setError(t('reminder.dueDateRequired'))
      return
    }

    if (['mileage', 'both', 'smart'].includes(reminderType) && !mileageInterval) {
      setError(t('reminder.milesRequired'))
      return
    }

    // Convert user-entered interval (display unit) to canonical km, then add
    // baseline canonical km for absolute target.
    const intervalKm = toCanonicalKm(mileageInterval ?? null, system)
    const due_mileage_km = hasMileage && intervalKm != null
      ? currentMileage + intervalKm
      : intervalKm ?? undefined

    setSubmitting(true)
    try {
      if (isEdit && reminder) {
        await updateMutation.mutateAsync({
          id: reminder.id,
          title,
          reminder_type: reminderType,
          due_date: dueDate || undefined,
          due_mileage_km,
          notes: notes || undefined,
        })
        toast.success(t('reminder.updated'))
      } else {
        await createMutation.mutateAsync({
          title,
          reminder_type: reminderType,
          due_date: dueDate || undefined,
          due_mileage_km,
          notes: notes || undefined,
        })
        toast.success(t('reminder.created'))
      }
      onSuccess()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common:error'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <FormModalWrapper
      title={isEdit ? t('reminder.editTitle') : t('reminder.createTitle')}
      onClose={onClose}
      maxWidth="max-w-lg"
    >
      <form onSubmit={handleSubmit} className="p-6 space-y-4">
        {error && (
          <div className="bg-danger/10 border border-danger rounded-lg p-3 flex items-center gap-2">
            <AlertTriangle className="w-5 h-5 text-danger" />
            <p className="text-sm text-danger">{error}</p>
          </div>
        )}

        <div>
          <label className="block text-sm font-medium text-garage-text mb-1">
            {t('common:title')} <span className="text-danger">*</span>
          </label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={t('reminder.titlePlaceholder')}
            maxLength={200}
            disabled={submitting}
            className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-garage-text mb-1">
            {t('reminder.reminderType')}
          </label>
          <div className="grid grid-cols-2 gap-2">
            {REMINDER_TYPES.map((type) => (
              <button
                key={type.value}
                type="button"
                onClick={() => setReminderType(type.value)}
                disabled={submitting}
                className={`text-left p-3 rounded-lg border transition-colors ${
                  reminderType === type.value
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-garage-border bg-garage-bg text-garage-text hover:border-primary/50'
                }`}
              >
                <div className="text-sm font-medium">{type.label}</div>
                <div className="text-xs text-garage-text-muted mt-0.5">{type.description}</div>
              </button>
            ))}
          </div>
        </div>

        {['date', 'both', 'smart'].includes(reminderType) && (
          <div>
            <label className="block text-sm font-medium text-garage-text mb-1">
              {t('reminder.dueDate')} <span className="text-danger">*</span>
            </label>
            <input
              type="date"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
              disabled={submitting}
              className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
            />
          </div>
        )}

        {['mileage', 'both', 'smart'].includes(reminderType) && (
          <div>
            <label className="block text-sm font-medium text-garage-text mb-1">
              {hasMileage ? t('reminder.milesUntilDue') : t('reminder.dueMileage')} ({UnitFormatter.getDistanceUnit(system)}) <span className="text-danger">*</span>
            </label>
            <input
              type="number"
              value={mileageInterval ?? ''}
              onChange={(e) => setMileageInterval(e.target.value ? parseInt(e.target.value) : undefined)}
              min="1"
              placeholder={hasMileage ? 'e.g., 5000' : (system === 'imperial' ? 'e.g., 92000' : 'e.g., 148000')}
              disabled={submitting}
              className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
            />
            {hasMileage && mileageInterval && currentDisplay != null ? (
              <p className="text-xs text-garage-text-muted mt-1">
                Current: {Math.round(currentDisplay).toLocaleString()} + {mileageInterval.toLocaleString()} = {Math.round(absoluteTarget ?? 0).toLocaleString()} {UnitFormatter.getDistanceUnit(system)} target
              </p>
            ) : !hasMileage ? (
              <p className="text-xs text-warning mt-1">{t('reminder.noOdometerData')}</p>
            ) : null}
            {isEdit && hasMileage && initialInterval !== undefined && initialInterval <= 0 && (
              <p className="text-xs text-danger mt-1">
                {t('reminder.overdueHint')}
              </p>
            )}
          </div>
        )}

        {reminderType === 'smart' && (
          <div className="bg-primary/5 border border-primary/20 rounded-lg p-3">
            <p className="text-xs text-garage-text-muted">
              {t('reminder.smartModeDescription')}
            </p>
          </div>
        )}

        <div>
          <label className="block text-sm font-medium text-garage-text mb-1">{t('common:notes')}</label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder={t('reminder.optionalNotes')}
            rows={2}
            disabled={submitting}
            className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
          />
        </div>

        <div className="flex gap-3 pt-2">
          <button
            type="submit"
            disabled={submitting}
            className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Save className="w-4 h-4" />
            <span>{submitting ? t('common:saving') : isEdit ? t('common:update') : t('common:create')}</span>
          </button>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="btn btn-primary rounded-lg transition-colors"
          >
            {t('common:cancel')}
          </button>
        </div>
      </form>
    </FormModalWrapper>
  )
}
