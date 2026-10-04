/**
 * Reminder list component for the Tracking tab.
 *
 * A reminder derived from a maintenance rule shows the rule's intervals, the
 * service it counts from, its due thresholds (mileage OR date, whichever
 * comes first) and, separately, the projected date the mileage is reached at
 * the current driving rate. Marking done opens the completion dialog so the
 * real date and reading anchor the next cycle. Applying a pack previews
 * first. Pending reminders of one maintenance type are flagged as possible
 * duplicates with a Review action.
 *
 * A pending row says where it stands (#192): a status chip and stripe when
 * overdue or due soon, and a bar from its start to due with what's left, all
 * computed by the server.
 */

import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Bell, Plus, Check, X, Edit, Trash2, Clock, Gauge, Zap, Timer, Package, PackagePlus, Repeat, GitMerge } from 'lucide-react'
import { toast } from 'sonner'
import {
  useReminders,
  useMarkReminderDismissed,
  useDeleteReminder,
  useReminderDuplicates,
  useReminderPacks,
  useDeletePack,
} from '../hooks/useReminders'
import { useLatestMileage } from '../hooks/useLatestMileage'
import { useLatestHours } from '../hooks/useLatestHours'
import { formatDateForDisplay } from '../utils/dateUtils'
import { useDateLocale } from '../hooks/useDateLocale'
import ReminderForm from './ReminderForm'
import CompleteReminderDialog from './CompleteReminderDialog'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import ApplyPackDialog from './ApplyPackDialog'
import SavePackDialog, { type ExistingPack } from './SavePackDialog'
import RenamePackDialog from './RenamePackDialog'
import ReconcileDuplicatesDialog from './ReconcileDuplicatesDialog'
import SnoozeReminderDialog from './SnoozeReminderDialog'
import { describeRecurrence } from './RecurrenceFields'
import { todayInHousehold } from '../constants/i18n'
import type { DuplicateGroup, Reminder, ReminderStatus } from '../types/reminder'
import type { Vehicle } from '../types/vehicle'
import { useUnitFormat } from '../hooks/useUnitFormat'
import { getUsageTracking } from '../utils/usageTracking'
import { Button, IconButton, Card, Chip, Mono, EmptyState, ProgressMeter, Select, type ProgressMeterTone } from './ui'
import api from '../services/api'

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

type DueStatus = NonNullable<Reminder['due_status']>

/** The bar's fill per status, the same colour as the row's stripe and chip. */
const METER_TONE: Record<DueStatus, ProgressMeterTone> = {
  overdue: 'danger',
  due_soon: 'warning',
  on_track: 'accent',
  snoozed: 'muted',
}

/**
 * A left stripe rather than a recoloured border: Card's base sets
 * `border-border`, and two utilities on one property resolve by stylesheet
 * order, not class order. `border-left-color` is its own property.
 */
const ROW_STRIPE: Partial<Record<DueStatus, string>> = {
  overdue: 'border-l-4 border-l-danger',
  due_soon: 'border-l-4 border-l-warning',
}

export default function ReminderList({ vin }: ReminderListProps) {
  const { t } = useTranslation('vehicles')
  const { t: tForms } = useTranslation('forms')
  const dateLocale = useDateLocale()
  const u = useUnitFormat()
  const [activeStatus, setActiveStatus] = useState<ReminderStatus | 'all'>('pending')
  const [showForm, setShowForm] = useState(false)
  const [editingReminder, setEditingReminder] = useState<Reminder | undefined>()
  const [completing, setCompleting] = useState<Reminder | undefined>()
  const [selectedPack, setSelectedPack] = useState('')
  const [previewingPack, setPreviewingPack] = useState<{ id: string; name: string } | undefined>()
  //   false        = closed
  //   true         = saving a NEW pack
  //   {id, name}   = saving this vehicle OVER that pack
  const [savingPack, setSavingPack] = useState<true | ExistingPack | false>(
    false,
  )
  const [renamingPack, setRenamingPack] = useState<{ id: string; name: string } | undefined>()
  const [reviewingGroup, setReviewingGroup] = useState<DuplicateGroup | undefined>()
  const [snoozing, setSnoozing] = useState<Reminder | undefined>()
  const [vehicle, setVehicle] = useState<Vehicle | null>(null)

  useEffect(() => {
    let cancelled = false
    void api
      .get(`/vehicles/${vin}`)
      .then((res) => {
        if (!cancelled) setVehicle(res.data ?? null)
      })
      .catch(() => {
        if (!cancelled) setVehicle(null)
      })
    return () => {
      cancelled = true
    }
  }, [vin])

  const { tracksDistance, tracksHours } = getUsageTracking({
    usage_unit: vehicle?.usage_unit,
    secondary_usage_enabled: vehicle?.secondary_usage_enabled,
  })
  const { data: packs = [] } = useReminderPacks(vehicle?.vehicle_type ?? null)
  const deletePackMutation = useDeletePack()

  const formatDate = (dateStr: string | null | undefined): string => {
    if (!dateStr) return '-'
    return formatDateForDisplay(dateStr, { year: 'numeric', month: 'short', day: 'numeric' }, dateLocale)
  }

  const { data: currentMileage } = useLatestMileage(vin)
  const { data: currentHours } = useLatestHours(vin)
  const { data: reminders = [], isLoading } = useReminders(vin, activeStatus === 'all' ? 'all' : activeStatus)
  const { data: duplicateGroups = [] } = useReminderDuplicates(vin)
  const dismissMutation = useMarkReminderDismissed(vin)
  const deleteMutation = useDeleteReminder(vin)

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

  /** The chosen pack, when it is one this user may change. Rename and delete
   *  hang off the selection rather than off a separate management screen. */
  const editablePack = packs.find((p) => p.id === selectedPack && p.is_custom && p.can_edit)

  const handleDeletePack = async (packId: string, name: string) => {
    if (!window.confirm(t('packList.deleteConfirm', { name }))) return
    try {
      await deletePackMutation.mutateAsync(packId)
      setSelectedPack('')
      toast.success(t('packList.deleted'))
    } catch (err) {
      toast.error(getActionErrorMessage(err, t('packList.delete')))
    }
  }

  const openPackPreview = () => {
    const pack = packs.find((p) => p.id === selectedPack)
    if (!pack) return
    setPreviewingPack({ id: pack.id, name: pack.name })
  }

  const anchorText = (reminder: Reminder): string | null => {
    if (!reminder.anchor_kind || !reminder.anchor_date) return null
    const reading =
      reminder.anchor_odometer_km != null
        ? u.distance.format(Number(reminder.anchor_odometer_km))
        : reminder.anchor_hours != null
          ? t('reminderList.dueAtHours', { n: Number(reminder.anchor_hours).toFixed(1) })
          : null
    if (reminder.anchor_kind === 'baseline') {
      return t('reminderList.countingFrom', { date: formatDate(reminder.anchor_date), reading: reading ?? '' })
    }
    return t('reminderList.lastDone', { date: formatDate(reminder.anchor_date), reading: reading ?? '' })
  }

  /** What is left along the dimension the bar measures, in the vehicle's units. */
  const remainingText = (reminder: Reminder): string | null => {
    switch (reminder.progress_basis) {
      case 'distance': {
        if (reminder.km_until_due == null) return null
        const km = Number(reminder.km_until_due)
        const distance = u.distance.format(Math.abs(km))
        return km < 0
          ? t('reminderList.distanceOver', { distance })
          : t('reminderList.distanceLeft', { distance })
      }
      case 'hours': {
        if (reminder.hours_until_due == null) return null
        const hours = Number(reminder.hours_until_due)
        const n = Math.abs(hours).toFixed(1)
        return hours < 0 ? t('reminderList.hoursOver', { n }) : t('reminderList.hoursLeft', { n })
      }
      case 'date': {
        const days = reminder.days_until_due
        if (days == null) return null
        if (days === 0) return t('reminderList.dueToday')
        return days < 0
          ? t('reminderList.daysOverdue', { count: -days })
          : t('reminderList.daysLeft', { count: days })
      }
      default:
        return null
    }
  }

  const rulesById = new Map<number, Reminder>()
  for (const r of reminders) rulesById.set(r.id, r)

  // Strictly-before, matching the backend's is_reminder_snoozed: on the
  // `until` date itself the snooze has expired and the chip drops.
  const today = todayInHousehold()
  const isSnoozed = (reminder: Reminder): boolean =>
    reminder.snoozed_until != null && today < reminder.snoozed_until

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

      <div className="flex flex-wrap items-end gap-2">
        {packs.length > 0 && (
          <>
            <div className="min-w-[220px] flex-1">
              <Select
                id="reminder-pack"
                aria-label={t('reminderList.applyPackAria')}
                value={selectedPack}
                onChange={(e) => setSelectedPack(e.target.value)}
                options={[
                  { value: '', label: t('reminderList.choosePack') },
                  // One list, built-in and saved together, with the saved ones
                  // marked. Two sections would stop mattering the moment you
                  // have your own.
                  ...packs.map((p) => ({
                    value: p.id,
                    label: p.is_custom ? `${p.name} (${t('packList.saved')})` : p.name,
                  })),
                ]}
              />
            </div>
            <Button
              variant="secondary"
              size="sm"
              icon={Package}
              disabled={!selectedPack}
              onClick={openPackPreview}
            >
              {t('reminderList.applyPack')}
            </Button>
          </>
        )}
        {/* Routine action, on the primary surface, away from anything
            destructive. Offered whether or not any pack exists yet: saving the
            first one is exactly when the list is empty. */}
        <Button variant="secondary" size="sm" icon={PackagePlus} onClick={() => setSavingPack(true)}>
          {t('savePack.title')}
        </Button>
        {editablePack && (
          <>
            <Button
              variant="secondary"
              size="sm"
              icon={PackagePlus}
              onClick={() => setSavingPack(editablePack)}
            >
              {t('packList.overwrite')}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={Edit}
              onClick={() => setRenamingPack({ id: editablePack.id, name: editablePack.name })}
            >
              {t('packList.rename')}
            </Button>
            <Button
              variant="danger"
              size="sm"
              icon={Trash2}
              onClick={() => void handleDeletePack(editablePack.id, editablePack.name)}
            >
              {t('packList.delete')}
            </Button>
          </>
        )}
      </div>

      {duplicateGroups.length > 0 && (
        <div className="rounded-lg border border-warning bg-warning/10 p-3 space-y-2">
          <p className="text-sm text-text">{t('reminderList.duplicatesFound', { count: duplicateGroups.length })}</p>
          <ul className="space-y-1">
            {duplicateGroups.map((group) => (
              <li key={group.maintenance_type} className="flex items-center justify-between gap-2">
                <span className="text-xs text-text-mute">
                  {t(`maintenanceTypes.${group.maintenance_type}`, { defaultValue: group.label })}
                  {' · '}
                  {t('reminderList.duplicateCount', { count: group.reminder_ids.length })}
                </span>
                <Button variant="secondary" size="sm" icon={GitMerge} onClick={() => setReviewingGroup(group)}>
                  {t('reminderList.review')}
                </Button>
              </li>
            ))}
          </ul>
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
            const recurrence = describeRecurrence(
              reminder.rule,
              (km) => u.distance.format(km),
              (key, options) => tForms(key, options),
            )
            const isDuplicate = (reminder.duplicate_of?.length ?? 0) > 0
            const anchor = anchorText(reminder)
            // Only a pending row says where it stands; a closed one keeps its history look.
            const status = reminder.status === 'pending' ? reminder.due_status ?? null : null
            const remaining = status ? remainingText(reminder) : null
            const supersededBy = reminder.superseded_by_id != null ? rulesById.get(reminder.superseded_by_id) : undefined
            return (
              <Card key={reminder.id} padding="sm" className={status ? ROW_STRIPE[status] ?? '' : ''}>
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-3 flex-1 min-w-0">
                    <TypeIcon aria-hidden="true" className="w-5 h-5 text-(--accent-fg) mt-0.5 shrink-0" />
                    <div className="min-w-0">
                      <h4 className="text-sm font-medium text-text">{reminder.title}</h4>
                      <div className="flex flex-wrap gap-2 mt-1 items-center">
                        {status === 'overdue' && <Chip tone="danger">{t('reminderList.statusOverdue')}</Chip>}
                        {status === 'due_soon' && <Chip tone="warning">{t('reminderList.statusDueSoon')}</Chip>}
                        <Chip>{reminder.reminder_type}</Chip>
                        {recurrence && reminder.rule?.is_active && (
                          <Chip tone="accent">
                            <Repeat aria-hidden="true" className="w-3 h-3" />
                            {t('reminderList.every', { interval: recurrence })}
                          </Chip>
                        )}
                        {isDuplicate && reminder.status === 'pending' && (
                          <Chip tone="warning">{t('reminderList.possibleDuplicate')}</Chip>
                        )}
                        {isSnoozed(reminder) && reminder.status === 'pending' && (
                          <Chip>{t('reminderList.snoozedUntil', { date: formatDate(reminder.snoozed_until) })}</Chip>
                        )}
                        {reminder.due_date && (
                          <span className="text-xs text-text-mute">
                            {t('reminderList.due')}: <Mono size="xs" tone="muted">{formatDate(reminder.due_date)}</Mono>
                          </span>
                        )}
                        {reminder.due_mileage_km && (
                          <span className="text-xs text-text-mute">
                            {t('reminderList.due')}: <Mono size="xs" tone="muted">{u.distance.format(parseFloat(String(reminder.due_mileage_km)))}</Mono>
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
                      {status && reminder.progress != null && (
                        <div className="mt-2 flex items-center gap-2">
                          <ProgressMeter
                            className="max-w-48 flex-1"
                            label={t('reminderList.progressLabel', { title: reminder.title })}
                            percent={reminder.progress * 100}
                            tone={METER_TONE[status]}
                            valueText={remaining ?? undefined}
                          />
                          {remaining && (
                            <span className="text-xs text-text-mute whitespace-nowrap">{remaining}</span>
                          )}
                        </div>
                      )}
                      {reminder.projected_usage_date && reminder.status === 'pending' && (
                        <p className="text-xs text-text-mute mt-1">
                          {t('reminderList.projected', { date: formatDate(reminder.projected_usage_date) })}
                        </p>
                      )}
                      {anchor && <p className="text-xs text-text-mute mt-1">{anchor}</p>}
                      {reminder.notes && (
                        <p className="text-xs text-text-mute mt-1 truncate">{reminder.notes}</p>
                      )}
                      {reminder.line_item_id && !anchor && (
                        <p className="text-xs text-text-mute mt-1">{t('reminderList.linkedToService')}</p>
                      )}
                      {reminder.status === 'done' && reminder.completed_date && (
                        <p className="text-xs text-text-mute mt-1">
                          {t('reminderList.completedOn', { date: formatDate(reminder.completed_date) })}
                        </p>
                      )}
                      {reminder.superseded_by_id != null && (
                        <p className="text-xs text-text-mute mt-1">
                          {t('reminderList.supersededBy', { title: supersededBy?.title ?? `#${reminder.superseded_by_id}` })}
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-1 shrink-0">
                    {reminder.status === 'pending' && (
                      <>
                        <IconButton icon={Check} label={t('reminderList.markDone')} variant="ghost" size="sm" onClick={() => setCompleting(reminder)} />
                        <IconButton icon={Clock} label={isSnoozed(reminder) ? t('reminderList.editSnooze') : t('reminderList.snooze')} variant="ghost" size="sm" onClick={() => setSnoozing(reminder)} />
                        <IconButton icon={X} label={reminder.rule?.is_active ? t('reminderList.dismissStopsRepeat') : t('reminderList.dismiss')} variant="ghost" size="sm" onClick={() => handleDismiss(reminder.id)} />
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

      {completing && (
        <CompleteReminderDialog
          vin={vin}
          reminder={completing}
          currentMileage={currentMileage}
          currentHours={currentHours}
          tracksDistance={tracksDistance}
          tracksHours={tracksHours}
          onClose={() => setCompleting(undefined)}
          onSuccess={() => setCompleting(undefined)}
        />
      )}

      {snoozing && (
        <SnoozeReminderDialog
          vin={vin}
          reminder={snoozing}
          onClose={() => setSnoozing(undefined)}
          onSuccess={() => setSnoozing(undefined)}
        />
      )}

      {savingPack && (
        <SavePackDialog
          vin={vin}
          vehicleType={vehicle?.vehicle_type}
          existingPack={savingPack === true ? undefined : savingPack}
          onClose={() => setSavingPack(false)}
          onSaved={() => setSavingPack(false)}
        />
      )}

      {renamingPack && (
        <RenamePackDialog
          packId={renamingPack.id}
          currentName={renamingPack.name}
          onClose={() => setRenamingPack(undefined)}
          onRenamed={() => setRenamingPack(undefined)}
        />
      )}

      {previewingPack && (
        <ApplyPackDialog
          vin={vin}
          packId={previewingPack.id}
          packName={previewingPack.name}
          onClose={() => setPreviewingPack(undefined)}
          onApplied={() => { setPreviewingPack(undefined); setSelectedPack('') }}
        />
      )}

      {reviewingGroup && (
        <ReconcileDuplicatesDialog
          vin={vin}
          group={reviewingGroup}
          onClose={() => setReviewingGroup(undefined)}
          onDone={() => setReviewingGroup(undefined)}
        />
      )}
    </div>
  )
}
