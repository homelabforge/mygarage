import { useCallback, useEffect, useId, useState } from 'react'
import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Play, RefreshCw, Server, Wifi } from 'lucide-react'

import { Button, Chip, Drawer, Field, Input, Toggle } from '@/components/ui'
import { parseWholeInRange } from '@/constants/livelink'
import { getActiveLocale } from '@/constants/i18n'
import { livelinkService } from '@/services/livelinkService'
import type { IntegrationTab, MQTTSettings, MQTTSettingsUpdate, MQTTStatus } from '@/types/livelink'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'
import { BROKER_STATUS_FALLBACK, BROKER_STATUS_LABEL } from '../integrationStatus'
import TopicDiscovery from './TopicDiscovery'

/**
 * The MQTT broker's settings: the connection, its live status, and a way to
 * see what the broker is publishing. Nothing about any one source.
 *
 * Moved from LiveLinkSettingsModal's "MQTT Subscription" section, minus the
 * topic prefix: that is the prefix WiCAN devices publish under
 * (livelink_sources/wican.py builds its subscriptions from it), so it lives in
 * the WiCAN drawer.
 *
 * The connection fields hold a draft and save on Save. The modal PUT on every
 * keystroke into host, port and username, and disabled the field mid-save.
 * Test and Restart act on the SAVED settings, so they wait until the draft is
 * saved: testing an unsaved host would test the old one and report on it.
 */

interface Props {
  open: boolean
  tab: IntegrationTab | null
  onClose: () => void
  /** The Mosquitto tab's dot follows the connection. */
  onChanged: () => void
}

interface Draft {
  broker_host: string
  broker_port: string
  username: string
  password: string
  use_tls: boolean
}

const PORT_LIMITS = { min: 1, max: 65535 }

const draftFrom = (settings: MQTTSettings): Draft => ({
  broker_host: settings.broker_host,
  broker_port: String(settings.broker_port),
  username: settings.username,
  password: '',
  use_tls: settings.use_tls,
})

const STATUS_TONE: Record<string, 'success' | 'warning' | 'danger' | 'muted'> = {
  connected: 'success',
  connecting: 'warning',
  error: 'danger',
}

export default function MosquittoSettingsDrawer({ open, tab, onClose, onChanged }: Props): ReactElement {
  const { t } = useTranslation('forms')
  const idBase = useId()
  const [settings, setSettings] = useState<MQTTSettings | null>(null)
  const [status, setStatus] = useState<MQTTStatus | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [portError, setPortError] = useState<string | undefined>(undefined)
  const [loadFailed, setLoadFailed] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [restarting, setRestarting] = useState(false)

  const load = useCallback(async (): Promise<void> => {
    setLoadFailed(false)
    try {
      const [loadedSettings, loadedStatus] = await Promise.all([
        livelinkService.getMQTTSettings(),
        livelinkService.getMQTTStatus(),
      ])
      setSettings(loadedSettings)
      setStatus(loadedStatus)
      setDraft(draftFrom(loadedSettings))
      setPortError(undefined)
    } catch {
      setLoadFailed(true)
    }
  }, [])

  useEffect(() => {
    if (open) void load()
  }, [open, load])

  const dirty =
    settings !== null &&
    draft !== null &&
    (draft.broker_host !== settings.broker_host ||
      draft.broker_port !== String(settings.broker_port) ||
      draft.username !== settings.username ||
      draft.use_tls !== settings.use_tls ||
      draft.password !== '')

  const set = <K extends keyof Draft>(key: K, value: Draft[K]): void =>
    setDraft((current) => (current ? { ...current, [key]: value } : current))

  const persist = async (update: MQTTSettingsUpdate): Promise<boolean> => {
    setSaving(true)
    try {
      const updated = await livelinkService.updateMQTTSettings(update)
      setSettings(updated)
      return true
    } catch (error) {
      toast.error(getActionErrorMessage(error, t('settings:integrations.saveSettingsAction')))
      return false
    } finally {
      setSaving(false)
    }
  }

  const saveConnection = async (): Promise<void> => {
    if (!settings || !draft) return
    const port = parseWholeInRange(draft.broker_port, PORT_LIMITS)
    if (port === null) {
      setPortError(t('settings:integrations.numberOutOfRange', PORT_LIMITS))
      return
    }
    setPortError(undefined)
    const update: MQTTSettingsUpdate = {}
    if (draft.broker_host !== settings.broker_host) update.broker_host = draft.broker_host.trim()
    if (port !== settings.broker_port) update.broker_port = port
    if (draft.username !== settings.username) update.username = draft.username
    if (draft.use_tls !== settings.use_tls) update.use_tls = draft.use_tls
    // Write-only: an empty field means "keep the stored password".
    if (draft.password) update.password = draft.password
    if (Object.keys(update).length === 0) return
    if (await persist(update)) {
      toast.success(t('modal.mqttSettingsSaved'))
      setDraft((current) => (current ? { ...current, password: '' } : current))
    }
  }

  const toggleEnabled = async (next: boolean): Promise<void> => {
    if (await persist({ enabled: next })) {
      toast.success(t('modal.mqttSettingsSaved'))
      onChanged()
    }
  }

  const test = async (): Promise<void> => {
    setTesting(true)
    try {
      const result = await livelinkService.testMQTTConnection()
      if (result.success) toast.success(result.message)
      else toast.error(result.message)
    } catch {
      toast.error(t('modal.failedToTestMqtt'))
    } finally {
      setTesting(false)
    }
  }

  const restart = async (): Promise<void> => {
    setRestarting(true)
    try {
      setStatus(await livelinkService.restartMQTTSubscriber())
      toast.success(t('modal.mqttRestarted'))
      onChanged()
    } catch {
      toast.error(t('modal.failedToRestartMqtt'))
    } finally {
      setRestarting(false)
    }
  }

  const id = (name: string): string => `${idBase}-${name}`

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('settings:integrations.sourceSettings', { source: tab?.label ?? '' })}
      icon={Server}
      width="md"
      closeLabel={t('common:close')}
    >
      {loadFailed ? (
        <div className="space-y-2">
          <p className="text-sm text-text-mute">{t('settings:integrations.settingsLoadError')}</p>
          <Button size="sm" variant="secondary" onClick={() => void load()}>
            {t('common:retry')}
          </Button>
        </div>
      ) : !settings || !draft ? (
        <div className="flex items-center justify-center py-12">
          <RefreshCw aria-hidden="true" className="w-8 h-8 text-(--accent-fg) animate-spin" />
        </div>
      ) : (
        <div className="space-y-6">
          {status ? (
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <Chip tone={STATUS_TONE[status.connection_status] ?? 'muted'}>
                {t((BROKER_STATUS_LABEL[status.connection_status] ?? BROKER_STATUS_FALLBACK).labelKey)}
              </Chip>
              <span className="text-text">
                {status.running ? t('modal.livelink.running') : t('modal.livelink.stopped')}
              </span>
              {status.messages_processed > 0 ? (
                <span className="text-text-mute">
                  {t('modal.livelink.messagesProcessed', {
                    count: status.messages_processed.toLocaleString(getActiveLocale()),
                  })}
                </span>
              ) : null}
            </div>
          ) : null}

          <div>
            <Toggle
              label={t('modal.enableMqttSubscription')}
              checked={settings.enabled}
              onChange={(next) => void toggleEnabled(next)}
              disabled={saving}
            />
            <p className="text-xs text-text-mute mt-1">{t('settings:integrations.brokerSubscriptionHint')}</p>
          </div>

          <section>
            <div className="grid grid-cols-2 gap-x-4">
              <Field id={id('host')} label={t('modal.brokerHost')}>
                <Input
                  id={id('host')}
                  mono
                  value={draft.broker_host}
                  placeholder="10.10.1.11"
                  onChange={(e) => set('broker_host', e.target.value)}
                />
              </Field>
              <Field id={id('port')} label={t('modal.port')} error={portError}>
                <Input
                  id={id('port')}
                  inputMode="numeric"
                  value={draft.broker_port}
                  invalid={Boolean(portError)}
                  onChange={(e) => set('broker_port', e.target.value)}
                />
              </Field>
              <Field id={id('username')} label={t('modal.username')}>
                <Input
                  id={id('username')}
                  value={draft.username}
                  placeholder={t('modal.livelink.optional')}
                  autoComplete="off"
                  onChange={(e) => set('username', e.target.value)}
                />
              </Field>
              <Field
                id={id('password')}
                label={t('modal.password')}
                hint={settings.has_password ? t('modal.livelink.passwordSet') : undefined}
              >
                <Input
                  id={id('password')}
                  type="password"
                  value={draft.password}
                  placeholder={settings.has_password ? '••••••••' : t('modal.livelink.optional')}
                  autoComplete="new-password"
                  onChange={(e) => set('password', e.target.value)}
                />
              </Field>
            </div>
            <Toggle
              label={t('modal.useTls')}
              checked={draft.use_tls}
              onChange={(next) => set('use_tls', next)}
            />
            <Button
              className="mt-4"
              size="sm"
              disabled={!dirty || saving}
              loading={saving}
              onClick={() => void saveConnection()}
            >
              {t('modal.livelink.save')}
            </Button>
          </section>

          <section className="space-y-2 border-t border-border pt-4">
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="secondary"
                icon={Wifi}
                loading={testing}
                disabled={dirty || testing || !settings.broker_host}
                onClick={() => void test()}
              >
                {t('modal.test')}
              </Button>
              <Button
                size="sm"
                icon={Play}
                loading={restarting}
                disabled={dirty || restarting}
                onClick={() => void restart()}
              >
                {status?.running ? t('modal.livelink.restart') : t('modal.livelink.start')}
              </Button>
            </div>
            {dirty ? (
              <p className="text-xs text-text-mute">{t('settings:integrations.brokerSaveFirst')}</p>
            ) : null}
          </section>

          <div className="border-t border-border pt-4">
            <TopicDiscovery />
          </div>
        </div>
      )}
    </Drawer>
  )
}
