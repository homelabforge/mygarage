import { useCallback, useEffect, useId, useState } from 'react'
import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import {
  AlertCircle,
  CheckCircle,
  Copy,
  Cpu,
  ExternalLink,
  Eye,
  EyeOff,
  Link2,
  Radio,
  RefreshCw,
  Settings,
} from 'lucide-react'

import NoMovementSignalNotice from '@/components/livelink/NoMovementSignalNotice'
import { Button, Drawer, Field, Input, Toggle } from '@/components/ui'
import { livelinkService } from '@/services/livelinkService'
import { vehicleService } from '@/services/vehicleService'
import type {
  DeviceFirmwareStatus,
  FirmwareInfo,
  IntegrationTab,
  LiveLinkDevice,
  LiveLinkSettings,
  MQTTSettings,
  MQTTStatus,
} from '@/types/livelink'
import type { Vehicle } from '@/types/vehicle'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'
import DeviceTable from './DeviceTable'

/**
 * WiCAN's settings, and nothing else: its HTTPS ingestion URL and token, the
 * MQTT topic prefix its dongles publish under, its devices, and its firmware.
 *
 * Moved from LiveLinkSettingsModal. Two things are new:
 *
 * - The topic prefix came from the modal's broker section. It is WiCAN's
 *   subscription prefix (livelink_sources/wican.py builds its topics from it),
 *   and the broker does not apply it until the subscriber restarts, so saving
 *   it here restarts a running subscriber. Without that, a changed prefix
 *   would silently do nothing until someone found the Restart button in
 *   another drawer.
 * - Every device or firmware mutation reloads BOTH the device list and the
 *   firmware status. A row derives its skip badge from the firmware status;
 *   the modal got that refresh for free by reloading everything.
 */

interface Props {
  open: boolean
  tab: IntegrationTab | null
  onClose: () => void
  onChanged: () => void
}

export default function WicanSettingsDrawer({ open, tab, onClose, onChanged }: Props): ReactElement {
  const { t } = useTranslation('forms')
  const idBase = useId()

  const [settings, setSettings] = useState<LiveLinkSettings | null>(null)
  const [devices, setDevices] = useState<LiveLinkDevice[] | null>(null)
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [firmware, setFirmware] = useState<FirmwareInfo | null>(null)
  const [deviceFirmware, setDeviceFirmware] = useState<DeviceFirmwareStatus[]>([])
  const [mqttSettings, setMqttSettings] = useState<MQTTSettings | null>(null)
  const [mqttStatus, setMqttStatus] = useState<MQTTStatus | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)

  const [newToken, setNewToken] = useState<string | null>(null)
  const [showToken, setShowToken] = useState(false)
  const [generatingToken, setGeneratingToken] = useState(false)
  const [prefix, setPrefix] = useState('')
  const [savingPrefix, setSavingPrefix] = useState(false)
  const [checkingFirmware, setCheckingFirmware] = useState(false)
  const [savingSetting, setSavingSetting] = useState(false)

  const reloadDevicesAndFirmware = useCallback(async (): Promise<void> => {
    const [loadedDevices, loadedFirmware] = await Promise.allSettled([
      livelinkService.getDevices(),
      livelinkService.getDeviceFirmwareStatus(),
    ])
    if (loadedDevices.status === 'fulfilled') {
      setDevices(loadedDevices.value.devices.filter((d) => d.kind === 'wican'))
    }
    if (loadedFirmware.status === 'fulfilled') setDeviceFirmware(loadedFirmware.value)
  }, [])

  const load = useCallback(async (): Promise<void> => {
    setLoadFailed(false)
    // The core three must load; firmware and broker details are optional, and
    // a failure there must not blank the device list.
    try {
      const [loadedSettings, loadedDevices, loadedVehicles] = await Promise.all([
        livelinkService.getSettings(),
        livelinkService.getDevices(),
        vehicleService.list(),
      ])
      setSettings(loadedSettings)
      setDevices(loadedDevices.devices.filter((d) => d.kind === 'wican'))
      setVehicles(loadedVehicles.vehicles)
    } catch {
      setLoadFailed(true)
      return
    }
    const [fw, dfw, ms, st] = await Promise.allSettled([
      livelinkService.getFirmwareLatest(),
      livelinkService.getDeviceFirmwareStatus(),
      livelinkService.getMQTTSettings(),
      livelinkService.getMQTTStatus(),
    ])
    setFirmware(fw.status === 'fulfilled' ? fw.value : null)
    setDeviceFirmware(dfw.status === 'fulfilled' ? dfw.value : [])
    if (ms.status === 'fulfilled') {
      setMqttSettings(ms.value)
      setPrefix(ms.value.topic_prefix)
    }
    setMqttStatus(st.status === 'fulfilled' ? st.value : null)
  }, [])

  useEffect(() => {
    if (!open) return
    // A token is shown once. Reopening must not show the last one again.
    setNewToken(null)
    setShowToken(false)
    void load()
  }, [open, load])

  const copyToClipboard = async (text: string, label: string): Promise<void> => {
    try {
      await navigator.clipboard.writeText(text)
      toast.success(t('modal.livelink.copiedToClipboard', { label }))
    } catch {
      toast.error(t('modal.failedToCopy'))
    }
  }

  const regenerateToken = async (): Promise<void> => {
    if (!confirm(t('modal.livelink.confirmRegenerateToken'))) return
    setGeneratingToken(true)
    try {
      const response = await livelinkService.regenerateGlobalToken()
      setNewToken(response.token)
      setShowToken(true)
      toast.success(t('modal.newTokenGenerated'))
      setSettings(await livelinkService.getSettings())
    } catch {
      toast.error(t('modal.failedToGenerateToken'))
    } finally {
      setGeneratingToken(false)
    }
  }

  const savePrefix = async (): Promise<void> => {
    const next = prefix.trim()
    if (!next || !mqttSettings) return
    // Switched off, the subscriber still runs in its "disabled" wait, and the
    // PUT stops it rather than restarting it.
    const restarts =
      mqttSettings.enabled && mqttStatus?.running === true && next !== mqttSettings.topic_prefix
    setSavingPrefix(true)
    try {
      // The PUT restarts a running subscriber itself when the prefix changes,
      // so there's nothing to restart from here; just re-read where it got to.
      setMqttSettings(await livelinkService.updateMQTTSettings({ topic_prefix: next }))
      if (restarts) {
        toast.success(t('modal.mqttRestarted'))
        // The save already worked, so a failed re-read just keeps the old status.
        void livelinkService
          .getMQTTStatus()
          .then(setMqttStatus)
          .catch(() => undefined)
      } else {
        toast.success(t('modal.mqttSettingsSaved'))
      }
      onChanged()
    } catch (error) {
      toast.error(getActionErrorMessage(error, t('settings:integrations.saveSettingsAction')))
    } finally {
      setSavingPrefix(false)
    }
  }

  const setFirmwareCheck = async (next: boolean): Promise<void> => {
    setSavingSetting(true)
    try {
      setSettings(await livelinkService.updateSettings({ firmware_check_enabled: next }))
      toast.success(t('modal.settingsSaved'))
    } catch {
      toast.error(t('modal.failedToSaveSettings'))
    } finally {
      setSavingSetting(false)
    }
  }

  const checkFirmware = async (): Promise<void> => {
    setCheckingFirmware(true)
    try {
      // In order. The status read compares each device against the cached
      // latest release that the check refreshes; run together (as the modal
      // did) it could compare against the release from before the check.
      setFirmware(await livelinkService.checkFirmwareUpdates())
      setDeviceFirmware(await livelinkService.getDeviceFirmwareStatus())
      toast.success(t('modal.firmwareCheckComplete'))
      onChanged()
    } catch {
      toast.error(t('modal.failedToCheckFirmware'))
    } finally {
      setCheckingFirmware(false)
    }
  }

  const deviceChanged = (): void => {
    void reloadDevicesAndFirmware()
    onChanged()
  }

  const prefixId = `${idBase}-prefix`

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('settings:integrations.sourceSettings', { source: tab?.label ?? '' })}
      icon={Radio}
      width="xl"
      closeLabel={t('common:close')}
    >
      {loadFailed ? (
        <div className="space-y-2">
          <p className="text-sm text-text-mute">{t('settings:integrations.settingsLoadError')}</p>
          <Button size="sm" variant="secondary" onClick={() => void load()}>
            {t('common:retry')}
          </Button>
        </div>
      ) : !settings || !devices ? (
        <div className="flex items-center justify-center py-12">
          <RefreshCw aria-hidden="true" className="w-8 h-8 text-(--accent-fg) animate-spin" />
        </div>
      ) : (
        <div className="space-y-6">
          <section className="bg-garage-bg rounded-lg border border-garage-border p-4">
            <div className="flex items-center gap-2 mb-4">
              <Link2 aria-hidden="true" className="w-5 h-5 text-(--accent-fg)" />
              <h3 className="text-lg font-semibold text-garage-text">{t('modal.connection')}</h3>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-garage-text mb-1">{t('modal.ingestionUrl')}</label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    readOnly
                    aria-label={t('modal.ingestionUrl')}
                    value={settings.ingestion_url ?? ''}
                    className="flex-1 px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text font-mono text-xs"
                  />
                  <button
                    onClick={() => void copyToClipboard(settings.ingestion_url ?? '', t('modal.livelink.urlLabel'))}
                    className="px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text hover:bg-garage-bg"
                    aria-label={t('modal.livelink.urlLabel')}
                  >
                    <Copy className="w-4 h-4" />
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-garage-text mb-1">{t('modal.globalApiToken')}</label>
                {newToken ? (
                  <div className="space-y-2">
                    <div className="flex gap-2">
                      <input
                        type={showToken ? 'text' : 'password'}
                        readOnly
                        aria-label={t('modal.globalApiToken')}
                        value={newToken}
                        className="flex-1 px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text font-mono text-xs"
                      />
                      <button
                        onClick={() => setShowToken(!showToken)}
                        className="px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text hover:bg-garage-bg"
                      >
                        {showToken ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                      <button
                        onClick={() => void copyToClipboard(newToken, t('modal.livelink.tokenLabel'))}
                        className="px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text hover:bg-garage-bg"
                      >
                        <Copy className="w-4 h-4" />
                      </button>
                    </div>
                    <div className="p-2 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
                      <p className="text-xs text-yellow-500">
                        <strong>{t('modal.livelink.saveTokenNowLabel')}</strong>{' '}
                        {t('modal.livelink.saveTokenNowDesc')}
                      </p>
                    </div>
                  </div>
                ) : (
                  <div className="flex items-center gap-4">
                    {settings.has_global_token ? (
                      <span className="flex items-center gap-2 text-sm text-green-500">
                        <CheckCircle className="w-4 h-4" />
                        {t('modal.livelink.tokenConfigured')}
                      </span>
                    ) : (
                      <span className="flex items-center gap-2 text-sm text-yellow-500">
                        <AlertCircle className="w-4 h-4" />
                        {t('modal.livelink.noTokenConfigured')}
                      </span>
                    )}
                    <Button
                      size="sm"
                      icon={RefreshCw}
                      loading={generatingToken}
                      disabled={generatingToken}
                      onClick={() => void regenerateToken()}
                    >
                      {settings.has_global_token ? t('modal.livelink.regenerate') : t('modal.livelink.generate')}
                    </Button>
                  </div>
                )}
              </div>

              {mqttSettings ? (
                <div>
                  <Field
                    id={prefixId}
                    label={t('settings:integrations.wicanTopicPrefix')}
                    hint={t('settings:integrations.wicanTopicPrefixHint')}
                  >
                    <Input id={prefixId} mono value={prefix} placeholder="wican" onChange={(e) => setPrefix(e.target.value)} />
                  </Field>
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={savingPrefix}
                    disabled={savingPrefix || !prefix.trim() || prefix.trim() === mqttSettings.topic_prefix}
                    onClick={() => void savePrefix()}
                  >
                    {t('modal.livelink.save')}
                  </Button>
                </div>
              ) : null}
            </div>
          </section>

          <section className="bg-garage-bg rounded-lg border border-garage-border p-4">
            <div className="flex items-center gap-2 mb-4">
              <Cpu aria-hidden="true" className="w-5 h-5 text-(--accent-fg)" />
              <h3 className="text-lg font-semibold text-garage-text">{t('modal.devices')}</h3>
            </div>
            <NoMovementSignalNotice devices={devices} />
            {devices.length > 0 ? (
              <DeviceTable
                devices={devices}
                vehicles={vehicles}
                deviceFirmware={deviceFirmware}
                mqttConnected={mqttStatus?.connection_status === 'connected'}
                onChanged={deviceChanged}
              />
            ) : (
              <div className="text-center py-6 text-garage-text-muted">
                <Cpu aria-hidden="true" className="w-10 h-10 mx-auto mb-2 opacity-50" />
                <p>{t('modal.noDevicesDiscovered')}</p>
              </div>
            )}
          </section>

          <section className="bg-garage-bg rounded-lg border border-garage-border p-4">
            <div className="flex items-center gap-2 mb-4">
              <Settings aria-hidden="true" className="w-5 h-5 text-(--accent-fg)" />
              <h3 className="text-lg font-semibold text-garage-text">{t('modal.livelink.firmwareUpdates')}</h3>
            </div>
            <div className="space-y-4">
              <div>
                <Toggle
                  label={t('modal.livelink.autoCheckUpdates')}
                  checked={settings.firmware_check_enabled}
                  onChange={(next) => void setFirmwareCheck(next)}
                  disabled={savingSetting}
                />
                <p className="text-xs text-garage-text-muted mt-1">{t('modal.livelink.autoCheckUpdatesDesc')}</p>
              </div>
              <div className="flex items-center gap-4">
                <div>
                  <p className="text-xs text-garage-text-muted">{t('modal.livelink.latestAvailable')}</p>
                  <p className="text-lg font-mono text-garage-text">
                    {firmware?.latest_tag ?? t('modal.livelink.unknown')}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="secondary"
                  icon={RefreshCw}
                  loading={checkingFirmware}
                  disabled={checkingFirmware}
                  onClick={() => void checkFirmware()}
                >
                  {t('modal.livelink.checkNow')}
                </Button>
                {firmware?.release_url ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    icon={ExternalLink}
                    onClick={() => window.open(firmware.release_url!, '_blank', 'noopener,noreferrer')}
                  >
                    {t('modal.livelink.viewRelease')}
                  </Button>
                ) : null}
              </div>
            </div>
          </section>
        </div>
      )}
    </Drawer>
  )
}
