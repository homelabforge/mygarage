import { useCallback, useEffect, useId, useState } from 'react'
import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { Trash2 } from 'lucide-react'

import { Button, Field, Input } from '@/components/ui'
import { livelinkService } from '@/services/livelinkService'
import type { TopicMap } from '@/types/livelinkTopicMap'
import { paramKeyFromTopic } from '@/types/livelinkTopicMap'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'

/**
 * One MQTT device's topic mappings: which exact topic feeds which parameter.
 *
 * Moved from MqttSourcesCard, where it was the whole card. For a preset device
 * the preset wrote these rows and nobody needs to see them, so the drawer
 * tucks this under "Advanced"; for a handmade device it is the point, and the
 * drawer opens it. Create and delete now report their failures; the card's
 * versions had no catch.
 */

interface Props {
  deviceId: string
  /** A mapping changed what the device reports: refetch its readings. */
  onMappingsChanged: () => void
}

export default function TopicMapEditor({ deviceId, onMappingsChanged }: Props): ReactElement {
  const { t } = useTranslation('settings')
  const idBase = useId()
  const [maps, setMaps] = useState<TopicMap[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [topic, setTopic] = useState('')
  const [paramKey, setParamKey] = useState('')
  const [paramKeyTouched, setParamKeyTouched] = useState(false)
  const [unit, setUnit] = useState('')

  const refresh = useCallback(async (): Promise<void> => {
    try {
      setMaps(await livelinkService.listTopicMaps(deviceId))
    } catch {
      setMaps([])
    }
  }, [deviceId])

  useEffect(() => {
    void refresh()
  }, [refresh])

  // Prefill the parameter key from the topic's last segment until the user
  // edits it themselves.
  useEffect(() => {
    if (!paramKeyTouched) setParamKey(paramKeyFromTopic(topic))
  }, [topic, paramKeyTouched])

  const addMapping = async (): Promise<void> => {
    setError(null)
    // Mapped topics are EXACT. Rejecting here as well as server-side keeps the
    // reason next to the field the user just typed in.
    if (topic.includes('+') || topic.includes('#')) {
      setError(t('integrations.mqttErrorsTopicMustBeExact'))
      return
    }
    setBusy(true)
    try {
      await livelinkService.createTopicMap({
        device_id: deviceId,
        topic,
        param_key: paramKey,
        unit: unit || null,
      })
      setTopic('')
      setParamKeyTouched(false)
      setUnit('')
      await refresh()
      onMappingsChanged()
    } catch (err) {
      setError(getActionErrorMessage(err, t('integrations.mappingAction')))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (id: number): Promise<void> => {
    setError(null)
    try {
      await livelinkService.deleteTopicMap(id)
      await refresh()
      onMappingsChanged()
    } catch (err) {
      setError(getActionErrorMessage(err, t('integrations.mappingAction')))
    }
  }

  const topicId = `${idBase}-topic`
  const keyId = `${idBase}-key`
  const unitId = `${idBase}-unit`

  return (
    <section className="space-y-3">
      {error ? (
        <p className="text-xs text-danger" role="alert">
          {error}
        </p>
      ) : null}
      <ul className="space-y-1">
        {maps.map((m) => (
          <li key={m.id} className="flex items-center justify-between gap-2 text-xs">
            <span className="truncate font-mono text-text-mute">{m.topic}</span>
            <span className="font-mono text-text">{m.param_key}</span>
            <Button
              size="sm"
              variant="ghost"
              icon={Trash2}
              aria-label={t('integrations.mqttRemoveMappingFor', { topic: m.topic, key: m.param_key })}
              onClick={() => void remove(m.id)}
            />
          </li>
        ))}
      </ul>
      <div className="grid gap-x-3 sm:grid-cols-3">
        <Field id={topicId} label={t('integrations.mqttMapTopic')}>
          <Input id={topicId} mono value={topic} onChange={(e) => setTopic(e.target.value)} />
        </Field>
        <Field id={keyId} label={t('integrations.mqttParamKey')}>
          <Input
            id={keyId}
            mono
            value={paramKey}
            onChange={(e) => {
              setParamKeyTouched(true)
              setParamKey(e.target.value)
            }}
          />
        </Field>
        <Field id={unitId} label={t('integrations.mqttUnit')}>
          <Input id={unitId} value={unit} onChange={(e) => setUnit(e.target.value)} />
        </Field>
      </div>
      <Button size="sm" variant="secondary" loading={busy} disabled={busy || !topic} onClick={() => void addMapping()}>
        {t('integrations.mqttAddMapping')}
      </Button>
    </section>
  )
}
