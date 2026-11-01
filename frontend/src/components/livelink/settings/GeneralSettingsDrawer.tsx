import { useCallback, useEffect, useId, useState } from 'react'
import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Bell, Database, RefreshCw, Settings } from 'lucide-react'

import { Button, Drawer, Field, Input, Select, Toggle } from '@/components/ui'
import {
  SETTINGS_LIMITS,
  parseWholeInRange,
  type LimitedSetting,
} from '@/constants/livelink'
import { livelinkService } from '@/services/livelinkService'
import type { LiveLinkSettings, LiveLinkSettingsUpdate } from '@/types/livelink'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'

/**
 * LiveLink's global settings: the master switch, data retention, and the
 * alert and drive-session rules. Opened from the gear on the LiveLink card.
 *
 * These belong to no single source, which is why they are not in any source's
 * drawer (spec: "Retention and Alerts move behind the gear icon").
 *
 * Moved from LiveLinkSettingsModal with one behaviour change: the four numeric
 * fields hold a draft and save on Save. The modal PUT on every keystroke and
 * disabled the input while each PUT was in flight, so typing 15 sent 1 and
 * then 15, and a fast typist lost characters. Toggles and selects still save
 * immediately, being one event each.
 */

interface Props {
  open: boolean
  onClose: () => void
  /** The master switch flips every tab's status, so the card must refetch. */
  onChanged: () => void
}

const LIMITED: LimitedSetting[] = [
  'device_offline_timeout_minutes',
  'alert_cooldown_minutes',
  'session_grace_period_seconds',
  'session_gap_minutes',
]

type Draft = Record<LimitedSetting, string>

const draftFrom = (settings: LiveLinkSettings): Draft => ({
  device_offline_timeout_minutes: String(settings.device_offline_timeout_minutes),
  alert_cooldown_minutes: String(settings.alert_cooldown_minutes),
  session_grace_period_seconds: String(settings.session_grace_period_seconds),
  session_gap_minutes: String(settings.session_gap_minutes),
})

export default function GeneralSettingsDrawer({ open, onClose, onChanged }: Props): ReactElement {
  const { t } = useTranslation('forms')
  const idBase = useId()
  const [settings, setSettings] = useState<LiveLinkSettings | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)
  const [saving, setSaving] = useState(false)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [errors, setErrors] = useState<Partial<Record<LimitedSetting, string>>>({})

  const load = useCallback(async (): Promise<void> => {
    setLoadFailed(false)
    try {
      const loaded = await livelinkService.getSettings()
      setSettings(loaded)
      setDraft(draftFrom(loaded))
      setErrors({})
    } catch {
      setLoadFailed(true)
    }
  }, [])

  useEffect(() => {
    if (open) void load()
  }, [open, load])

  /** One immediate save, for a toggle or a select. */
  const save = async (update: LiveLinkSettingsUpdate): Promise<void> => {
    setSaving(true)
    try {
      const updated = await livelinkService.updateSettings(update)
      setSettings(updated)
      toast.success(t('modal.settingsSaved'))
      onChanged()
    } catch (error) {
      toast.error(getActionErrorMessage(error, t('settings:integrations.saveSettingsAction')))
    } finally {
      setSaving(false)
    }
  }

  const saveNumbers = async (): Promise<void> => {
    if (!settings || !draft) return
    const update: Partial<Record<LimitedSetting, number>> = {}
    const found: Partial<Record<LimitedSetting, string>> = {}
    for (const key of LIMITED) {
      if (draft[key] === String(settings[key])) continue
      const value = parseWholeInRange(draft[key], SETTINGS_LIMITS[key])
      if (value === null) {
        found[key] = t('settings:integrations.numberOutOfRange', SETTINGS_LIMITS[key])
      } else {
        update[key] = value
      }
    }
    setErrors(found)
    if (Object.keys(found).length > 0 || Object.keys(update).length === 0) return
    await save(update)
  }

  const dirty =
    settings !== null && draft !== null && LIMITED.some((key) => draft[key] !== String(settings[key]))

  // Takes translated strings, not keys: `validate-i18n-usage` checks only keys
  // written as literals at the call, so a key passed through a parameter would
  // go unchecked.
  const numberField = (key: LimitedSetting, label: string, unit: string, hint?: string): ReactElement => {
    const id = `${idBase}-${key}`
    return (
      <Field id={id} label={label} unit={unit} hint={hint} error={errors[key]}>
        <Input
          id={id}
          inputMode="numeric"
          value={draft?.[key] ?? ''}
          invalid={Boolean(errors[key])}
          onChange={(e) => setDraft((current) => (current ? { ...current, [key]: e.target.value } : current))}
        />
      </Field>
    )
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('settings:integrations.livelinkGeneral')}
      icon={Settings}
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
          <section className="bg-garage-bg rounded-lg border border-garage-border p-4">
            <Toggle
              label={t('modal.enableLiveLink')}
              checked={settings.enabled}
              onChange={(next) => void save({ enabled: next })}
              disabled={saving}
            />
            <p className="text-xs text-garage-text-muted mt-1">{t('settings:integrations.livelinkEnableHint')}</p>
          </section>

          <section className="bg-garage-bg rounded-lg border border-garage-border p-4">
            <div className="flex items-center gap-2 mb-4">
              <Database aria-hidden="true" className="w-5 h-5 text-(--accent-fg)" />
              <h3 className="text-lg font-semibold text-garage-text">{t('modal.dataRetention')}</h3>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label
                  htmlFor={`${idBase}-retention`}
                  className="block text-sm font-medium text-garage-text mb-1"
                >
                  {t('modal.rawTelemetryRetention')}
                </label>
                <Select
                  id={`${idBase}-retention`}
                  value={settings.telemetry_retention_days}
                  onChange={(e) => void save({ telemetry_retention_days: parseInt(e.target.value, 10) })}
                  disabled={saving}
                  options={[30, 60, 90, 180, 365].map((days) => ({
                    value: String(days),
                    label: t('modal.livelink.retentionDays', { count: days }),
                  }))}
                />
              </div>
              <div className="flex items-center">
                <div>
                  <Toggle
                    label={t('modal.livelink.dailyAggregation')}
                    checked={settings.daily_aggregation_enabled}
                    onChange={(next) => void save({ daily_aggregation_enabled: next })}
                    disabled={saving}
                  />
                  <p className="text-xs text-garage-text-muted mt-1">
                    {t('modal.livelink.dailyAggregationDesc')}
                  </p>
                </div>
              </div>
            </div>
          </section>

          <section className="bg-garage-bg rounded-lg border border-garage-border p-4">
            <div className="flex items-center gap-2 mb-4">
              <Bell aria-hidden="true" className="w-5 h-5 text-(--accent-fg)" />
              <h3 className="text-lg font-semibold text-garage-text">
                {t('modal.livelink.alertsNotifications')}
              </h3>
            </div>

            <div className="grid grid-cols-2 gap-x-4">
              {numberField(
                'device_offline_timeout_minutes',
                t('modal.livelink.deviceOfflineTimeout'),
                t('modal.livelink.minutes'),
              )}
              {numberField(
                'alert_cooldown_minutes',
                t('modal.livelink.alertCooldown'),
                t('modal.livelink.minutes'),
              )}
              {numberField(
                'session_grace_period_seconds',
                t('modal.livelink.sessionGracePeriod'),
                t('modal.livelink.seconds'),
                t('modal.livelink.sessionGracePeriodDesc'),
              )}
              {numberField(
                'session_gap_minutes',
                t('modal.livelink.sessionGap'),
                t('modal.livelink.minutes'),
                t('modal.livelink.sessionGapDesc'),
              )}
            </div>
            <Button size="sm" disabled={!dirty || saving} loading={saving} onClick={() => void saveNumbers()}>
              {t('modal.livelink.save')}
            </Button>

            <div className="mt-6">
              <label
                htmlFor={`${idBase}-boundary`}
                className="block text-sm font-medium text-garage-text mb-1"
              >
                {t('modal.livelink.boundaryMode')}
              </label>
              <Select
                id={`${idBase}-boundary`}
                value={settings.session_boundary_mode}
                onChange={(e) =>
                  void save({
                    // The API accepts only these two, and the Select offers only
                    // these two, but `e.target.value` is a bare string: the cast
                    // is where those two facts are tied together.
                    session_boundary_mode: e.target.value as 'movement' | 'contact',
                  })
                }
                disabled={saving}
                options={[
                  { value: 'movement', label: t('modal.livelink.boundaryModeMovement') },
                  { value: 'contact', label: t('modal.livelink.boundaryModeContact') },
                ]}
              />
              <p className="text-xs text-garage-text-muted mt-1">
                {settings.session_boundary_mode === 'contact'
                  ? t('modal.livelink.boundaryModeContactDesc')
                  : t('modal.livelink.boundaryModeMovementDesc')}
              </p>
            </div>

            <div className="mt-6 grid grid-cols-2 gap-3">
              <Toggle
                label={t('modal.livelink.notifyNewDevice')}
                checked={settings.notify_new_device}
                onChange={(next) => void save({ notify_new_device: next })}
                disabled={saving}
              />
              <Toggle
                label={t('modal.livelink.notifyDeviceOffline')}
                checked={settings.notify_device_offline}
                onChange={(next) => void save({ notify_device_offline: next })}
                disabled={saving}
              />
              <Toggle
                label={t('modal.livelink.notifyThresholdAlerts')}
                checked={settings.notify_threshold_alerts}
                onChange={(next) => void save({ notify_threshold_alerts: next })}
                disabled={saving}
              />
              <Toggle
                label={t('modal.livelink.notifyFirmwareUpdate')}
                checked={settings.notify_firmware_update}
                onChange={(next) => void save({ notify_firmware_update: next })}
                disabled={saving}
              />
            </div>
          </section>
        </div>
      )}
    </Drawer>
  )
}
