import { useId, useState } from 'react'
import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { Button, NumberInput } from '@/components/ui'
import { getActiveLocale } from '@/constants/i18n'
import { livelinkService } from '@/services/livelinkService'
import type { DeviceReading, LiveLinkParameterUpdate } from '@/types/livelink'
import { parseDecimalInput } from '@/utils/decimalInput'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'
import { sensorReadingName } from '@/utils/sensorReadings'
import { getParamDisplayName } from '@/utils/telemetryUnits'

/**
 * One preset sensor's alert lines: a tank's level warns below Low and again
 * below Critical, its battery below Low. Set per sensor, so two tanks can
 * differ.
 *
 * The lines colour the Live tab's tank card, and the server sends one
 * notification each time a reading drops below one (it re-arms once the
 * reading is back clear, after a refill). Only percent readings offer lines,
 * so a field takes 0 to 100 as typed. A blank field switches its line off.
 */

type Line = NonNullable<DeviceReading['alert_lines']>[number]

const FIELD = { low: 'warning_min', critical: 'critical_min' } as const

interface Props {
  readings: DeviceReading[]
  /** Dropped from the front of each reading's name, as in the readings list. */
  sensorLabel?: string
  /** Called after a save, so the block reloads the readings. */
  onSaved: () => void
}

/** What each field shows, keyed `${param_key}:${line}`. */
type Drafts = Record<string, string>

const draftKey = (paramKey: string, line: Line): string => `${paramKey}:${line}`

const linesOf = (reading: DeviceReading): Line[] => reading.alert_lines ?? []

function draftsFor(readings: DeviceReading[]): Drafts {
  const drafts: Drafts = {}
  for (const reading of readings) {
    for (const line of linesOf(reading)) {
      const value = reading[FIELD[line]]
      drafts[draftKey(reading.param_key, line)] = value == null ? '' : String(value)
    }
  }
  return drafts
}

interface Parsed {
  line: Line
  value: number | null | 'invalid'
}

const isSettable = (p: Parsed): p is Parsed & { value: number | null } => p.value !== 'invalid'

/** A field's line: null when blank (off), 'invalid' when not a percentage. */
function parseLine(text: string): number | null | 'invalid' {
  const result = parseDecimalInput(text, getActiveLocale())
  if (result.kind === 'empty') return null
  if (result.kind === 'invalid' || result.value < 0 || result.value > 100) return 'invalid'
  return result.value
}

export default function SensorAlerts({ readings, sensorLabel, onSaved }: Props): ReactElement | null {
  const { t } = useTranslation('settings')
  const headingId = useId()
  const fieldIdPrefix = useId()
  const [drafts, setDrafts] = useState<Drafts>(() => draftsFor(readings))
  const [saveError, setSaveError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // New readings (after a save, a rename, a relink) show what the server
  // holds. React's "adjust state when a prop changes" pattern, not an effect:
  // it runs before the stale render.
  const [seen, setSeen] = useState(readings)
  if (readings !== seen) {
    setSeen(readings)
    setDrafts(draftsFor(readings))
    setSaveError(null)
  }

  const rows = readings.flatMap((reading) => {
    const lines = linesOf(reading)
    if (lines.length === 0) return []

    const parsed = lines.map((line) => ({
      line,
      value: parseLine(drafts[draftKey(reading.param_key, line)] ?? ''),
    }))
    let problem: string | null = null
    // Sent on save: only a valid change.
    let update: LiveLinkParameterUpdate | null = null
    if (!parsed.every(isSettable)) {
      problem = t('integrations.alertRange')
    } else {
      const low = parsed.find((p) => p.line === 'low')?.value
      const critical = parsed.find((p) => p.line === 'critical')?.value
      if (low != null && critical != null && critical >= low) {
        problem = t('integrations.alertCriticalBelowLow')
      } else if (parsed.some(({ line, value }) => value !== (reading[FIELD[line]] ?? null))) {
        update = {}
        for (const { line, value } of parsed) update[FIELD[line]] = value
      }
    }

    const name = sensorReadingName(getParamDisplayName(reading.param_key, reading.display_name ?? null), sensorLabel)
    return [{ reading, lines, name, problem, update }]
  })

  if (rows.length === 0) return null

  const blocked = rows.some((row) => row.problem !== null)
  const toSave = rows.flatMap(({ reading, update }) => (update ? [{ paramKey: reading.param_key, update }] : []))

  const save = async (): Promise<void> => {
    setBusy(true)
    setSaveError(null)
    try {
      await Promise.all(toSave.map(({ paramKey, update }) => livelinkService.updateParameter(paramKey, update)))
      toast.success(t('integrations.alertsSaved'))
      onSaved()
    } catch (error) {
      setSaveError(getActionErrorMessage(error, t('integrations.saveAlertsAction')))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section aria-labelledby={headingId} className="space-y-2 border-t border-border pt-2">
      <div>
        <h5 id={headingId} className="text-xs font-semibold text-text">
          {t('integrations.alertsHeading')}
        </h5>
        <p className="text-xs text-text-mute">{t('integrations.alertsHint')}</p>
      </div>

      {rows.map(({ reading, lines, name, problem }) => (
        <div key={reading.param_key} className="space-y-1">
          {/* Top-aligned so a read-as hint growing one field doesn't shift the row. */}
          <div className="flex flex-wrap items-start gap-x-4 gap-y-1">
            <span className="flex h-input-sm w-20 items-center text-sm text-text">{name}</span>
            {lines.map((line) => {
              const lineName = line === 'low' ? t('integrations.alertLow') : t('integrations.alertCritical')
              const key = draftKey(reading.param_key, line)
              const inputId = `${fieldIdPrefix}-${key}`
              return (
                <div key={line} className="flex items-start gap-1.5 text-xs text-text-mute">
                  {/* Paired by id, not wrapped, so NumberInput's hint stays out of the label. */}
                  <label htmlFor={inputId} className="flex h-input-sm items-center">
                    {lineName}
                  </label>
                  {/* The control (first child) gets the 5rem; the hint under it gets its own width. */}
                  <div className="flex shrink-0 flex-col [&>:first-child]:w-20">
                    <NumberInput
                      id={inputId}
                      size="sm"
                      aria-label={t('integrations.alertField', { reading: name, line: lineName })}
                      placeholder={t('integrations.alertOff')}
                      suffix={reading.unit ?? undefined}
                      invalid={problem !== null}
                      value={drafts[key] ?? ''}
                      disabled={busy}
                      onChange={(e) => {
                        const text = e.target.value
                        setDrafts((current) => ({ ...current, [key]: text }))
                      }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
          {problem ? (
            <p role="alert" className="text-xs text-danger">
              {problem}
            </p>
          ) : null}
        </div>
      ))}

      {saveError ? (
        <p role="alert" className="text-xs text-danger">
          {saveError}
        </p>
      ) : null}
      <div className="flex justify-end">
        <Button
          size="sm"
          variant="secondary"
          disabled={busy || blocked || toSave.length === 0}
          onClick={() => void save()}
        >
          {t('integrations.saveAlerts')}
        </Button>
      </div>
    </section>
  )
}
