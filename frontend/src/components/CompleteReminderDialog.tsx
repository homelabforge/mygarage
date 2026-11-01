/**
 * Complete a reminder with the date and reading the work was actually done at.
 *
 * Three modes: log a service visit (default, one typed line item), link an
 * existing visit, or just record the completion. For a recurring reminder
 * the backend anchors the next cycle on what is entered here, never on the
 * vehicle's newest odometer record, which is the defect this dialog replaces
 * ("mark done" used to flip a status and nothing else).
 */

import { useState, type SyntheticEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { CheckCircle2 } from 'lucide-react'
import { toast } from 'sonner'
import FormModalWrapper from './FormModalWrapper'
import VendorSearch from './VendorSearch'
import { Button, Field, Input, NumberInput, Select, Textarea } from './ui'
import { useCompleteReminder } from '../hooks/useReminders'
import { useServiceVisitPages } from '../hooks/queries/useServiceVisits'
import { useUnitFormat } from '../hooks/useUnitFormat'
import { useDateLocale } from '../hooks/useDateLocale'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'
import { canonicalFromTypedUnitField, seedUnitField, type UnitFieldOrigin } from '../utils/unitFormat'
import { formatDateForDisplay, formatDateForInput } from '../utils/dateUtils'
import { parseOptionalDecimal } from '../utils/decimalInput'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { moneyTextError } from '../schemas/shared'
import type { Reminder, ReminderCompleteRequest } from '../types/reminder'
import { withUnitSession } from '../contexts/UnitSession'

type Mode = ReminderCompleteRequest['mode']

interface CompleteReminderDialogProps {
  vin: string
  reminder: Reminder
  currentMileage?: number | null
  currentHours?: number | null
  tracksDistance: boolean
  tracksHours: boolean
  onClose: () => void
  onSuccess: () => void
}

function CompleteReminderDialog({
  vin,
  reminder,
  currentMileage,
  currentHours,
  tracksDistance,
  tracksHours,
  onClose,
  onSuccess,
}: CompleteReminderDialogProps) {
  const { t } = useTranslation('vehicles')
  const u = useUnitFormat()
  const dateLocale = useDateLocale()
  const { currencyCode } = useCurrencyPreference()
  const completeMutation = useCompleteReminder(vin)
  const [mode, setMode] = useState<Mode>('create_visit')
  // The visit list is only for linking; the default mode never fetches it.
  const linking = mode === 'link_visit'
  const {
    data: visitPages,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
  } = useServiceVisitPages(vin, { enabled: linking })

  const [completedDate, setCompletedDate] = useState(formatDateForInput())
  const [odometerOrigin] = useState<UnitFieldOrigin>(() => seedUnitField(currentMileage ?? null, u.distance))
  const [odometerText, setOdometerText] = useState(odometerOrigin.display)
  const [hoursText, setHoursText] = useState(currentHours != null ? String(currentHours) : '')
  const [visitId, setVisitId] = useState<string>('')
  const [vendorId, setVendorId] = useState<number | undefined>()
  const [costText, setCostText] = useState('')
  const [costError, setCostError] = useState<string | undefined>()
  const [notes, setNotes] = useState('')
  const [error, setError] = useState<string | null>(null)
  const submitting = completeMutation.isPending

  const recurring = !!reminder.rule && reminder.rule.is_active
  const visits = visitPages?.pages.flatMap((page) => page.visits) ?? []

  const handleSubmit = async (e: SyntheticEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError(null)
    if (linking && !visitId) {
      setError(t('completeReminder.visitRequired'))
      return
    }
    if (!linking && !completedDate) {
      setError(t('completeReminder.dateRequired'))
      return
    }
    // Only the visit it creates takes a cost, so only that mode checks it.
    const costProblem = mode === 'create_visit' ? moneyTextError(t, costText) : undefined
    setCostError(costProblem)
    if (costProblem) return
    // A linked visit is the service record: the backend takes its date and
    // readings, so the dialog sends the visit's date and no readings of its own.
    const linkedVisit = linking ? visits.find((v) => String(v.id) === visitId) : undefined
    const odometerKm = !linking && tracksDistance ? canonicalFromTypedUnitField(odometerText, odometerOrigin, u.distance) : null
    const hours = !linking && tracksHours ? parseOptionalDecimal(hoursText) : undefined
    const cost = parseOptionalDecimal(costText)
    try {
      const result = await completeMutation.mutateAsync({
        id: reminder.id,
        completed_date: linkedVisit ? linkedVisit.date.split('T')[0] : completedDate,
        odometer_km: odometerKm ?? undefined,
        engine_hours: hours,
        mode,
        service_visit_id: mode === 'link_visit' ? Number(visitId) : undefined,
        vendor_id: mode === 'create_visit' ? vendorId : undefined,
        cost: mode === 'create_visit' ? cost : undefined,
        notes: mode === 'create_visit' && notes ? notes : undefined,
      })
      const next = result.next_reminder
      if (next?.due_date) {
        toast.success(
          t('completeReminder.doneNextDue', {
            date: formatDateForDisplay(next.due_date, undefined, dateLocale),
          }),
        )
      } else if (next?.due_mileage_km != null) {
        toast.success(
          t('completeReminder.doneNextDueAt', {
            reading: u.distance.format(Number(next.due_mileage_km)),
          }),
        )
      } else {
        toast.success(t('completeReminder.done'))
      }
      onSuccess()
    } catch (err) {
      setError(getActionErrorMessage(err, t('completeReminder.action')))
    }
  }

  const modeOptions: { value: Mode; label: string; description: string }[] = [
    {
      value: 'create_visit',
      label: t('completeReminder.modeCreate'),
      description: t('completeReminder.modeCreateHelp'),
    },
    {
      value: 'link_visit',
      label: t('completeReminder.modeLink'),
      description: t('completeReminder.modeLinkHelp'),
    },
    {
      value: 'mark_only',
      label: t('completeReminder.modeMarkOnly'),
      description: t('completeReminder.modeMarkOnlyHelp'),
    },
  ]

  return (
    <FormModalWrapper
      title={t('completeReminder.title', { title: reminder.title })}
      icon={CheckCircle2}
      onClose={onClose}
      width="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={submitting}>
            {t('common:cancel')}
          </Button>
          <Button type="submit" form="complete-reminder-form" loading={submitting} disabled={submitting}>
            {t('completeReminder.confirm')}
          </Button>
        </>
      }
    >
      <form id="complete-reminder-form" onSubmit={handleSubmit} className="p-6 space-y-4">
        {error && (
          <p role="alert" className="text-sm text-danger bg-danger/10 border border-danger rounded-lg p-3">
            {error}
          </p>
        )}
        {recurring && (
          <p className="text-xs text-text-mute">{t('completeReminder.recurringHint')}</p>
        )}

        {!linking && (
        <Field id="complete-date" label={t('completeReminder.completedDate')} required>
          <Input
            id="complete-date"
            type="date"
            value={completedDate}
            onChange={(e) => setCompletedDate(e.target.value)}
            disabled={submitting}
          />
        </Field>

        )}

        {!linking && tracksDistance && (
          <Field id="complete-odometer" label={t('completeReminder.odometer')} unit={u.distance.label}>
            <NumberInput
              id="complete-odometer"
              value={odometerText}
              onChange={(e) => setOdometerText(e.target.value)}
              disabled={submitting}
            />
          </Field>
        )}
        {!linking && tracksHours && (
          <Field id="complete-hours" label={t('completeReminder.hours')} unit="hr">
            <NumberInput
              id="complete-hours"
              value={hoursText}
              onChange={(e) => setHoursText(e.target.value)}
              disabled={submitting}
            />
          </Field>
        )}

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-text mb-1">{t('completeReminder.mode')}</legend>
          {modeOptions.map((option) => (
            <label
              key={option.value}
              className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer ${
                mode === option.value
                  ? 'border-(--accent-line) bg-(--accent-soft)'
                  : 'border-border bg-surface-2'
              }`}
            >
              <input
                type="radio"
                name="complete-mode"
                value={option.value}
                checked={mode === option.value}
                onChange={() => setMode(option.value)}
                disabled={submitting}
                className="mt-1"
              />
              <span className="min-w-0">
                <span className="block text-sm font-medium text-text">{option.label}</span>
                <span className="block text-xs text-text-mute">{option.description}</span>
              </span>
            </label>
          ))}
        </fieldset>

        {mode === 'link_visit' && (
          <Field id="complete-visit" label={t('completeReminder.visit')} required>
            <Select
              id="complete-visit"
              value={visitId}
              onChange={(e) => setVisitId(e.target.value)}
              disabled={submitting}
              placeholder={t('completeReminder.chooseVisit')}
              options={visits.map((visit) => ({
                value: String(visit.id),
                label: [
                  formatDateForDisplay(visit.date, undefined, dateLocale),
                  visit.line_items?.[0]?.description ?? '',
                  visit.vendor?.name ?? '',
                ]
                  .filter(Boolean)
                  .join(' · '),
              }))}
            />
          </Field>
        )}
        {linking && (
          <div className="space-y-2">
            <p className="text-xs text-text-mute">{t('completeReminder.linkUsesVisit')}</p>
            {hasNextPage && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => void fetchNextPage()}
                loading={isFetchingNextPage}
                disabled={isFetchingNextPage || submitting}
              >
                {t('completeReminder.showOlderVisits')}
              </Button>
            )}
          </div>
        )}

        {mode === 'create_visit' && (
          <>
            <Field id="complete-vendor" label={t('completeReminder.vendor')}>
              <VendorSearch
                id="complete-vendor"
                value={vendorId}
                onSelect={(vendor) => setVendorId(vendor?.id)}
                disabled={submitting}
              />
            </Field>
            <Field id="complete-cost" label={t('completeReminder.cost')} unit={currencyCode} error={costError}>
              <NumberInput
                id="complete-cost"
                value={costText}
                onChange={(e) => {
                  setCostText(e.target.value)
                  setCostError(undefined)
                }}
                invalid={!!costError}
                disabled={submitting}
              />
            </Field>
            <Field id="complete-notes" label={t('common:notes')}>
              <Textarea
                id="complete-notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={2}
                disabled={submitting}
              />
            </Field>
          </>
        )}
      </form>
    </FormModalWrapper>
  )
}

// Pins its units for as long as it is open (R4).
export default withUnitSession(CompleteReminderDialog)
