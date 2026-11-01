import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'

import { useNearestHours } from '../../hooks/queries/useHoursRecords'
import { useNearestOdometer } from '../../hooks/queries/useOdometerRecords'
import { useUnitFormat } from '../../hooks/useUnitFormat'
import { formatDateForDisplay } from '../../utils/dateUtils'
import { formatHours } from '../../utils/hoursFormat'
import { seedUnitField, type UnitFieldOrigin } from '../../utils/unitFormat'
import { Button, Field, Input, NumberInput } from '../ui'

/**
 * An odometer as typed, with the canonical value it was seeded from.
 *
 * A single value rather than a typed string plus a sibling origin: keeping
 * them in one object means a reset can never clear one and forget the other,
 * and typing can never drop the origin it has to keep carrying forward. See
 * `utils/unitFormat.ts` for what the origin is for.
 */
export interface OdometerFieldValue {
  typed: string
  origin: UnitFieldOrigin
}

/** A blank odometer field, with no canonical origin to preserve. */
export const EMPTY_ODOMETER: OdometerFieldValue = {
  typed: '',
  origin: { canonical: null, display: '' },
}

interface MountEventFieldsProps {
  vin: string
  /** Prefix for the input ids and the suggestions' test ids. */
  idPrefix: string
  dateLabel: string
  /** YYYY-MM-DD. The caller defaults it to today with `formatDateForInput()`. */
  date: string
  onDateChange: (next: string) => void
  odometerLabel: string
  odometerHint?: string
  /** The odometer as typed, in the user's distance unit, with the canonical
   *  value it was last seeded from. */
  odometer: OdometerFieldValue
  onOdometerChange: (next: OdometerFieldValue) => void
  /** Whether the vehicle takes an odometer. Defaults to true. */
  tracksDistance?: boolean
  /** Whether the vehicle takes an hour meter. Defaults to false. */
  tracksHours?: boolean
  /** The hour meter as typed. Hours are never converted. */
  hours?: string
  onHoursChange?: (next: string) => void
  hoursHint?: string
}

/** How far a suggested reading sits from the date asked about. */
function dayOffset(t: TFunction, daysAway: number): string {
  if (daysAway === 0) return t('tireList.suggestionSameDay')
  if (daysAway < 0) return t('tireList.suggestionEarlier', { count: -daysAway })
  return t('tireList.suggestionLater', { count: daysAway })
}

/**
 * A date and an odometer, with the vehicle's nearest reading offered beneath.
 * Since #217 it shows the odometer, the hour meter or both, whichever the vehicle takes.
 *
 * Used by every dialog that records where a tire went and when: Add Tire on
 * a corner, Mount, Dismount, Retire, Rotate, Set fit, and both halves of the
 * period editor. Before v3.4.0 each of those had a bare odometer input and no
 * date at all, so every operation was recorded as today.
 *
 * The suggestion is offered, never applied. It shows the reading's own date
 * and how far off it is, because the nearest reading to an installation can
 * sit on the far side of it, and only the user can judge that. Use seeds the
 * field from the reading's own canonical value, not from a re-conversion of
 * its rounded display string: on imperial units, accepting a suggestion for
 * a tire mounted at 100,000 km used to store 99,999.56 km, because the
 * "62,137 mi" it displayed was converted back to kilometres with no memory of
 * the value it came from. Typing keeps carrying the current origin forward
 * unchanged -- only Use ever replaces it -- so `canonicalFromTypedUnitField` can
 * still tell an untouched field from an edited one after a suggestion has
 * been accepted. Both boxes are typed text, read in the user's language.
 */
export default function MountEventFields({
  vin,
  idPrefix,
  dateLabel,
  date,
  onDateChange,
  odometerLabel,
  odometerHint,
  odometer,
  onOdometerChange,
  tracksDistance = true,
  tracksHours = false,
  hours = '',
  onHoursChange,
  hoursHint,
}: MountEventFieldsProps) {
  return (
    <div className="space-y-3">
      <Field id={`${idPrefix}-date`} label={dateLabel}>
        <Input
          id={`${idPrefix}-date`}
          type="date"
          value={date}
          onChange={(e) => onDateChange(e.target.value)}
        />
      </Field>
      {tracksDistance && (
        <OdometerField
          vin={vin}
          idPrefix={idPrefix}
          date={date}
          label={odometerLabel}
          hint={odometerHint}
          odometer={odometer}
          onChange={onOdometerChange}
        />
      )}
      {tracksHours && (
        <HoursField
          vin={vin}
          idPrefix={idPrefix}
          date={date}
          hint={hoursHint}
          hours={hours}
          onChange={onHoursChange ?? (() => undefined)}
        />
      )}
    </div>
  )
}

interface OdometerFieldProps {
  vin: string
  idPrefix: string
  date: string
  label: string
  hint?: string
  odometer: OdometerFieldValue
  onChange: (next: OdometerFieldValue) => void
}

/**
 * The odometer and its nearest-reading suggestion. A component of its own so
 * a vehicle without an odometer never asks for one: hooks can't be skipped,
 * components can.
 */
function OdometerField({ vin, idPrefix, date, label, hint, odometer, onChange }: OdometerFieldProps) {
  const { t } = useTranslation('vehicles')
  const u = useUnitFormat()
  const nearest = useNearestOdometer(vin, date)
  const reading = nearest.isSuccess ? (nearest.data ?? null) : undefined

  return (
    <>
      <Field id={`${idPrefix}-odometer`} label={label} hint={hint}>
        <NumberInput
          id={`${idPrefix}-odometer`}
          value={odometer.typed}
          onChange={(e) => onChange({ typed: e.target.value, origin: odometer.origin })}
        />
      </Field>
      {reading ? (
        <div
          data-testid={`${idPrefix}-suggestion`}
          className="flex flex-wrap items-center gap-2 text-sm text-text-mute"
        >
          <span>
            {t('tireList.suggestion', {
              odometer: u.distance.format(Number(reading.odometer_km)),
              date: formatDateForDisplay(reading.date),
              offset: dayOffset(t, reading.days_away),
            })}
          </span>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              const seed = seedUnitField(Number(reading.odometer_km), u.distance)
              onChange({ typed: seed.display, origin: seed })
            }}
          >
            {t('tireList.suggestionUse')}
          </Button>
        </div>
      ) : reading === null ? (
        <p className="text-sm text-text-mute">{t('tireList.suggestionNone')}</p>
      ) : null}
    </>
  )
}

interface HoursFieldProps {
  vin: string
  idPrefix: string
  date: string
  hint?: string
  hours: string
  onChange: (next: string) => void
}

/** The hour meter and its nearest-reading suggestion. Use seeds one decimal, the way the meter reads. */
function HoursField({ vin, idPrefix, date, hint, hours, onChange }: HoursFieldProps) {
  const { t } = useTranslation('vehicles')
  const nearest = useNearestHours(vin, date)
  const reading = nearest.isSuccess ? (nearest.data ?? null) : undefined

  return (
    <>
      <Field id={`${idPrefix}-hours`} label={t('common:engineHours')} unit="hr" hint={hint}>
        <NumberInput
          id={`${idPrefix}-hours`}
          value={hours}
          onChange={(e) => onChange(e.target.value)}
        />
      </Field>
      {reading ? (
        <div
          data-testid={`${idPrefix}-hours-suggestion`}
          className="flex flex-wrap items-center gap-2 text-sm text-text-mute"
        >
          <span>
            {t('tireList.suggestionHours', {
              hours: formatHours(reading.engine_hours),
              date: formatDateForDisplay(reading.date),
              offset: dayOffset(t, reading.days_away),
            })}
          </span>
          <Button size="sm" variant="ghost" onClick={() => onChange(Number(reading.engine_hours).toFixed(1))}>
            {t('tireList.suggestionUse')}
          </Button>
        </div>
      ) : reading === null ? (
        <p className="text-sm text-text-mute">{t('tireList.suggestionNoneHours')}</p>
      ) : null}
    </>
  )
}
