import { useId, useRef, useState } from 'react'
import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus } from 'lucide-react'

import { Button, Field, Input, Select } from '@/components/ui'
import { livelinkService } from '@/services/livelinkService'
import type { LiveLinkDevice } from '@/types/livelink'
import type { PresetInfo } from '@/types/livelinkTopicMap'
import type { Vehicle } from '@/types/vehicle'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'
import { presetReadingLabel } from '../presetText'
import { discoveryFilter, suggestTopics } from './suggestTopics'

/**
 * Add one sensor from a preset: a name, a vehicle, and the topic its level
 * arrives on. The other readings' topics are then suggested, each editable.
 *
 * Where a gateway publishes is its owner's choice, so nothing here assumes a
 * layout. On leaving the level field the form listens to the broker for a few
 * seconds under the level topic's own shape and suggests what it hears,
 * matched by keyword (see `suggestTopics`). When it hears nothing it falls
 * back to the reference names. A field the operator has typed in is never
 * overwritten by a later suggestion, and an empty field is simply not mapped.
 *
 * Adding does not wait for the listen: the suggestions are a convenience, and
 * someone who has typed every topic has nothing to wait for.
 */

interface Props {
  preset: PresetInfo
  vehicles: Vehicle[]
  onCreated: (device: LiveLinkDevice) => void
  onCancel?: () => void
}

/** How long to listen for the sensor's other readings. Long enough for a
 *  gateway that publishes every few seconds; retained topics arrive at once. */
const LISTEN_SECONDS = 5

const hasWildcard = (topic: string): boolean => topic.includes('+') || topic.includes('#')

export default function SensorForm({ preset, vehicles, onCreated, onCancel }: Props): ReactElement {
  const { t } = useTranslation('settings')
  const idBase = useId()
  const levelReading = preset.readings.find((r) => r.required) ?? preset.readings[0]
  const others = preset.readings.filter((r) => r !== levelReading)

  const [label, setLabel] = useState('')
  const [vin, setVin] = useState('')
  const [level, setLevel] = useState('')
  const [topics, setTopics] = useState<Record<string, string>>({})
  // A ref, not state: the suggestion lands after a network wait and must see
  // edits made DURING the wait, which a captured state value would miss.
  const edited = useRef<Set<string>>(new Set())
  // The level topic last listened for, so leaving the field again without
  // changing it does not listen again; and a count of listens, so an answer
  // for a level since changed is dropped rather than applied.
  const listenedFor = useRef<string | null>(null)
  const listens = useRef(0)
  const [listening, setListening] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const suggest = async (): Promise<void> => {
    const levelTopic = level.trim()
    const filter = discoveryFilter(levelTopic, preset.readings)
    if (!filter || hasWildcard(levelTopic) || levelTopic === listenedFor.current) return
    listenedFor.current = levelTopic
    const run = ++listens.current
    setListening(true)
    let heard: string[]
    try {
      heard = (await livelinkService.discoverTopics(filter, LISTEN_SECONDS)).map((d) => d.topic)
    } catch {
      // No broker, or a discovery already running: fall back to the
      // reference names, which the operator can edit.
      heard = []
    }
    if (run !== listens.current) return
    setListening(false)
    const suggested = suggestTopics(levelTopic, preset.readings, heard)
    setTopics((current) => {
      const next = { ...current }
      for (const reading of others) {
        if (!edited.current.has(reading.suffix)) next[reading.suffix] = suggested[reading.suffix] ?? ''
      }
      return next
    })
  }

  const edit = (suffix: string, value: string): void => {
    edited.current.add(suffix)
    setTopics((current) => ({ ...current, [suffix]: value }))
  }

  const chosen = Object.fromEntries(
    [[levelReading.suffix, level.trim()], ...others.map((r) => [r.suffix, (topics[r.suffix] ?? '').trim()])].filter(
      ([, topic]) => topic !== '',
    ),
  ) as Record<string, string>
  const wildcard = Object.values(chosen).some(hasWildcard)
  // One topic carries one reading; the server refuses a repeat too, but by
  // then the operator has lost which two fields it meant.
  const repeated = new Set(Object.values(chosen)).size !== Object.keys(chosen).length
  const ready = label.trim() !== '' && level.trim() !== '' && !wildcard && !repeated && !busy

  const submit = async (): Promise<void> => {
    setError(null)
    setBusy(true)
    try {
      const device = await livelinkService.applyPreset(preset.name, {
        label: label.trim(),
        vin: vin || null,
        topics: chosen,
      })
      onCreated(device)
    } catch (err) {
      // The server's own words: a topic another device already maps is a 409
      // that names it, and a generic failure would hide which one.
      setError(getActionErrorMessage(err, t('integrations.addSensorAction')))
    } finally {
      setBusy(false)
    }
  }

  const id = (name: string): string => `${idBase}-${name}`

  return (
    <div className="space-y-3">
      {error ? (
        <p className="text-sm text-danger" role="alert">
          {error}
        </p>
      ) : null}
      <div className="grid gap-x-4 sm:grid-cols-2">
        <Field id={id('label')} label={t('integrations.sensorName')} required>
          <Input
            id={id('label')}
            value={label}
            maxLength={60}
            placeholder={t('integrations.sensorNamePlaceholder')}
            onChange={(e) => setLabel(e.target.value)}
          />
        </Field>
        <Field id={id('vehicle')} label={t('integrations.sourceVehicle')} hint={t('integrations.sourceVehicleHint')}>
          <Select
            id={id('vehicle')}
            value={vin}
            onChange={(e) => setVin(e.target.value)}
            placeholder={t('integrations.sourceVehicleUnset')}
            options={vehicles.map((v) => ({
              value: v.vin,
              label: v.nickname || `${v.year} ${v.make} ${v.model}`,
            }))}
          />
        </Field>
      </div>
      <Field
        id={id('level')}
        label={t('integrations.levelTopic')}
        hint={t('integrations.levelTopicHint')}
        error={hasWildcard(level) ? t('integrations.mqttErrorsTopicMustBeExact') : undefined}
        required
      >
        <Input
          id={id('level')}
          mono
          value={level}
          maxLength={255}
          invalid={hasWildcard(level)}
          onChange={(e) => setLevel(e.target.value)}
          onBlur={() => void suggest()}
        />
      </Field>

      <fieldset className="space-y-1">
        <legend className="text-sm font-semibold text-text">{t('integrations.otherReadings')}</legend>
        <p className="text-xs text-text-mute">
          {listening ? t('integrations.listeningForReadings') : t('integrations.otherReadingsHint')}
        </p>
        {repeated ? (
          <p className="text-xs text-danger" role="alert">
            {t('integrations.readingTopicsRepeat')}
          </p>
        ) : null}
        <div className="grid gap-x-4 sm:grid-cols-2">
          {others.map((reading) => {
            const value = topics[reading.suffix] ?? ''
            return (
              <Field
                key={reading.suffix}
                id={id(reading.suffix)}
                label={presetReadingLabel(preset.name, reading, t)}
                error={hasWildcard(value) ? t('integrations.mqttErrorsTopicMustBeExact') : undefined}
              >
                <Input
                  id={id(reading.suffix)}
                  mono
                  size="sm"
                  value={value}
                  maxLength={255}
                  invalid={hasWildcard(value)}
                  onChange={(e) => edit(reading.suffix, e.target.value)}
                />
              </Field>
            )
          })}
        </div>
      </fieldset>

      <div className="flex gap-2">
        <Button size="sm" icon={Plus} disabled={!ready} loading={busy} onClick={() => void submit()}>
          {t('integrations.addSensor')}
        </Button>
        {onCancel ? (
          <Button size="sm" variant="secondary" onClick={onCancel}>
            {t('common:cancel')}
          </Button>
        ) : null}
      </div>
    </div>
  )
}
