/**
 * Resolve pending reminders that track the same maintenance type.
 *
 * An installation upgraded from v3.4 can hold a reminder from a pack beside
 * one linked to a service for the same work. The owner picks the one to keep;
 * the others are marked superseded (dismissed with a pointer, never deleted)
 * and any rule they carried moves to the keeper or goes inactive, so the
 * duplicate cannot grow back.
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { GitMerge } from 'lucide-react'
import { toast } from 'sonner'
import FormModalWrapper from './FormModalWrapper'
import { Button, Mono } from './ui'
import { describeDue } from './RecurrenceFields'
import { useReconcileDuplicates, useReminders } from '../hooks/useReminders'
import { useUnitFormat } from '../hooks/useUnitFormat'
import { useDateLocale } from '../hooks/useDateLocale'
import { formatDateForDisplay } from '../utils/dateUtils'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import type { DuplicateGroup, Reminder } from '../types/reminder'

interface ReconcileDuplicatesDialogProps {
  vin: string
  group: DuplicateGroup
  onClose: () => void
  onDone: () => void
}

export default function ReconcileDuplicatesDialog({
  vin,
  group,
  onClose,
  onDone,
}: ReconcileDuplicatesDialogProps) {
  const { t } = useTranslation('vehicles')
  const u = useUnitFormat()
  const dateLocale = useDateLocale()
  const [keepId, setKeepId] = useState<number>(group.suggested_keep_id)
  const [error, setError] = useState<string | null>(null)
  const mutation = useReconcileDuplicates(vin)
  // The group is made of PENDING reminders, whatever tab the list is showing,
  // so the dialog reads them itself. Confirming supersedes every id in the
  // group, so it is only possible once every one of them is on screen.
  const { data: pending = [], isLoading } = useReminders(vin, 'pending')

  const members = group.reminder_ids
    .map((id) => pending.find((r) => r.id === id))
    .filter((r): r is Reminder => !!r)
  const complete = members.length === group.reminder_ids.length

  const handleConfirm = async () => {
    setError(null)
    try {
      await mutation.mutateAsync({
        keepId,
        supersedeIds: group.reminder_ids.filter((id) => id !== keepId),
      })
      toast.success(t('duplicates.resolved'))
      onDone()
    } catch (err) {
      setError(getActionErrorMessage(err, t('duplicates.action')))
    }
  }

  const describe = (r: Reminder) =>
    describeDue(r, (km) => u.distance.format(km), (iso) => formatDateForDisplay(iso, undefined, dateLocale), t)

  return (
    <FormModalWrapper
      title={t('duplicates.title', { label: group.label })}
      icon={GitMerge}
      onClose={onClose}
      width="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            {t('common:cancel')}
          </Button>
          <Button
            onClick={() => void handleConfirm()}
            loading={mutation.isPending}
            disabled={mutation.isPending || !complete}
          >
            {t('duplicates.confirm')}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-text-mute">{t('duplicates.intro')}</p>
        {!isLoading && !complete && (
          <p role="alert" className="text-sm text-warning">{t('duplicates.incomplete')}</p>
        )}
        {error && (
          <p role="alert" className="text-sm text-danger bg-danger/10 border border-danger rounded-lg p-3">
            {error}
          </p>
        )}
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-text mb-1">{t('duplicates.keep')}</legend>
          {members.map((r) => (
            <label
              key={r.id}
              className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer ${
                keepId === r.id ? 'border-(--accent-line) bg-(--accent-soft)' : 'border-border bg-surface-2'
              }`}
            >
              <input
                type="radio"
                name="duplicate-keep"
                value={r.id}
                checked={keepId === r.id}
                onChange={() => setKeepId(r.id)}
                className="mt-1"
              />
              <span className="min-w-0">
                <span className="block text-sm font-medium text-text">{r.title}</span>
                <span className="block text-xs text-text-mute">
                  {r.rule ? t('duplicates.recurring') : r.line_item_id ? t('reminderList.linkedToService') : t('duplicates.oneOff')}
                </span>
                {describe(r) && (
                  <Mono size="xs" tone="muted">
                    {describe(r)}
                  </Mono>
                )}
              </span>
            </label>
          ))}
        </fieldset>
      </div>
    </FormModalWrapper>
  )
}
