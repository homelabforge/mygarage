/**
 * Reminder list component for the Tracking tab
 */

import { useState } from 'react'
import { Bell, Plus, Check, X, Edit, Trash2, Clock, Gauge, Zap } from 'lucide-react'
import { toast } from 'sonner'
import { useReminders, useMarkReminderDone, useMarkReminderDismissed, useDeleteReminder } from '../hooks/useReminders'
import ReminderForm from './ReminderForm'
import type { Reminder, ReminderStatus } from '../types/reminder'

interface ReminderListProps {
  vin: string
}

const STATUS_TABS: { id: ReminderStatus | 'all'; label: string }[] = [
  { id: 'pending', label: 'Pending' },
  { id: 'done', label: 'Done' },
  { id: 'dismissed', label: 'Dismissed' },
]

const TYPE_ICONS: Record<string, typeof Bell> = {
  date: Clock,
  mileage: Gauge,
  both: Bell,
  smart: Zap,
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
}

export default function ReminderList({ vin }: ReminderListProps) {
  const [activeStatus, setActiveStatus] = useState<ReminderStatus | 'all'>('pending')
  const [showForm, setShowForm] = useState(false)
  const [editingReminder, setEditingReminder] = useState<Reminder | undefined>()

  const { data: reminders = [], isLoading } = useReminders(vin, activeStatus === 'all' ? 'all' : activeStatus)
  const markDoneMutation = useMarkReminderDone(vin)
  const dismissMutation = useMarkReminderDismissed(vin)
  const deleteMutation = useDeleteReminder(vin)

  const handleMarkDone = async (id: number) => {
    try {
      await markDoneMutation.mutateAsync(id)
      toast.success('Reminder marked as done')
    } catch {
      toast.error('Failed to mark reminder as done')
    }
  }

  const handleDismiss = async (id: number) => {
    try {
      await dismissMutation.mutateAsync(id)
      toast.success('Reminder dismissed')
    } catch {
      toast.error('Failed to dismiss reminder')
    }
  }

  const handleDelete = async (id: number) => {
    try {
      await deleteMutation.mutateAsync(id)
      toast.success('Reminder deleted')
    } catch {
      toast.error('Failed to delete reminder')
    }
  }

  const handleEdit = (reminder: Reminder) => {
    setEditingReminder(reminder)
    setShowForm(true)
  }

  const handleFormClose = () => {
    setShowForm(false)
    setEditingReminder(undefined)
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bell className="w-5 h-5 text-primary" />
          <h3 className="text-lg font-semibold text-garage-text">Reminders</h3>
        </div>
        <button
          onClick={() => { setEditingReminder(undefined); setShowForm(true) }}
          className="flex items-center gap-1 text-sm text-primary hover:text-primary/80"
        >
          <Plus className="w-4 h-4" />
          Add Reminder
        </button>
      </div>

      {/* Status filter tabs */}
      <div className="flex gap-1 p-1 bg-garage-bg rounded-lg">
        {STATUS_TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveStatus(tab.id)}
            className={`flex-1 py-1.5 px-3 text-sm font-medium rounded-md transition-colors ${
              activeStatus === tab.id
                ? 'bg-garage-surface text-primary shadow-sm'
                : 'text-garage-text-muted hover:text-garage-text'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Reminder list */}
      {isLoading ? (
        <div className="text-center py-8 text-garage-text-muted">Loading reminders...</div>
      ) : reminders.length === 0 ? (
        <div className="text-center py-8 text-garage-text-muted">
          No {activeStatus !== 'all' ? activeStatus : ''} reminders
        </div>
      ) : (
        <div className="space-y-3">
          {reminders.map((reminder) => {
            const TypeIcon = TYPE_ICONS[reminder.reminder_type] || Bell
            return (
              <div
                key={reminder.id}
                className="border border-garage-border rounded-lg p-4 bg-garage-surface"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-3 flex-1 min-w-0">
                    <TypeIcon className="w-5 h-5 text-primary mt-0.5 shrink-0" />
                    <div className="min-w-0">
                      <h4 className="text-sm font-medium text-garage-text">{reminder.title}</h4>
                      <div className="flex flex-wrap gap-2 mt-1">
                        <span className="px-2 py-0.5 text-xs bg-primary/10 text-primary rounded">
                          {reminder.reminder_type}
                        </span>
                        {reminder.due_date && (
                          <span className="text-xs text-garage-text-muted">
                            Due: {formatDate(reminder.due_date)}
                          </span>
                        )}
                        {reminder.due_mileage && (
                          <span className="text-xs text-garage-text-muted">
                            Due: {reminder.due_mileage.toLocaleString()} mi
                          </span>
                        )}
                        {reminder.estimated_due_date && (
                          <span className="text-xs text-primary">
                            Est: {formatDate(reminder.estimated_due_date)}
                          </span>
                        )}
                      </div>
                      {reminder.notes && (
                        <p className="text-xs text-garage-text-muted mt-1 truncate">{reminder.notes}</p>
                      )}
                      {reminder.line_item_id && (
                        <p className="text-xs text-garage-text-muted mt-1">Linked to service record</p>
                      )}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-1 shrink-0">
                    {reminder.status === 'pending' && (
                      <>
                        <button
                          onClick={() => handleMarkDone(reminder.id)}
                          className="p-1.5 text-green-600 hover:bg-green-50 dark:hover:bg-green-900/20 rounded"
                          title="Mark done"
                        >
                          <Check className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleDismiss(reminder.id)}
                          className="p-1.5 text-garage-text-muted hover:bg-garage-bg rounded"
                          title="Dismiss"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      </>
                    )}
                    <button
                      onClick={() => handleEdit(reminder)}
                      className="p-1.5 text-garage-text-muted hover:bg-garage-bg rounded"
                      title="Edit"
                    >
                      <Edit className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDelete(reminder.id)}
                      className="p-1.5 text-danger hover:bg-danger/10 rounded"
                      title="Delete"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Form modal */}
      {showForm && (
        <ReminderForm
          vin={vin}
          reminder={editingReminder}
          onClose={handleFormClose}
          onSuccess={handleFormClose}
        />
      )}
    </div>
  )
}
