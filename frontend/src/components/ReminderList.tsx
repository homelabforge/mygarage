/**
 * Reminder list component for the Tracking tab
 */

import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Bell, Plus, Check, X, Edit, Trash2, Clock, Gauge, Zap, Timer, Package } from 'lucide-react'
import { toast } from 'sonner'
import { useReminders, useMarkReminderDone, useMarkReminderDismissed, useDeleteReminder } from '../hooks/useReminders'
import { useLatestMileage } from '../hooks/useLatestMileage'
import { useLatestHours } from '../hooks/useLatestHours'
import { formatDateForDisplay } from '../utils/dateUtils'
import { useDateLocale } from '../hooks/useDateLocale'
import ReminderForm from './ReminderForm'
import type { Reminder, ReminderStatus } from '../types/reminder'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitFormatter } from '../utils/units'
import { Button, IconButton, Card, Chip, Mono, EmptyState, Select } from './ui'
import api from '../services/api'
import { useQueryClient } from '@tanstack/react-query'

interface ReminderListProps {
  vin: string
}

const STATUS_TABS: { id: ReminderStatus | 'all'; labelKey: string }[] = [
  { id: 'pending', labelKey: 'reminderList.statusPending' },
  { id: 'done', labelKey: 'reminderList.statusDone' },
  { id: 'dismissed', labelKey: 'reminderList.statusDismissed' },
]

const TYPE_ICONS: Record<string, typeof Bell> = {
  date: Clock,
  mileage: Gauge,
  hours: Timer,
  both: Bell,
  smart: Zap,
}

export default function ReminderList({ vin }: ReminderListProps) {
  const { t } = useTranslation('vehicles')
  const dateLocale = useDateLocale()
  const { system, showBoth } = useUnitPreference()
  const queryClient = useQueryClient()
  const [activeStatus, setActiveStatus] = useState<ReminderStatus | 'all'>('pending')
  const [showForm, setShowForm] = useState(false)
  const [editingReminder, setEditingReminder] = useState<Reminder | undefined>()
  const [packs, setPacks] = useState<{ id: string; name: string; description?: string }[]>([])
  const [selectedPack, setSelectedPack] = useState('')
  const [applyingPack, setApplyingPack] = useState(false)

  useEffect(() => {
    void api
      .get('/reminder-packs')
      .then((res) => setPacks(res.data || []))
      .catch(() => setPacks([]))
  }, [])

  const applyPack = async () => {
    if (!selectedPack) return
    setApplyingPack(true)
    try {
      await api.post(`/vehicles/${vin}/reminders/apply-pack`, { pack_id: selectedPack })
      toast.success(t('reminderList.packApplied'))
      await queryClient.invalidateQueries({ queryKey: ['reminders', vin] })
      setSelectedPack('')
    } catch {
      toast.error(t('reminderList.packApplyError'))
    } finally {
      setApplyingPack(false)
    }
  }

  const formatDate = (dateStr: string | null): string => {
    if (!dateStr) return '-'
    return formatDateForDisplay(dateStr, { year: 'numeric', month: 'short', day: 'numeric' }, dateLocale)
  }

  const { data: currentMileage } = useLatestMileage(vin)
  const { data: currentHours } = useLatestHours(vin)
  const { data: reminders = [], isLoading } = useReminders(vin, activeStatus === 'all' ? 'all' : activeStatus)
  const markDoneMutation = useMarkReminderDone(vin)
  const dismissMutation = useMarkReminderDismissed(vin)
  const deleteMutation = useDeleteReminder(vin)

  const handleMarkDone = async (id: number) => {
    try {
      await markDoneMutation.mutateAsync(id)
      toast.success(t('reminderList.markedDone'))
    } catch {
      toast.error(t('reminderList.markDoneError'))
    }
  }

  const handleDismiss = async (id: number) => {
    try {
      await dismissMutation.mutateAsync(id)
      toast.success(t('reminderList.dismissed'))
    } catch {
      toast.error(t('reminderList.dismissError'))
    }
  }

  const handleDelete = async (id: number) => {
    try {
      await deleteMutation.mutateAsync(id)
      toast.success(t('reminderList.deleted'))
    } catch {
      toast.error(t('reminderList.deleteError'))
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
          <Bell aria-hidden="true" className="w-5 h-5 text-text-mute" />
          <h3 className="text-lg font-semibold text-text">{t('reminderList.title')}</h3>
        </div>
        <Button
          variant="primary"
          size="sm"
          icon={Plus}
          onClick={() => { setEditingReminder(undefined); setShowForm(true) }}
        >
          {t('reminderList.addReminder')}
        </Button>
      </div>

      {packs.length > 0 && (
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[220px] flex-1">
            <Select
              id="reminder-pack"
              aria-label={t('reminderList.applyPackAria')}
              value={selectedPack}
              onChange={(e) => setSelectedPack(e.target.value)}
              options={[
                { value: '', label: t('reminderList.choosePack') },
                ...packs.map((p) => ({ value: p.id, label: p.name })),
              ]}
            />
          </div>
          <Button
            variant="secondary"
            size="sm"
            icon={Package}
            loading={applyingPack}
            disabled={!selectedPack}
            onClick={() => void applyPack()}
          >
            {t('reminderList.applyPack')}
          </Button>
        </div>
      )}

      {/* Status filter */}
      <div className="flex flex-wrap gap-2">
        {STATUS_TABS.map((tab) => (
          <Chip
            key={tab.id}
            onClick={() => setActiveStatus(tab.id)}
            selected={activeStatus === tab.id}
          >
            {t(tab.labelKey)}
          </Chip>
        ))}
      </div>

      {/* Reminder list */}
      {isLoading ? (
        <div className="text-center py-8 text-text-mute">{t('reminderList.loading')}</div>
      ) : reminders.length === 0 ? (
        <EmptyState
          icon={Bell}
          size="sm"
          title={t('reminderList.noReminders', { status: activeStatus !== 'all' ? activeStatus : '' })}
        />
      ) : (
        <div className="space-y-3">
          {reminders.map((reminder) => {
            const TypeIcon = TYPE_ICONS[reminder.reminder_type] || Bell
            return (
              <Card key={reminder.id} padding="sm">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-3 flex-1 min-w-0">
                    <TypeIcon aria-hidden="true" className="w-5 h-5 text-(--accent-fg) mt-0.5 shrink-0" />
                    <div className="min-w-0">
                      <h4 className="text-sm font-medium text-text">{reminder.title}</h4>
                      <div className="flex flex-wrap gap-2 mt-1 items-center">
                        <Chip>{reminder.reminder_type}</Chip>
                        {reminder.due_date && (
                          <span className="text-xs text-text-mute">
                            {t('reminderList.due')}: <Mono size="xs" tone="muted">{formatDate(reminder.due_date)}</Mono>
                          </span>
                        )}
                        {reminder.due_mileage_km && (
                          <span className="text-xs text-text-mute">
                            {t('reminderList.due')}: <Mono size="xs" tone="muted">{UnitFormatter.formatDistance(parseFloat(String(reminder.due_mileage_km)), system, showBoth)}</Mono>
                          </span>
                        )}
                        {/* Task 15 — hours-based target. Dimensionless: no UnitFormatter
                            conversion, unlike due_mileage_km above — fixed "hr" unit,
                            same convention as the engine-hours reading elsewhere. */}
                        {reminder.due_hours && (
                          <span className="text-xs text-text-mute">
                            <Mono size="xs" tone="muted">
                              {t('reminderList.dueAtHours', { n: Number(reminder.due_hours).toFixed(1) })}
                            </Mono>
                          </span>
                        )}
                        {reminder.estimated_due_date && (
                          <span className="text-xs text-(--accent-fg)">
                            {t('reminderList.estimated')}: <Mono size="xs" tone="accent">{formatDate(reminder.estimated_due_date)}</Mono>
                          </span>
                        )}
                      </div>
                      {reminder.notes && (
                        <p className="text-xs text-text-mute mt-1 truncate">{reminder.notes}</p>
                      )}
                      {reminder.line_item_id && (
                        <p className="text-xs text-text-mute mt-1">{t('reminderList.linkedToService')}</p>
                      )}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-1 shrink-0">
                    {reminder.status === 'pending' && (
                      <>
                        <IconButton icon={Check} label={t('reminderList.markDone')} variant="ghost" size="sm" onClick={() => handleMarkDone(reminder.id)} />
                        <IconButton icon={X} label={t('reminderList.dismiss')} variant="ghost" size="sm" onClick={() => handleDismiss(reminder.id)} />
                      </>
                    )}
                    <IconButton icon={Edit} label={t('common:edit')} variant="ghost" size="sm" onClick={() => handleEdit(reminder)} />
                    <IconButton icon={Trash2} label={t('common:delete')} variant="danger" size="sm" onClick={() => handleDelete(reminder.id)} />
                  </div>
                </div>
              </Card>
            )
          })}
        </div>
      )}

      {/* Form modal */}
      {showForm && (
        <ReminderForm
          vin={vin}
          reminder={editingReminder}
          currentMileage={currentMileage}
          currentHours={currentHours}
          onClose={handleFormClose}
          onSuccess={handleFormClose}
        />
      )}
    </div>
  )
}
