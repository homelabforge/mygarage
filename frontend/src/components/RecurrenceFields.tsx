/**
 * The intervals of a maintenance rule: distance (typed in the client's
 * distance unit, stored as canonical km), calendar months, and engine hours
 * for vehicles that track them.
 *
 * The distance field goes through `seedUnitField` / `canonicalFromTypedUnitField`
 * like every other unit-bearing input, so an untouched field hands back the
 * exact canonical value it was seeded from rather than a re-conversion of a
 * rounded display.
 *
 * Every field is read when it's typed, in that moment's locale, and the draft
 * keeps the number. So each NumberInput says `parsedOnChange` and its hint
 * keeps that locale too, even if the language changes before the save.
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Field, NumberInput } from './ui'
import { useUnitFormat } from '../hooks/useUnitFormat'
import { canonicalFromTypedUnitField, seedUnitField, type UnitFieldOrigin } from '../utils/unitFormat'
import { parseOptionalDecimal } from '../utils/decimalInput'
import type { RecurrenceDraft } from '../types/reminder'

interface RecurrenceFieldsProps {
  idPrefix: string
  value: RecurrenceDraft
  onChange: (next: RecurrenceDraft) => void
  tracksDistance: boolean
  tracksHours: boolean
  disabled?: boolean
  errors?: Partial<Record<keyof RecurrenceDraft, string>>
}

export default function RecurrenceFields({
  idPrefix,
  value,
  onChange,
  tracksDistance,
  tracksHours,
  disabled,
  errors,
}: RecurrenceFieldsProps) {
  const { t } = useTranslation('forms')
  const u = useUnitFormat()
  const [kmOrigin] = useState<UnitFieldOrigin>(() => seedUnitField(value.interval_km ?? null, u.distance))
  const [kmText, setKmText] = useState(kmOrigin.display)
  const [monthsText, setMonthsText] = useState(value.interval_months != null ? String(value.interval_months) : '')
  // Day intervals come from packs. The field is shown when the rule has one,
  // so editing that rule round-trips it instead of dropping it.
  const [showDays] = useState(value.interval_days != null)
  const [daysText, setDaysText] = useState(value.interval_days != null ? String(value.interval_days) : '')
  const [hoursText, setHoursText] = useState(value.interval_hours != null ? String(value.interval_hours) : '')

  const emit = (patch: Partial<RecurrenceDraft>) => onChange({ ...value, ...patch })

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {tracksDistance && (
        <Field
          id={`${idPrefix}-interval-km`}
          label={t('recurrence.everyDistance')}
          unit={u.distance.label}
          error={errors?.interval_km}
        >
          <NumberInput
            id={`${idPrefix}-interval-km`}
            value={kmText}
            onChange={(e) => {
              setKmText(e.target.value)
              const km = canonicalFromTypedUnitField(e.target.value, kmOrigin, u.distance)
              emit({ interval_km: km == null ? undefined : km })
            }}
            placeholder={t('recurrence.distancePlaceholder')}
            disabled={disabled}
            parsedOnChange
          />
        </Field>
      )}
      <Field
        id={`${idPrefix}-interval-months`}
        label={t('recurrence.everyMonths')}
        unit={t('recurrence.monthsUnit')}
        error={errors?.interval_months}
      >
        <NumberInput
          id={`${idPrefix}-interval-months`}
          value={monthsText}
          onChange={(e) => {
            setMonthsText(e.target.value)
            const months = parseOptionalDecimal(e.target.value)
            emit({ interval_months: months == null ? undefined : Math.round(months) })
          }}
          placeholder={t('recurrence.monthsPlaceholder')}
          disabled={disabled}
          parsedOnChange
        />
      </Field>
      {showDays && (
        <Field
          id={`${idPrefix}-interval-days`}
          label={t('recurrence.everyDays')}
          unit={t('recurrence.daysUnit')}
          error={errors?.interval_days}
        >
          <NumberInput
            id={`${idPrefix}-interval-days`}
            value={daysText}
            onChange={(e) => {
              setDaysText(e.target.value)
              const days = parseOptionalDecimal(e.target.value)
              emit({ interval_days: days == null ? undefined : Math.round(days) })
            }}
            placeholder={t('recurrence.daysPlaceholder')}
            disabled={disabled}
            parsedOnChange
          />
        </Field>
      )}
      {tracksHours && (
        <Field
          id={`${idPrefix}-interval-hours`}
          label={t('recurrence.everyHours')}
          unit="hr"
          error={errors?.interval_hours}
        >
          <NumberInput
            id={`${idPrefix}-interval-hours`}
            value={hoursText}
            onChange={(e) => {
              setHoursText(e.target.value)
              const hours = parseOptionalDecimal(e.target.value)
              emit({ interval_hours: hours == null ? undefined : hours })
            }}
            placeholder={t('recurrence.hoursPlaceholder')}
            disabled={disabled}
            parsedOnChange
          />
        </Field>
      )}
    </div>
  )
}

/** The rule's intervals as one short line: "8,000 km / 6 mo". */
export function describeRecurrence(
  rule: { interval_km?: number | string | null; interval_months?: number | null; interval_days?: number | null; interval_hours?: number | string | null } | null | undefined,
  format: (km: number) => string,
  t: (key: string, options?: Record<string, unknown>) => string,
): string | null {
  if (!rule) return null
  const parts: string[] = []
  const km = rule.interval_km != null ? Number(rule.interval_km) : null
  if (km != null && !Number.isNaN(km)) parts.push(format(km))
  if (rule.interval_months) parts.push(t('recurrence.monthsShort', { count: rule.interval_months }))
  if (rule.interval_days) parts.push(t('recurrence.daysShort', { count: rule.interval_days }))
  const hours = rule.interval_hours != null ? Number(rule.interval_hours) : null
  if (hours != null && !Number.isNaN(hours)) parts.push(t('recurrence.hoursShort', { count: hours }))
  return parts.length ? parts.join(' / ') : null
}

/** A reminder's thresholds as one short line: "151,064 km or Dec 13, 2026". */
export function describeDue(
  due: {
    due_date?: string | null
    due_mileage_km?: number | string | null
    due_hours?: number | string | null
  },
  formatKm: (km: number) => string,
  formatDate: (iso: string) => string,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  const parts: string[] = []
  if (due.due_mileage_km != null) parts.push(formatKm(Number(due.due_mileage_km)))
  if (due.due_date) parts.push(formatDate(due.due_date))
  if (due.due_hours != null) parts.push(t('vehicles:reminderList.dueAtHours', { n: Number(due.due_hours).toFixed(1) }))
  return parts.join(` ${t('vehicles:reminderList.or')} `)
}
