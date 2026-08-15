/**
 * Reminder create/edit form (standalone, for Tracking tab)
 *
 * Mileage input is an interval by default ("miles until due"). When
 * currentMileage is available, the form converts interval → absolute on
 * submit. Users can switch to "From last service" to enter a past odometer
 * reading + interval (due = lastDone + interval), which may already be overdue.
 * On edit, "From now" reverse-computes the remaining interval for display.
 *
 * The engine-hours target mirrors this exactly for parity: interval from now,
 * or last hours + interval. Hours stay dimensionless (no unit conversion).
 * `smart` reminders target the vehicle's PRIMARY usage dimension (mileage or
 * hours, from getUsageTracking), never both at once.
 */

import { useTranslation } from 'react-i18next'
import { useEffect, useState, type SyntheticEvent } from 'react'
import { Save, AlertTriangle } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import { Button, Field, Input, NumberInput, Textarea } from './ui'
import { toast } from 'sonner'
import { useCreateReminder, useUpdateReminder } from '../hooks/useReminders'
import type { Reminder, ReminderType } from '../types/reminder'
import type { Vehicle } from '../types/vehicle'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitConverter, UnitFormatter } from '../utils/units'
import { toCanonicalKm } from '../utils/decimalSafe'
import { parseDecimalInput } from '../utils/decimalInput'
import { getUsageTracking } from '../utils/usageTracking'
import api from '../services/api'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { applyControlledFieldErrors } from '../hooks/useApiFormErrors'
import { getActiveLocale } from '@/constants/i18n'

/** Locale-aware parse for controlled (non-RHF) numeric fields — empty vs invalid stay distinct from a real value. */
function parseOptionalDecimal(raw: string): number | undefined {
  const result = parseDecimalInput(raw, getActiveLocale())
  return result.kind === 'value' ? result.value : undefined
}

type BaselineMode = 'from_now' | 'from_last'

interface ReminderFormProps {
  vin: string
  reminder?: Reminder
  currentMileage?: number | null
  currentHours?: number | null
  onClose: () => void
  onSuccess: () => void
}

/**
 * All reminder-type definitions, keyed by value. `labelKey`/`descriptionKey`
 * are resolved through t() at render time — never store the English here.
 * The component filters/orders these per-vehicle via getUsageTracking (Task
 * 15) — hours-only vehicles never offer mileage/both, distance-only vehicles
 * never offer hours.
 */
const REMINDER_TYPE_DEFS: Record<ReminderType, { labelKey: string; descriptionKey: string }> = {
  date: { labelKey: 'reminderForm.typeDate', descriptionKey: 'reminderForm.typeDateDescription' },
  mileage: { labelKey: 'reminderForm.typeMileage', descriptionKey: 'reminderForm.typeMileageDescription' },
  hours: { labelKey: 'reminderForm.typeHours', descriptionKey: 'reminderForm.typeHoursDescription' },
  both: { labelKey: 'reminderForm.typeBoth', descriptionKey: 'reminderForm.typeBothDescription' },
  smart: { labelKey: 'reminderForm.typeSmart', descriptionKey: 'reminderForm.typeSmartDescription' },
}

export default function ReminderForm({ vin, reminder, currentMileage, currentHours, onClose, onSuccess }: ReminderFormProps) {
  const { t } = useTranslation('forms')
  const isEdit = !!reminder
  const createMutation = useCreateReminder(vin)
  const updateMutation = useUpdateReminder(vin)
  const hasMileage = currentMileage != null && currentMileage > 0
  const hasHours = currentHours != null && currentHours > 0
  const { system } = useUnitPreference()
  // currentMileage is in canonical km. Convert to user display unit when present.
  const currentDisplay = currentMileage != null
    ? (system === 'imperial' ? UnitConverter.kmToMiles(currentMileage) ?? currentMileage : currentMileage)
    : null

  // Task 15 — which usage dimension(s) this vehicle tracks, driving the
  // reminder-type options + due_hours field visibility below. Defaults mirror
  // getUsageTracking's own distance-primary default so the form doesn't
  // flash the wrong options before the vehicle fetch resolves. Independent
  // `/vehicles/{vin}` fetch, mirroring FuelRecordForm/ServiceVisitForm (Tasks
  // 13/14) rather than threading a new prop through ReminderList.
  const [vehicleUsageUnit, setVehicleUsageUnit] = useState<string>('distance')
  const [vehicleSecondaryUsageEnabled, setVehicleSecondaryUsageEnabled] = useState<boolean>(false)
  useEffect(() => {
    const fetchVehicleUsage = async () => {
      try {
        const response = await api.get(`/vehicles/${vin}`)
        const vehicleData: Vehicle = response.data
        setVehicleUsageUnit(vehicleData.usage_unit || 'distance')
        setVehicleSecondaryUsageEnabled(!!vehicleData.secondary_usage_enabled)
      } catch {
        // Silent fail - non-critical for field visibility
      }
    }
    fetchVehicleUsage()
  }, [vin])
  const { tracksDistance, tracksHours, primary } = getUsageTracking({
    usage_unit: vehicleUsageUnit,
    secondary_usage_enabled: vehicleSecondaryUsageEnabled,
  })

  // Type options filtered by which dimension(s) this vehicle tracks: hours-only
  // never offers mileage/both (backend rejects those combos for an hours-only
  // vehicle anyway), distance-only never offers hours, dual offers everything.
  const reminderTypeOrder: ReminderType[] = tracksDistance && tracksHours
    ? ['date', 'mileage', 'hours', 'both', 'smart']
    : tracksHours
      ? ['date', 'hours', 'smart']
      : ['date', 'mileage', 'both', 'smart']
  const reminderTypeOptions = reminderTypeOrder.map((value) => ({ value, ...REMINDER_TYPE_DEFS[value] }))

  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [title, setTitle] = useState(reminder?.title ?? '')
  const [reminderType, setReminderType] = useState<ReminderType>(
    (reminder?.reminder_type as ReminderType) ?? 'date'
  )
  const [dueDate, setDueDate] = useState(reminder?.due_date ?? '')
  const [mileageMode, setMileageMode] = useState<BaselineMode>('from_now')
  const [hoursMode, setHoursMode] = useState<BaselineMode>('from_now')
  const [lastDoneMileageText, setLastDoneMileageText] = useState('')
  const [lastDoneHoursText, setLastDoneHoursText] = useState('')

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
  const [mileageIntervalText, setMileageIntervalText] = useState(
    initialInterval != null ? String(initialInterval) : '',
  )

  // Task 15 (revised) — hours input is always an interval ("engine-hours
  // until due"), mirroring the mileage field above exactly. On edit, reverse-
  // compute the remaining interval (in hours — dimensionless, no unit
  // conversion) from the absolute due_hours target.
  const initialHoursInterval = (() => {
    const dh = reminder?.due_hours
    if (dh == null) return undefined
    const dhNum = typeof dh === 'string' ? parseFloat(dh) : dh
    if (isNaN(dhNum)) return undefined
    const remainingHours = currentHours != null ? Math.max(0, dhNum - currentHours) : dhNum
    return Math.round(remainingHours * 10) / 10
  })()
  const [hoursIntervalText, setHoursIntervalText] = useState(
    initialHoursInterval != null ? String(initialHoursInterval) : '',
  )

  const mileageInterval = (() => {
    const n = parseOptionalDecimal(mileageIntervalText)
    return n == null ? undefined : Math.round(n)
  })()
  const hoursInterval = parseOptionalDecimal(hoursIntervalText)
  const lastDoneMileage = (() => {
    const n = parseOptionalDecimal(lastDoneMileageText)
    return n == null ? undefined : Math.round(n)
  })()
  const lastDoneHours = parseOptionalDecimal(lastDoneHoursText)

  const [notes, setNotes] = useState(reminder?.notes ?? '')

  const mileageFromLast = hasMileage && mileageMode === 'from_last'
  const hoursFromLast = hasHours && hoursMode === 'from_last'

  // Compute target for display in user's units
  const absoluteTarget = (() => {
    if (!mileageInterval) return undefined
    if (mileageFromLast && lastDoneMileage != null) {
      return lastDoneMileage + mileageInterval
    }
    if (hasMileage && currentDisplay != null && !mileageFromLast) {
      return currentDisplay + mileageInterval
    }
    return mileageInterval
  })()

  // Hours target for display — dimensionless, so no display-unit conversion
  // (unlike absoluteTarget above), mirroring the same baseline+interval math.
  const absoluteHoursTarget = (() => {
    if (hoursInterval == null) return undefined
    if (hoursFromLast && lastDoneHours != null) {
      return lastDoneHours + hoursInterval
    }
    if (hasHours && currentHours != null && !hoursFromLast) {
      return currentHours + hoursInterval
    }
    return hoursInterval
  })()

  const mileageTargetOverdue =
    mileageFromLast &&
    absoluteTarget != null &&
    currentDisplay != null &&
    absoluteTarget <= currentDisplay

  const hoursTargetOverdue =
    hoursFromLast &&
    absoluteHoursTarget != null &&
    currentHours != null &&
    absoluteHoursTarget <= currentHours

  // Task 15 — smart reminders target the vehicle's PRIMARY dimension (keeps
  // the backend's exactly-one-of{mileage,hours} rule trivially satisfied: we
  // never populate both). A dual vehicle defaults to distance-primary unless
  // usage_unit === 'hours'.
  const smartUsesHours = reminderType === 'smart' && primary === 'hours'
  const needsMileageField = reminderType === 'mileage' || reminderType === 'both' ||
    (reminderType === 'smart' && !smartUsesHours)
  const needsHoursField = reminderType === 'hours' || smartUsesHours

  const modeButtonClass = (active: boolean) =>
    `flex-1 text-center px-3 py-2 rounded-lg border text-sm font-medium transition-colors ${
      active
        ? 'border-(--accent-line) bg-(--accent-soft) text-(--accent-fg)'
        : 'border-border bg-surface-2 text-text hover:border-(--accent-line)'
    }`

  const handleSubmit = async (e: SyntheticEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError(null)
    setFieldErrors({})

    if (!title.trim()) {
      setError(t('reminder.titleRequired'))
      return
    }

    if (['date', 'both', 'smart'].includes(reminderType) && !dueDate) {
      setError(t('reminder.dueDateRequired'))
      return
    }

    if (needsMileageField && !mileageInterval) {
      setError(t('reminder.milesRequired'))
      return
    }

    if (needsMileageField && mileageFromLast) {
      if (lastDoneMileage == null || lastDoneMileage <= 0) {
        setError(t('reminder.lastDoneMileageRequired'))
        return
      }
      if (currentDisplay != null && lastDoneMileage > currentDisplay) {
        setError(t('reminder.lastDoneExceedsCurrentMileage'))
        return
      }
    }

    if (needsHoursField && !hoursInterval) {
      setError(t('reminder.hoursRequired'))
      return
    }

    if (needsHoursField && hoursFromLast) {
      if (lastDoneHours == null || lastDoneHours <= 0) {
        setError(t('reminder.lastDoneHoursRequired'))
        return
      }
      if (currentHours != null && lastDoneHours > currentHours) {
        setError(t('reminder.lastDoneExceedsCurrentHours'))
        return
      }
    }

    // Convert user-entered values (display unit) to canonical km, then add
    // baseline for absolute target. Never sent for an hours-only or
    // smart-hours reminder — the backend rejects both metrics at once.
    const intervalKm = toCanonicalKm(mileageInterval ?? null, system)
    let due_mileage_km: number | undefined
    if (needsMileageField) {
      if (mileageFromLast && lastDoneMileage != null && intervalKm != null) {
        const lastKm = toCanonicalKm(lastDoneMileage, system)
        due_mileage_km = lastKm != null ? lastKm + intervalKm : undefined
      } else if (hasMileage && intervalKm != null && !mileageFromLast) {
        due_mileage_km = currentMileage! + intervalKm
      } else {
        due_mileage_km = intervalKm ?? undefined
      }
    }

    // due_hours mirrors due_mileage_km's baseline + interval conversion.
    let due_hours: number | undefined
    if (needsHoursField) {
      if (hoursFromLast && lastDoneHours != null && hoursInterval != null) {
        due_hours = lastDoneHours + hoursInterval
      } else if (hasHours && hoursInterval != null && !hoursFromLast) {
        due_hours = currentHours! + hoursInterval
      } else {
        due_hours = hoursInterval ?? undefined
      }
    }

    setSubmitting(true)
    try {
      if (isEdit && reminder) {
        await updateMutation.mutateAsync({
          id: reminder.id,
          title,
          reminder_type: reminderType,
          due_date: dueDate || undefined,
          due_mileage_km,
          due_hours,
          notes: notes || undefined,
        })
        toast.success(t('reminder.updated'))
      } else {
        await createMutation.mutateAsync({
          title,
          reminder_type: reminderType,
          due_date: dueDate || undefined,
          due_mileage_km,
          due_hours,
          notes: notes || undefined,
        })
        toast.success(t('reminder.created'))
      }
      onSuccess()
    } catch (err) {
      // Render targets: title, due_date, due_mileage_km, due_hours, notes.
      // `reminder_type` has no Field wrapper (it's a button group), so a
      // problem addressed to it must fall through to the banner below.
      const { attached, unhandled, errorsByField } = applyControlledFieldErrors(err, [
        'title',
        'due_date',
        'due_mileage_km',
        'due_hours',
        'notes',
      ])
      if (attached.length > 0) {
        setFieldErrors(errorsByField)
      }
      if (attached.length === 0 || unhandled.length > 0) {
        setError(getActionErrorMessage(err, t('reminder.saveAction')))
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <FormModalWrapper
      title={isEdit ? t('reminder.editTitle') : t('reminder.createTitle')}
      onClose={onClose}
      width="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={submitting}>
            {t('common:cancel')}
          </Button>
          <Button type="submit" form="reminder-form" icon={Save} loading={submitting} disabled={submitting}>
            {submitting ? t('common:saving') : isEdit ? t('common:update') : t('common:create')}
          </Button>
        </>
      }
    >
      <form id="reminder-form" onSubmit={handleSubmit} className="p-6 space-y-4">
        {error && (
          <div className="bg-danger/10 border border-danger rounded-lg p-3 flex items-center gap-2">
            <AlertTriangle aria-hidden="true" className="w-5 h-5 text-danger" />
            <p className="text-sm text-danger">{error}</p>
          </div>
        )}

        <Field id="reminder-title" label={t('common:title')} required error={fieldErrors.title}>
          <Input
            id="reminder-title"
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={t('reminder.titlePlaceholder')}
            maxLength={200}
            disabled={submitting}
          />
        </Field>

        <div>
          <label className="block text-sm font-medium text-text mb-1">
            {t('reminder.reminderType')}
          </label>
          <div className="grid grid-cols-2 gap-2">
            {reminderTypeOptions.map((type) => (
              <button
                key={type.value}
                type="button"
                onClick={() => setReminderType(type.value)}
                disabled={submitting}
                className={`text-left p-3 rounded-lg border transition-colors ${
                  reminderType === type.value
                    ? 'border-(--accent-line) bg-(--accent-soft) text-(--accent-fg)'
                    : 'border-border bg-surface-2 text-text hover:border-(--accent-line)'
                }`}
              >
                <div className="text-sm font-medium">{t(type.labelKey)}</div>
                <div className="text-xs text-text-mute mt-0.5">{t(type.descriptionKey)}</div>
              </button>
            ))}
          </div>
        </div>

        {['date', 'both', 'smart'].includes(reminderType) && (
          <Field id="reminder-due-date" label={t('reminder.dueDate')} required error={fieldErrors.due_date}>
            <Input
              id="reminder-due-date"
              type="date"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
              disabled={submitting}
            />
          </Field>
        )}

        {needsMileageField && (
          <div className="space-y-3">
            {hasMileage && (
              <div>
                <label className="block text-sm font-medium text-text mb-1">
                  {t('reminder.mileageBaseline')}
                </label>
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={submitting}
                    className={modeButtonClass(mileageMode === 'from_now')}
                    onClick={() => setMileageMode('from_now')}
                  >
                    {t('reminderForm.modeFromNow')}
                  </button>
                  <button
                    type="button"
                    disabled={submitting}
                    className={modeButtonClass(mileageMode === 'from_last')}
                    onClick={() => setMileageMode('from_last')}
                  >
                    {t('reminderForm.modeFromLast')}
                  </button>
                </div>
              </div>
            )}

            {mileageFromLast && (
              <Field
                id="reminder-last-done-mileage"
                label={t('reminder.lastDoneMileage')}
                unit={UnitFormatter.getDistanceUnit(system)}
                required
              >
                <NumberInput
                  id="reminder-last-done-mileage"
                  value={lastDoneMileageText}
                  onChange={(e) => setLastDoneMileageText(e.target.value)}
                  placeholder={
                    system === 'imperial'
                      ? t('reminderForm.lastDoneMileagePlaceholderImperial')
                      : t('reminderForm.lastDoneMileagePlaceholderMetric')
                  }
                  disabled={submitting}
                />
              </Field>
            )}

            <Field
              id="reminder-mileage"
              label={
                !hasMileage
                  ? t('reminder.dueMileage')
                  : mileageFromLast
                    ? t('reminder.mileageInterval')
                    : t('reminder.milesUntilDue')
              }
              unit={UnitFormatter.getDistanceUnit(system)}
              required
              error={fieldErrors.due_mileage_km}
            >
              <NumberInput
                id="reminder-mileage"
                value={mileageIntervalText}
                onChange={(e) => setMileageIntervalText(e.target.value)}
                placeholder={
                  hasMileage
                    ? t('reminderForm.mileageIntervalPlaceholder')
                    : system === 'imperial'
                      ? t('reminderForm.mileageAbsolutePlaceholderImperial')
                      : t('reminderForm.mileageAbsolutePlaceholderMetric')
                }
                disabled={submitting}
              />
            </Field>
            {mileageFromLast && mileageInterval && lastDoneMileage != null ? (
              <>
                <p className="text-xs text-text-mute">
                  {t('reminderForm.mileageLastTargetHint', {
                    last: Math.round(lastDoneMileage).toLocaleString(getActiveLocale()),
                    interval: mileageInterval.toLocaleString(getActiveLocale()),
                    target: Math.round(absoluteTarget ?? 0).toLocaleString(getActiveLocale()),
                    unit: UnitFormatter.getDistanceUnit(system),
                  })}
                </p>
                {mileageTargetOverdue && currentDisplay != null && (
                  <p className="text-xs text-danger">
                    {t('reminderForm.mileageLastOverdueNote', {
                      current: Math.round(currentDisplay).toLocaleString(getActiveLocale()),
                      unit: UnitFormatter.getDistanceUnit(system),
                    })}
                  </p>
                )}
              </>
            ) : hasMileage && !mileageFromLast && mileageInterval && currentDisplay != null ? (
              <p className="text-xs text-text-mute">
                {t('reminderForm.mileageTargetHint', {
                  current: Math.round(currentDisplay).toLocaleString(getActiveLocale()),
                  interval: mileageInterval.toLocaleString(getActiveLocale()),
                  target: Math.round(absoluteTarget ?? 0).toLocaleString(getActiveLocale()),
                  unit: UnitFormatter.getDistanceUnit(system),
                })}
              </p>
            ) : !hasMileage ? (
              <p className="text-xs text-warning">{t('reminder.noOdometerData')}</p>
            ) : null}
            {isEdit && hasMileage && !mileageFromLast && initialInterval !== undefined && initialInterval <= 0 && (
              <p className="text-xs text-danger">
                {t('reminder.overdueHint')}
              </p>
            )}
          </div>
        )}

        {/* Task 15 (revised) — engine-hours target, interval-based to mirror
            the mileage field above exactly. Dimensionless: no unit conversion,
            but the same current+interval / last+interval baseline math applies. */}
        {needsHoursField && (
          <div className="space-y-3">
            {hasHours && (
              <div>
                <label className="block text-sm font-medium text-text mb-1">
                  {t('reminder.hoursBaseline')}
                </label>
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={submitting}
                    className={modeButtonClass(hoursMode === 'from_now')}
                    onClick={() => setHoursMode('from_now')}
                  >
                    {t('reminderForm.modeFromNow')}
                  </button>
                  <button
                    type="button"
                    disabled={submitting}
                    className={modeButtonClass(hoursMode === 'from_last')}
                    onClick={() => setHoursMode('from_last')}
                  >
                    {t('reminderForm.modeFromLast')}
                  </button>
                </div>
              </div>
            )}

            {hoursFromLast && (
              <Field
                id="reminder-last-done-hours"
                label={t('reminder.lastDoneHours')}
                unit="hr"
                required
              >
                <NumberInput
                  id="reminder-last-done-hours"
                  value={lastDoneHoursText}
                  onChange={(e) => setLastDoneHoursText(e.target.value)}
                  placeholder={t('reminderForm.lastDoneHoursPlaceholder')}
                  disabled={submitting}
                />
              </Field>
            )}

            <Field
              id="reminder-hours"
              label={
                !hasHours
                  ? t('reminder.dueHours')
                  : hoursFromLast
                    ? t('reminder.hoursInterval')
                    : t('reminder.hoursUntilDue')
              }
              unit="hr"
              required
              error={fieldErrors.due_hours}
            >
              <NumberInput
                id="reminder-hours"
                value={hoursIntervalText}
                onChange={(e) => setHoursIntervalText(e.target.value)}
                placeholder={
                  hasHours
                    ? t('reminderForm.hoursIntervalPlaceholder')
                    : t('reminderForm.hoursAbsolutePlaceholder')
                }
                disabled={submitting}
              />
            </Field>
            {hoursFromLast && hoursInterval != null && lastDoneHours != null ? (
              <>
                <p className="text-xs text-text-mute">
                  {t('reminderForm.hoursLastTargetHint', {
                    last: lastDoneHours.toLocaleString(getActiveLocale()),
                    interval: hoursInterval.toLocaleString(getActiveLocale()),
                    target: (absoluteHoursTarget ?? 0).toLocaleString(getActiveLocale()),
                  })}
                </p>
                {hoursTargetOverdue && currentHours != null && (
                  <p className="text-xs text-danger">
                    {t('reminderForm.hoursLastOverdueNote', {
                      current: currentHours.toLocaleString(getActiveLocale()),
                    })}
                  </p>
                )}
              </>
            ) : hasHours && !hoursFromLast && hoursInterval != null && currentHours != null ? (
              <p className="text-xs text-text-mute">
                {t('reminderForm.hoursTargetHint', {
                  current: currentHours.toLocaleString(getActiveLocale()),
                  interval: hoursInterval.toLocaleString(getActiveLocale()),
                  target: (absoluteHoursTarget ?? 0).toLocaleString(getActiveLocale()),
                })}
              </p>
            ) : !hasHours ? (
              <p className="text-xs text-warning">{t('reminder.noHoursData')}</p>
            ) : null}
            {isEdit && hasHours && !hoursFromLast && initialHoursInterval !== undefined && initialHoursInterval <= 0 && (
              <p className="text-xs text-danger">
                {t('reminder.overdueHoursHint')}
              </p>
            )}
          </div>
        )}

        {reminderType === 'smart' && (
          <div className="bg-(--accent-soft) border border-(--accent-line) rounded-lg p-3">
            <p className="text-xs text-text-mute">
              {t('reminder.smartModeDescription')}
            </p>
          </div>
        )}

        <Field id="reminder-notes" label={t('common:notes')} error={fieldErrors.notes}>
          <Textarea
            id="reminder-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder={t('reminder.optionalNotes')}
            rows={2}
            disabled={submitting}
          />
        </Field>
      </form>
    </FormModalWrapper>
  )
}
