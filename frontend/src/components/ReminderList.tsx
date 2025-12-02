import { useState, useEffect, useMemo, useCallback } from 'react'
import { Bell, Plus, Trash2, Edit3, CheckCircle, Circle, Calendar, Gauge, RotateCw, Filter, X, Save } from 'lucide-react'
import { toast } from 'sonner'
import type { Reminder } from '../types/reminder'
import api from '../services/api'

type FilterOption = 'all' | 'overdue' | 'upcoming' | 'completed'

interface ReminderListProps {
  vin: string
  onAddClick: () => void
  onEditClick: (reminder: Reminder) => void
}

type NextReminderPayload = {
  vin: string
  description: string
  is_recurring: boolean
  recurrence_days?: number | null
  recurrence_miles?: number | null
  notes?: string | null
  due_date?: string
  due_mileage?: number
}

export default function ReminderList({ vin, onAddClick, onEditClick }: ReminderListProps) {
  const [reminders, setReminders] = useState<Reminder[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [showCompleted, setShowCompleted] = useState(false)
  const [stats, setStats] = useState({ total: 0, active: 0, completed: 0 })
  const [filterBy, setFilterBy] = useState<FilterOption>('all')
  const [showRecurringModal, setShowRecurringModal] = useState(false)
  const [recurringReminderToComplete, setRecurringReminderToComplete] = useState<Reminder | null>(null)

  const fetchReminders = useCallback(async () => {
    try {
      const response = await api.get(`/vehicles/${vin}/reminders?include_completed=${showCompleted}`)
      setReminders(response.data.reminders)
      setStats({ total: response.data.total, active: response.data.active, completed: response.data.completed })
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    }
  }, [vin, showCompleted])

  useEffect(() => {
    setLoading(true)
    fetchReminders().finally(() => setLoading(false))
  }, [fetchReminders])

  // Filter reminders based on selected filter
  const filteredReminders = useMemo(() => {
    switch (filterBy) {
      case 'overdue':
        return reminders.filter((r) => isOverdue(r))
      case 'upcoming':
        return reminders.filter((r) => !r.is_completed && !isOverdue(r))
      case 'completed':
        return reminders.filter((r) => r.is_completed)
      case 'all':
      default:
        return reminders
    }
  }, [reminders, filterBy])

  const handleDelete = async (reminderId: number) => {
    if (!confirm('Are you sure you want to delete this reminder?')) {
      return
    }

    setDeletingId(reminderId)
    try {
      await api.delete(`/vehicles/${vin}/reminders/${reminderId}`)
      await fetchReminders()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete reminder')
    } finally {
      setDeletingId(null)
    }
  }

  const handleToggleComplete = async (reminder: Reminder) => {
    // If marking as complete and it's recurring, show modal
    if (!reminder.is_completed && reminder.is_recurring) {
      setRecurringReminderToComplete(reminder)
      setShowRecurringModal(true)
      return
    }

    // Otherwise, complete/uncomplete normally
    try {
      const endpoint = reminder.is_completed ? 'uncomplete' : 'complete'
      await api.post(`/vehicles/${vin}/reminders/${reminder.id}/${endpoint}`)
      await fetchReminders()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : `Failed to update reminder`)
    }
  }

  const handleCompleteRecurring = async (createNext: boolean) => {
    if (!recurringReminderToComplete) return

    try {
      // Mark current reminder as complete
      await api.post(`/vehicles/${vin}/reminders/${recurringReminderToComplete.id}/complete`)

      // Create next occurrence if requested
      if (createNext) {
        const nextReminder = calculateNextReminder(recurringReminderToComplete)
        await api.post(`/vehicles/${vin}/reminders`, nextReminder)
      }

      await fetchReminders()
      setShowRecurringModal(false)
      setRecurringReminderToComplete(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to complete recurring reminder')
    }
  }

  const calculateNextReminder = (reminder: Reminder): NextReminderPayload => {
    const nextReminder: NextReminderPayload = {
      vin: reminder.vin,
      description: reminder.description,
      is_recurring: reminder.is_recurring,
      recurrence_days: reminder.recurrence_days,
      recurrence_miles: reminder.recurrence_miles,
      notes: reminder.notes,
    }

    // Calculate next due date
    if (reminder.due_date && reminder.recurrence_days) {
      const currentDue = new Date(reminder.due_date)
      currentDue.setDate(currentDue.getDate() + reminder.recurrence_days)
      nextReminder.due_date = currentDue.toISOString().split('T')[0]
    }

    // Calculate next due mileage
    if (reminder.due_mileage && reminder.recurrence_miles) {
      nextReminder.due_mileage = reminder.due_mileage + reminder.recurrence_miles
    }

    return nextReminder
  }

  const formatDate = (dateString: string): string => {
    const date = new Date(dateString + 'T00:00:00')
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  }

  const isOverdue = (reminder: Reminder): boolean => {
    if (reminder.is_completed) return false

    if (reminder.due_date) {
      const dueDate = new Date(reminder.due_date)
      const today = new Date()
      today.setHours(0, 0, 0, 0)
      return dueDate < today
    }

    return false
  }

  const getDueSoonClass = (reminder: Reminder): string => {
    if (reminder.is_completed) return ''

    if (isOverdue(reminder)) {
      return 'border-danger bg-danger/5'
    }

    if (reminder.due_date) {
      const dueDate = new Date(reminder.due_date)
      const today = new Date()
      const daysUntilDue = Math.ceil((dueDate.getTime() - today.getTime()) / (1000 * 60 * 60 * 24))

      if (daysUntilDue <= 7) {
        return 'border-warning bg-warning/5'
      }
    }

    return ''
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">Loading reminders...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-danger/10 border border-danger rounded-lg p-4">
        <p className="text-danger">{error}</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Bell className="w-5 h-5 text-garage-text-muted" />
            <h3 className="text-lg font-semibold text-garage-text">
              Reminders
            </h3>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="text-garage-text-muted">
              <span className="text-garage-text font-medium">{stats.active}</span> active
            </span>
            {stats.completed > 0 && (
              <span className="text-garage-text-muted">
                <span className="text-garage-text font-medium">{stats.completed}</span> completed
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* Filter dropdown */}
          <div className="relative">
            <select
              value={filterBy}
              onChange={(e) => setFilterBy(e.target.value as FilterOption)}
              className="pl-3 pr-10 py-2 text-sm border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text appearance-none cursor-pointer"
            >
              <option value="all" className="bg-garage-bg text-garage-text">
                All Reminders
              </option>
              <option value="overdue" className="bg-garage-bg text-garage-text">
                Overdue Only
              </option>
              <option value="upcoming" className="bg-garage-bg text-garage-text">
                Upcoming Only
              </option>
              <option value="completed" className="bg-garage-bg text-garage-text">
                Completed Only
              </option>
            </select>
            <Filter className="absolute right-3 top-1/2 transform -translate-y-1/2 w-3.5 h-3.5 text-garage-text-muted pointer-events-none" />
          </div>

          {stats.completed > 0 && (
            <button
              onClick={() => setShowCompleted(!showCompleted)}
              className="px-3 py-2 text-sm border border-garage-border text-garage-text rounded-md hover:bg-garage-bg"
            >
              {showCompleted ? 'Hide' : 'Show'} Completed
            </button>
          )}
          <button
            onClick={onAddClick}
            className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>Add Reminder</span>
          </button>
        </div>
      </div>

      {/* Filter results count */}
      {filterBy !== 'all' && (
        <div className="text-sm text-garage-text-muted">
          Showing {filteredReminders.length} {filterBy} reminder{filteredReminders.length !== 1 ? 's' : ''}
        </div>
      )}

      {filteredReminders.length === 0 ? (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-8 text-center">
          <Bell className="w-12 h-12 text-garage-text-muted opacity-50 mx-auto mb-3" />
          <p className="text-garage-text mb-2">
            {showCompleted ? 'No completed reminders' : 'No active reminders'}
          </p>
          <p className="text-sm text-garage-text-muted mb-4">
            {!showCompleted && 'Set reminders for upcoming maintenance, registration renewals, and inspections'}
          </p>
          {!showCompleted && (
            <button
              onClick={onAddClick}
              className="inline-flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
            >
              <Plus className="w-4 h-4" />
              <span>Add First Reminder</span>
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {filteredReminders.map((reminder) => (
            <div
              key={reminder.id}
              className={`bg-garage-surface border rounded-lg p-4 transition-colors ${getDueSoonClass(reminder)} ${
                reminder.is_completed ? 'opacity-60' : ''
              }`}
            >
              <div className="flex items-start gap-3">
                <button
                  onClick={() => handleToggleComplete(reminder)}
                  className="mt-1 flex-shrink-0"
                  title={reminder.is_completed ? 'Mark as incomplete' : 'Mark as complete'}
                >
                  {reminder.is_completed ? (
                    <CheckCircle className="w-5 h-5 text-primary" />
                  ) : (
                    <Circle className="w-5 h-5 text-garage-text-muted hover:text-primary" />
                  )}
                </button>

                <div className="flex-1 min-w-0">
                  <div className="flex items-start justify-between gap-2">
                    <h4 className={`text-garage-text font-medium ${reminder.is_completed ? 'line-through' : ''}`}>
                      {reminder.description}
                    </h4>
                    <div className="flex items-center gap-1 flex-shrink-0">
                      {reminder.is_recurring && (
                        <span className="p-1 bg-primary/20 text-primary rounded" title="Recurring">
                          <RotateCw className="w-3 h-3" />
                        </span>
                      )}
                      {!reminder.is_completed && (
                        <>
                          <button
                            onClick={() => onEditClick(reminder)}
                            className="p-2 text-garage-text-muted hover:bg-garage-bg rounded-full"
                            title="Edit"
                          >
                            <Edit3 className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => handleDelete(reminder.id)}
                            disabled={deletingId === reminder.id}
                            className="p-2 text-danger hover:bg-danger/10 rounded-full disabled:opacity-50"
                            title="Delete"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </>
                      )}
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-4 mt-2 text-sm text-garage-text-muted">
                    {reminder.due_date && (
                      <div className="flex items-center gap-1">
                        <Calendar className="w-4 h-4" />
                        <span className={isOverdue(reminder) && !reminder.is_completed ? 'text-danger font-medium' : ''}>
                          {formatDate(reminder.due_date)}
                          {isOverdue(reminder) && !reminder.is_completed && ' (Overdue)'}
                        </span>
                      </div>
                    )}
                    {reminder.due_mileage && (
                      <div className="flex items-center gap-1">
                        <Gauge className="w-4 h-4" />
                        <span>{reminder.due_mileage.toLocaleString()} mi</span>
                      </div>
                    )}
                    {reminder.is_recurring && (
                      <div className="flex items-center gap-1 text-primary">
                        <RotateCw className="w-4 h-4" />
                        <span>
                          Every{' '}
                          {reminder.recurrence_days ? `${reminder.recurrence_days} days` : ''}
                          {reminder.recurrence_days && reminder.recurrence_miles ? ' or ' : ''}
                          {reminder.recurrence_miles ? `${reminder.recurrence_miles.toLocaleString()} mi` : ''}
                        </span>
                      </div>
                    )}
                  </div>

                  {reminder.notes && (
                    <p className="text-sm text-garage-text-muted mt-2">{reminder.notes}</p>
                  )}

                  {reminder.is_completed && reminder.completed_at && (
                    <p className="text-xs text-garage-text-muted mt-2">
                      Completed {formatDate(reminder.completed_at)}
                    </p>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Recurring Reminder Modal */}
      {showRecurringModal && recurringReminderToComplete && (
        <div className="fixed inset-0 modal-overlay backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-garage-surface rounded-lg border border-garage-border w-full max-w-md">
            <div className="sticky top-0 bg-garage-surface border-b border-garage-border px-6 py-4 flex items-center justify-between rounded-t-lg">
              <div className="flex items-center gap-2">
                <RotateCw className="w-5 h-5 text-primary" />
                <h2 className="text-xl font-semibold text-garage-text">Complete Recurring Reminder</h2>
              </div>
              <button
                onClick={() => {
                  setShowRecurringModal(false)
                  setRecurringReminderToComplete(null)
                }}
                className="text-garage-text-muted hover:text-garage-text transition-colors"
              >
                <X size={24} />
              </button>
            </div>

            <div className="p-6 space-y-4">
              <p className="text-garage-text">
                You are completing a recurring reminder:
              </p>
              <div className="bg-garage-bg border border-garage-border rounded-lg p-4">
                <h3 className="font-medium text-garage-text mb-2">{recurringReminderToComplete.description}</h3>
                <div className="text-sm text-garage-text-muted space-y-1">
                  {recurringReminderToComplete.due_date && (
                    <div className="flex items-center gap-2">
                      <Calendar className="w-4 h-4" />
                      <span>Due: {formatDate(recurringReminderToComplete.due_date)}</span>
                    </div>
                  )}
                  {recurringReminderToComplete.due_mileage && (
                    <div className="flex items-center gap-2">
                      <Gauge className="w-4 h-4" />
                      <span>Due at: {recurringReminderToComplete.due_mileage.toLocaleString()} mi</span>
                    </div>
                  )}
                  <div className="flex items-center gap-2 text-primary">
                    <RotateCw className="w-4 h-4" />
                    <span>
                      Recurs every{' '}
                      {recurringReminderToComplete.recurrence_days ? `${recurringReminderToComplete.recurrence_days} days` : ''}
                      {recurringReminderToComplete.recurrence_days && recurringReminderToComplete.recurrence_miles ? ' or ' : ''}
                      {recurringReminderToComplete.recurrence_miles ? `${recurringReminderToComplete.recurrence_miles.toLocaleString()} mi` : ''}
                    </span>
                  </div>
                </div>
              </div>

              {/* Next occurrence preview */}
              {(() => {
                const next = calculateNextReminder(recurringReminderToComplete)
                return (
                  <div className="bg-primary/10 border border-primary/30 rounded-lg p-4">
                    <h4 className="text-sm font-medium text-primary mb-2">Next Occurrence Will Be:</h4>
                    <div className="text-sm text-garage-text space-y-1">
                      {next.due_date && (
                        <div className="flex items-center gap-2">
                          <Calendar className="w-4 h-4" />
                          <span>Due: {formatDate(next.due_date)}</span>
                        </div>
                      )}
                      {next.due_mileage && (
                        <div className="flex items-center gap-2">
                          <Gauge className="w-4 h-4" />
                          <span>Due at: {next.due_mileage.toLocaleString()} mi</span>
                        </div>
                      )}
                    </div>
                  </div>
                )
              })()}

              <p className="text-sm text-garage-text-muted">
                Would you like to create the next occurrence of this reminder?
              </p>

              <div className="flex gap-3 pt-4">
                <button
                  onClick={() => handleCompleteRecurring(false)}
                  className="flex-1 btn-primary transition-colors"
                >
                  Complete Only
                </button>
                <button
                  onClick={() => handleCompleteRecurring(true)}
                  className="flex-1 flex items-center justify-center gap-2 btn btn-primary rounded-lg transition-colors"
                >
                  <Save size={16} />
                  Create Next
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
