import { useTranslation } from 'react-i18next'
import { useState, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { toast } from 'sonner'
import { getErrorMessage } from '@/utils/httpErrorHandler'
import {
  Copy,
  Eye,
  EyeOff,
  RefreshCw,
  Trash2,
  ExternalLink,
  AlertCircle,
  CheckCircle,
  Settings,
  Database,
  Bell,
  Cpu,
  Link2,
  Link2Off,
  Wifi,
  WifiOff,
  Key,
  Server,
  Play,
  Square,
  Battery,
  Download,
} from 'lucide-react'
import { livelinkService } from '@/services/livelinkService'
import NoMovementSignalNotice from '@/components/livelink/NoMovementSignalNotice'
import { vehicleService } from '@/services/vehicleService'
import { Select, Drawer, Toggle } from '@/components/ui'
import type {
  LiveLinkSettings,
  LiveLinkSettingsUpdate,
  LiveLinkDevice,
  LiveLinkDeviceListResponse,
  FirmwareInfo,
  DeviceFirmwareStatus,
  MQTTSettings,
  MQTTStatus,
  BackfillResultResponse,
} from '@/types/livelink'
import type { Vehicle } from '@/types/vehicle'
import { getActiveLocale } from '@/constants/i18n'

interface LiveLinkSettingsModalProps {
  isOpen: boolean
  onClose: () => void
}

export default function LiveLinkSettingsModal({ isOpen, onClose }: LiveLinkSettingsModalProps) {
  const { t } = useTranslation('forms')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [settings, setSettings] = useState<LiveLinkSettings | null>(null)
  const [devices, setDevices] = useState<LiveLinkDeviceListResponse | null>(null)
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [firmware, setFirmware] = useState<FirmwareInfo | null>(null)
  const [deviceFirmware, setDeviceFirmware] = useState<DeviceFirmwareStatus[]>([])

  // Token state
  const [showToken, setShowToken] = useState(false)
  const [newToken, setNewToken] = useState<string | null>(null)
  const [generatingToken, setGeneratingToken] = useState(false)

  // Firmware check state
  const [checkingFirmware, setCheckingFirmware] = useState(false)

  // Device token modals
  const [deviceTokenModal, setDeviceTokenModal] = useState<{
    deviceId: string
    token: string | null
  } | null>(null)

  // MQTT state
  const [mqttSettings, setMqttSettings] = useState<MQTTSettings | null>(null)
  const [mqttStatus, setMqttStatus] = useState<MQTTStatus | null>(null)
  const [mqttPassword, setMqttPassword] = useState('')
  const [savingMqtt, setSavingMqtt] = useState(false)
  const [testingMqtt, setTestingMqtt] = useState(false)
  const [restartingMqtt, setRestartingMqtt] = useState(false)

  // Load all data
  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [
        settingsData,
        devicesData,
        vehiclesData,
        firmwareData,
        deviceFirmwareData,
        mqttSettingsData,
        mqttStatusData,
      ] = await Promise.all([
        livelinkService.getSettings(),
        livelinkService.getDevices(),
        vehicleService.list(),
        livelinkService.getFirmwareLatest(),
        livelinkService.getDeviceFirmwareStatus(),
        livelinkService.getMQTTSettings(),
        livelinkService.getMQTTStatus(),
      ])
      setSettings(settingsData)
      setDevices(devicesData)
      setVehicles(vehiclesData.vehicles)
      setFirmware(firmwareData)
      setDeviceFirmware(deviceFirmwareData)
      setMqttSettings(mqttSettingsData)
      setMqttStatus(mqttStatusData)
    } catch (error) {
      console.error('Failed to load LiveLink settings:', error)
      toast.error(t('modal.failedToLoadLiveLink'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    if (isOpen) {
      loadData()
    }
  }, [isOpen, loadData])

  // Reset state when modal closes
  useEffect(() => {
    if (!isOpen) {
      setNewToken(null)
      setShowToken(false)
      setDeviceTokenModal(null)
      setMqttPassword('')
    }
  }, [isOpen])

  // Save settings
  const handleSaveSettings = async (update: LiveLinkSettingsUpdate) => {
    setSaving(true)
    try {
      const updated = await livelinkService.updateSettings(update)
      setSettings(updated)
      toast.success(t('modal.settingsSaved'))
    } catch (error) {
      console.error('Failed to save settings:', error)
      toast.error(t('modal.failedToSaveSettings'))
    } finally {
      setSaving(false)
    }
  }

  // Generate global token
  const handleRegenerateToken = async () => {
    if (!confirm(t('modal.livelink.confirmRegenerateToken'))) {
      return
    }

    setGeneratingToken(true)
    try {
      const response = await livelinkService.regenerateGlobalToken()
      setNewToken(response.token)
      setShowToken(true)
      toast.success(t('modal.newTokenGenerated'))
      const updated = await livelinkService.getSettings()
      setSettings(updated)
    } catch (error) {
      console.error('Failed to generate token:', error)
      toast.error(t('modal.failedToGenerateToken'))
    } finally {
      setGeneratingToken(false)
    }
  }

  // Copy to clipboard
  const copyToClipboard = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text)
      toast.success(t('modal.livelink.copiedToClipboard', { label }))
    } catch {
      toast.error(t('modal.failedToCopy'))
    }
  }

  // Check firmware updates
  const handleCheckFirmware = async () => {
    setCheckingFirmware(true)
    try {
      const [firmwareData, deviceFirmwareData] = await Promise.all([
        livelinkService.checkFirmwareUpdates(),
        livelinkService.getDeviceFirmwareStatus(),
      ])
      setFirmware(firmwareData)
      setDeviceFirmware(deviceFirmwareData)
      toast.success(t('modal.firmwareCheckComplete'))
    } catch (error) {
      console.error('Failed to check firmware:', error)
      toast.error(t('modal.failedToCheckFirmware'))
    } finally {
      setCheckingFirmware(false)
    }
  }

  // Save MQTT settings
  const handleSaveMqttSettings = async (
    update: Partial<{
      enabled: boolean
      broker_host: string
      broker_port: number
      username: string
      password: string
      topic_prefix: string
      use_tls: boolean
    }>
  ) => {
    setSavingMqtt(true)
    try {
      const updated = await livelinkService.updateMQTTSettings(update)
      setMqttSettings(updated)
      if (update.password) {
        setMqttPassword('')
      }
      toast.success(t('modal.mqttSettingsSaved'))
    } catch (error) {
      console.error('Failed to save MQTT settings:', error)
      toast.error(t('modal.failedToSaveMqtt'))
    } finally {
      setSavingMqtt(false)
    }
  }

  // Test MQTT connection
  const handleTestMqtt = async () => {
    setTestingMqtt(true)
    try {
      const result = await livelinkService.testMQTTConnection()
      if (result.success) {
        toast.success(result.message)
      } else {
        toast.error(result.message)
      }
    } catch (error) {
      console.error('Failed to test MQTT connection:', error)
      toast.error(t('modal.failedToTestMqtt'))
    } finally {
      setTestingMqtt(false)
    }
  }

  // Restart MQTT subscriber
  const handleRestartMqtt = async () => {
    setRestartingMqtt(true)
    try {
      const status = await livelinkService.restartMQTTSubscriber()
      setMqttStatus(status)
      toast.success(t('modal.mqttRestarted'))
    } catch (error) {
      console.error('Failed to restart MQTT subscriber:', error)
      toast.error(t('modal.failedToRestartMqtt'))
    } finally {
      setRestartingMqtt(false)
    }
  }

  // Update device
  const handleUpdateDevice = async (
    deviceId: string,
    update: { vin?: string | null; label?: string; enabled?: boolean; odometer_unit?: 'km' | 'mi' | 'auto' }
  ) => {
    try {
      await livelinkService.updateDevice(deviceId, update)
      toast.success(t('modal.deviceUpdated'))
      const updated = await livelinkService.getDevices()
      setDevices(updated)
    } catch (error) {
      console.error('Failed to update device:', error)
      // The server refuses an odometer-unit change once readings depend on it,
      // and says why and what to run. A generic failure toast would throw that
      // away and leave the setting looking merely broken.
      toast.error(getErrorMessage(error, t('modal.failedToUpdateDevice')))
    }
  }

  // Delete device
  const handleDeleteDevice = async (deviceId: string) => {
    if (!confirm(t('modal.livelink.confirmDeleteDevice'))) {
      return
    }

    try {
      await livelinkService.deleteDevice(deviceId)
      toast.success(t('modal.deviceDeleted'))
      const updated = await livelinkService.getDevices()
      setDevices(updated)
    } catch (error) {
      console.error('Failed to delete device:', error)
      toast.error(t('modal.failedToDeleteDevice'))
    }
  }

  // Generate device token
  const handleGenerateDeviceToken = async (deviceId: string) => {
    try {
      const response = await livelinkService.generateDeviceToken(deviceId)
      setDeviceTokenModal({ deviceId, token: response.token })
      const updated = await livelinkService.getDevices()
      setDevices(updated)
    } catch (error) {
      console.error('Failed to generate device token:', error)
      toast.error(t('modal.failedToGenerateDeviceToken'))
    }
  }

  // Revoke device token
  const handleRevokeDeviceToken = async (deviceId: string) => {
    if (!confirm(t('modal.livelink.confirmRevokeDeviceToken'))) {
      return
    }

    try {
      await livelinkService.revokeDeviceToken(deviceId)
      toast.success(t('modal.deviceTokenRevoked'))
      const updated = await livelinkService.getDevices()
      setDevices(updated)
    } catch (error) {
      console.error('Failed to revoke device token:', error)
      toast.error(t('modal.failedToRevokeDeviceToken'))
    }
  }

  const handleSendCommand = async (deviceId: string, command: string) => {
    try {
      const result = await livelinkService.sendDeviceCommand(deviceId, command)
      toast.success(result.message)
    } catch (error) {
      console.error('Failed to send command:', error)
      toast.error(t('modal.failedToSendCommand'))
    }
  }

  const handleSetSdConfig = async (
    deviceId: string,
    config: { device_address: string | null; sd_backfill_enabled: boolean }
  ): Promise<void> => {
    try {
      await livelinkService.setSdConfig(deviceId, config)
      toast.success(t('modal.livelink.sdConfigSaved'))
    } catch (error) {
      console.error('Failed to save SD config:', error)
      toast.error(t('modal.livelink.failedToSaveSdConfig'))
    }
  }

  const handleSdBackfill = async (deviceId: string): Promise<BackfillResultResponse | null> => {
    try {
      const result = await livelinkService.triggerSdBackfill(deviceId)
      const summary = t('modal.livelink.backfillSummary', {
        ingested: result.rows_ingested,
        skipped: result.rows_skipped,
      })
      if (result.errors && result.errors.length > 0) {
        toast.warning(`${summary} — ${result.errors[0]}`)
      } else {
        toast.success(summary)
      }
      return result
    } catch (error) {
      console.error('Failed to trigger SD backfill:', error)
      toast.error(t('modal.livelink.sdBackfillFailed'))
      return null
    }
  }

  if (!isOpen) return null

  return (
    <>
    <Drawer
      open={isOpen}
      onClose={onClose}
      title={t('modal.liveLinkSettings')}
      icon={Settings}
      width="xl"
      closeLabel={t('modal.livelink.close')}
      footer={
        <button
          onClick={onClose}
          className="px-4 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text hover:bg-garage-bg"
        >
          {t('modal.livelink.close')}
        </button>
      }
    >
        <p className="text-sm text-garage-text-muted mb-6">{t('modal.liveLinkDescription')}</p>
        <div className="space-y-6">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <RefreshCw className="w-8 h-8 text-primary animate-spin" />
            </div>
          ) : (
            <>
              {/* Section: Connection */}
              <section className="bg-garage-bg rounded-lg border border-garage-border p-4">
                <div className="flex items-center gap-2 mb-4">
                  <Link2 className="w-5 h-5 text-primary" />
                  <h3 className="text-lg font-semibold text-garage-text">{t('modal.connection')}</h3>
                </div>

                <div className="space-y-4">
                  {/* Enable Toggle */}
                  <div>
                    <Toggle
                      label={t('modal.enableLiveLink')}
                      checked={settings?.enabled ?? false}
                      onChange={(next) => handleSaveSettings({ enabled: next })}
                      disabled={saving}
                    />
                    <p className="text-xs text-garage-text-muted mt-1">{t('modal.acceptTelemetry')}</p>
                  </div>

                  {/* Ingestion URL */}
                  <div>
                    <label className="block text-sm font-medium text-garage-text mb-1">{t('modal.ingestionUrl')}</label>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        readOnly
                        value={settings?.ingestion_url ?? ''}
                        className="flex-1 px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text font-mono text-xs"
                      />
                      <button
                        onClick={() => copyToClipboard(settings?.ingestion_url ?? '', t('modal.livelink.urlLabel'))}
                        className="px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text hover:bg-garage-bg"
                      >
                        <Copy className="w-4 h-4" />
                      </button>
                    </div>
                  </div>

                  {/* Global Token */}
                  <div>
                    <label className="block text-sm font-medium text-garage-text mb-1">{t('modal.globalApiToken')}</label>
                    {newToken ? (
                      <div className="space-y-2">
                        <div className="flex gap-2">
                          <input
                            type={showToken ? 'text' : 'password'}
                            readOnly
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
                            onClick={() => copyToClipboard(newToken, t('modal.livelink.tokenLabel'))}
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
                        {settings?.has_global_token ? (
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
                        <button
                          onClick={handleRegenerateToken}
                          disabled={generatingToken}
                          className="flex items-center gap-2 btn btn-primary rounded-lg disabled:opacity-50"
                        >
                          <RefreshCw className={`w-4 h-4 ${generatingToken ? 'animate-spin' : ''}`} />
                          {settings?.has_global_token
                            ? t('modal.livelink.regenerate')
                            : t('modal.livelink.generate')}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </section>

              {/* Section: MQTT Settings */}
              <section className="bg-garage-bg rounded-lg border border-garage-border p-4">
                <div className="flex items-center gap-2 mb-4">
                  <Server className="w-5 h-5 text-primary" />
                  <h3 className="text-lg font-semibold text-garage-text">{t('modal.mqttSubscription')}</h3>
                  {mqttStatus && (
                    <span
                      className={`px-2 py-0.5 text-xs rounded-full ${
                        mqttStatus.connection_status === 'connected'
                          ? 'bg-green-500/20 text-green-500'
                          : mqttStatus.connection_status === 'connecting'
                            ? 'bg-yellow-500/20 text-yellow-500'
                            : mqttStatus.connection_status === 'error'
                              ? 'bg-red-500/20 text-red-500'
                              : 'bg-gray-500/20 text-gray-500'
                      }`}
                    >
                      {mqttStatus.connection_status}
                    </span>
                  )}
                </div>

                <div className="space-y-4">
                  {/* Enable Toggle */}
                  <div>
                    <Toggle
                      label={t('modal.enableMqttSubscription')}
                      checked={mqttSettings?.enabled ?? false}
                      onChange={(next) => handleSaveMqttSettings({ enabled: next })}
                      disabled={savingMqtt}
                    />
                    <p className="text-xs text-garage-text-muted mt-1">{t('modal.mqttDescription')}</p>
                  </div>

                  {/* Broker Settings */}
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-garage-text mb-1">{t('modal.brokerHost')}</label>
                      <input
                        type="text"
                        value={mqttSettings?.broker_host ?? ''}
                        onChange={(e) => handleSaveMqttSettings({ broker_host: e.target.value })}
                        placeholder="10.10.1.11"
                        disabled={savingMqtt}
                        className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text text-sm focus:ring-2 focus:ring-primary"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-garage-text mb-1">{t('modal.port')}</label>
                      <input
                        type="number"
                        value={mqttSettings?.broker_port ?? 1883}
                        onChange={(e) => handleSaveMqttSettings({ broker_port: parseInt(e.target.value) })}
                        min="1"
                        max="65535"
                        disabled={savingMqtt}
                        className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text text-sm focus:ring-2 focus:ring-primary"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-garage-text mb-1">{t('modal.username')}</label>
                      <input
                        type="text"
                        value={mqttSettings?.username ?? ''}
                        onChange={(e) => handleSaveMqttSettings({ username: e.target.value })}
                        placeholder={t('modal.livelink.optional')}
                        disabled={savingMqtt}
                        className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text text-sm focus:ring-2 focus:ring-primary"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-garage-text mb-1">
                        {t('modal.password')}{' '}
                        {mqttSettings?.has_password && (
                          <span className="text-green-500 text-xs">{t('modal.livelink.passwordSet')}</span>
                        )}
                      </label>
                      <div className="flex gap-2">
                        <input
                          type="password"
                          value={mqttPassword}
                          onChange={(e) => setMqttPassword(e.target.value)}
                          placeholder={mqttSettings?.has_password ? '••••••••' : t('modal.livelink.optional')}
                          disabled={savingMqtt}
                          className="flex-1 px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text text-sm focus:ring-2 focus:ring-primary"
                        />
                        {mqttPassword && (
                          <button
                            onClick={() => handleSaveMqttSettings({ password: mqttPassword })}
                            disabled={savingMqtt}
                            className="btn btn-primary rounded-lg disabled:opacity-50"
                          >
                            {t('modal.livelink.save')}
                          </button>
                        )}
                      </div>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-garage-text mb-1">{t('modal.topicPrefix')}</label>
                      <input
                        type="text"
                        value={mqttSettings?.topic_prefix ?? 'wican'}
                        onChange={(e) => handleSaveMqttSettings({ topic_prefix: e.target.value })}
                        placeholder="wican"
                        disabled={savingMqtt}
                        className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text text-sm focus:ring-2 focus:ring-primary"
                      />
                    </div>
                    <div className="flex items-center">
                      <Toggle
                        label={t('modal.useTls')}
                        checked={mqttSettings?.use_tls ?? false}
                        onChange={(next) => handleSaveMqttSettings({ use_tls: next })}
                        disabled={savingMqtt}
                      />
                    </div>
                  </div>

                  {/* Status and Actions */}
                  <div className="flex flex-wrap items-center gap-4 pt-3 border-t border-garage-border">
                    {mqttStatus && (
                      <div className="flex items-center gap-2 text-sm">
                        {mqttStatus.connection_status === 'connected' ? (
                          <CheckCircle className="w-4 h-4 text-green-500" />
                        ) : mqttStatus.connection_status === 'connecting' ? (
                          <RefreshCw className="w-4 h-4 text-yellow-500 animate-spin" />
                        ) : mqttStatus.connection_status === 'error' ? (
                          <AlertCircle className="w-4 h-4 text-red-500" />
                        ) : (
                          <Square className="w-4 h-4 text-gray-500" />
                        )}
                        <span className="text-garage-text">
                          {mqttStatus.running ? t('modal.livelink.running') : t('modal.livelink.stopped')}
                        </span>
                        {mqttStatus.messages_processed > 0 && (
                          <span className="text-garage-text-muted">
                            {t('modal.livelink.messagesProcessed', {
                              count: mqttStatus.messages_processed.toLocaleString(getActiveLocale()),
                            })}
                          </span>
                        )}
                      </div>
                    )}

                    <div className="flex gap-2 ml-auto">
                      <button
                        onClick={handleTestMqtt}
                        disabled={testingMqtt || !mqttSettings?.broker_host}
                        className="flex items-center gap-2 px-4 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text hover:bg-garage-bg disabled:opacity-50"
                      >
                        {testingMqtt ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Wifi className="w-4 h-4" />}
                        {t('modal.test')}
                      </button>
                      <button
                        onClick={handleRestartMqtt}
                        disabled={restartingMqtt}
                        className="flex items-center gap-2 btn btn-primary rounded-lg disabled:opacity-50"
                      >
                        {restartingMqtt ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                        {mqttStatus?.running ? t('modal.livelink.restart') : t('modal.livelink.start')}
                      </button>
                    </div>
                  </div>
                </div>
              </section>

              {/* Section: Devices */}
              <section className="bg-garage-bg rounded-lg border border-garage-border p-4">
                <div className="flex items-center gap-2 mb-4">
                  <Cpu className="w-5 h-5 text-primary" />
                  <h3 className="text-lg font-semibold text-garage-text">{t('modal.devices')}</h3>
                  <span className="text-sm text-garage-text-muted">
                    {t('modal.livelink.deviceCounts', {
                      total: devices?.total ?? 0,
                      online: devices?.online_count ?? 0,
                    })}
                  </span>
                </div>

                {devices && devices.devices.length > 0 ? (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-garage-border">
                          <th className="text-left py-2 px-3 text-garage-text">{t('modal.livelink.device')}</th>
                          <th className="text-left py-2 px-3 text-garage-text">{t('modal.livelink.status')}</th>
                          <th className="text-left py-2 px-3 text-garage-text">{t('modal.vehicle')}</th>
                          <th className="text-left py-2 px-3 text-garage-text">{t('modal.livelink.firmware')}</th>
                          <th className="text-right py-2 px-3 text-garage-text">{t('modal.livelink.actions')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {devices.devices.map((device) => (
                          <DeviceRow
                            key={device.device_id}
                            device={device}
                            vehicles={vehicles}
                            deviceFirmware={deviceFirmware.find((d) => d.device_id === device.device_id)}
                            mqttConnected={mqttStatus?.connection_status === 'connected'}
                            onUpdate={handleUpdateDevice}
                            onDelete={handleDeleteDevice}
                            onGenerateToken={handleGenerateDeviceToken}
                            onRevokeToken={handleRevokeDeviceToken}
                            onSendCommand={handleSendCommand}
                            onSetSdConfig={handleSetSdConfig}
                            onSdBackfill={handleSdBackfill}
                          />
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="text-center py-6 text-garage-text-muted">
                    <Cpu className="w-10 h-10 mx-auto mb-2 opacity-50" />
                    <p>{t('modal.noDevicesDiscovered')}</p>
                  </div>
                )}
              </section>

              {/* Section: Data Retention */}
              <section className="bg-garage-bg rounded-lg border border-garage-border p-4">
                <div className="flex items-center gap-2 mb-4">
                  <Database className="w-5 h-5 text-primary" />
                  <h3 className="text-lg font-semibold text-garage-text">{t('modal.dataRetention')}</h3>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-garage-text mb-1">{t('modal.rawTelemetryRetention')}</label>
                    <Select
                      value={settings?.telemetry_retention_days ?? 90}
                      onChange={(e) => handleSaveSettings({ telemetry_retention_days: parseInt(e.target.value) })}
                      disabled={saving}
                      options={[
                        { value: '30', label: t('modal.livelink.retentionDays', { count: 30 }) },
                        { value: '60', label: t('modal.livelink.retentionDays', { count: 60 }) },
                        { value: '90', label: t('modal.livelink.retentionDays', { count: 90 }) },
                        { value: '180', label: t('modal.livelink.retentionDays', { count: 180 }) },
                        { value: '365', label: t('modal.livelink.retentionDays', { count: 365 }) },
                      ]}
                    />
                  </div>
                  <div className="flex items-center">
                    <div>
                      <Toggle
                        label={t('modal.livelink.dailyAggregation')}
                        checked={settings?.daily_aggregation_enabled ?? true}
                        onChange={(next) => handleSaveSettings({ daily_aggregation_enabled: next })}
                        disabled={saving}
                      />
                      <p className="text-xs text-garage-text-muted mt-1">
                        {t('modal.livelink.dailyAggregationDesc')}
                      </p>
                    </div>
                  </div>
                </div>
              </section>

              <NoMovementSignalNotice devices={devices?.devices ?? []} />

              {/* Section: Alerts & Notifications */}
              <section className="bg-garage-bg rounded-lg border border-garage-border p-4">
                <div className="flex items-center gap-2 mb-4">
                  <Bell className="w-5 h-5 text-primary" />
                  <h3 className="text-lg font-semibold text-garage-text">{t('modal.livelink.alertsNotifications')}</h3>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-garage-text mb-1">
                      {t('modal.livelink.deviceOfflineTimeout')}
                    </label>
                    <div className="flex items-center gap-2">
                      <input
                        type="number"
                        min="5"
                        max="60"
                        value={settings?.device_offline_timeout_minutes ?? 15}
                        onChange={(e) =>
                          handleSaveSettings({ device_offline_timeout_minutes: parseInt(e.target.value) })
                        }
                        disabled={saving}
                        className="w-20 px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text text-sm focus:ring-2 focus:ring-primary"
                      />
                      <span className="text-garage-text-muted text-sm">{t('modal.livelink.minutes')}</span>
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-garage-text mb-1">
                      {t('modal.livelink.alertCooldown')}
                    </label>
                    <div className="flex items-center gap-2">
                      <input
                        type="number"
                        min="5"
                        max="120"
                        value={settings?.alert_cooldown_minutes ?? 30}
                        onChange={(e) => handleSaveSettings({ alert_cooldown_minutes: parseInt(e.target.value) })}
                        disabled={saving}
                        className="w-20 px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text text-sm focus:ring-2 focus:ring-primary"
                      />
                      <span className="text-garage-text-muted text-sm">{t('modal.livelink.minutes')}</span>
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-garage-text mb-1">
                      {t('modal.livelink.sessionGracePeriod')}
                    </label>
                    <div className="flex items-center gap-2">
                      <input
                        type="number"
                        min="0"
                        max="300"
                        value={settings?.session_grace_period_seconds ?? 60}
                        onChange={(e) =>
                          handleSaveSettings({ session_grace_period_seconds: parseInt(e.target.value) })
                        }
                        disabled={saving}
                        className="w-20 px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text text-sm focus:ring-2 focus:ring-primary"
                      />
                      <span className="text-garage-text-muted text-sm">{t('modal.livelink.seconds')}</span>
                    </div>
                    <p className="text-xs text-garage-text-muted mt-1">
                      {t('modal.livelink.sessionGracePeriodDesc')}
                    </p>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-garage-text mb-1">
                      {t('modal.livelink.sessionGap')}
                    </label>
                    <div className="flex items-center gap-2">
                      <input
                        type="number"
                        min="1"
                        max="240"
                        value={settings?.session_gap_minutes ?? 15}
                        onChange={(e) => handleSaveSettings({ session_gap_minutes: parseInt(e.target.value) })}
                        disabled={saving}
                        className="w-20 px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text text-sm focus:ring-2 focus:ring-primary"
                      />
                      <span className="text-garage-text-muted text-sm">{t('modal.livelink.minutes')}</span>
                    </div>
                    <p className="text-xs text-garage-text-muted mt-1">
                      {t('modal.livelink.sessionGapDesc')}
                    </p>
                  </div>
                  <div className="col-span-2">
                    <label className="block text-sm font-medium text-garage-text mb-1">
                      {t('modal.livelink.boundaryMode')}
                    </label>
                    <Select
                      value={settings?.session_boundary_mode ?? 'movement'}
                      onChange={(e) =>
                        handleSaveSettings({
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
                      {settings?.session_boundary_mode === 'contact'
                        ? t('modal.livelink.boundaryModeContactDesc')
                        : t('modal.livelink.boundaryModeMovementDesc')}
                    </p>
                  </div>
                  <div className="col-span-2 grid grid-cols-2 gap-3">
                    <Toggle
                      label={t('modal.livelink.notifyNewDevice')}
                      checked={settings?.notify_new_device ?? true}
                      onChange={(next) => handleSaveSettings({ notify_new_device: next })}
                      disabled={saving}
                    />
                    <Toggle
                      label={t('modal.livelink.notifyDeviceOffline')}
                      checked={settings?.notify_device_offline ?? true}
                      onChange={(next) => handleSaveSettings({ notify_device_offline: next })}
                      disabled={saving}
                    />
                    <Toggle
                      label={t('modal.livelink.notifyThresholdAlerts')}
                      checked={settings?.notify_threshold_alerts ?? true}
                      onChange={(next) => handleSaveSettings({ notify_threshold_alerts: next })}
                      disabled={saving}
                    />
                    <Toggle
                      label={t('modal.livelink.notifyFirmwareUpdate')}
                      checked={settings?.notify_firmware_update ?? true}
                      onChange={(next) => handleSaveSettings({ notify_firmware_update: next })}
                      disabled={saving}
                    />
                  </div>
                </div>
              </section>

              {/* Section: Firmware */}
              <section className="bg-garage-bg rounded-lg border border-garage-border p-4">
                <div className="flex items-center gap-2 mb-4">
                  <Settings className="w-5 h-5 text-primary" />
                  <h3 className="text-lg font-semibold text-garage-text">{t('modal.livelink.firmwareUpdates')}</h3>
                </div>

                <div className="space-y-4">
                  <div>
                    <Toggle
                      label={t('modal.livelink.autoCheckUpdates')}
                      checked={settings?.firmware_check_enabled ?? true}
                      onChange={(next) => handleSaveSettings({ firmware_check_enabled: next })}
                      disabled={saving}
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
                    <button
                      onClick={handleCheckFirmware}
                      disabled={checkingFirmware}
                      className="flex items-center gap-2 px-4 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text hover:bg-garage-bg disabled:opacity-50"
                    >
                      <RefreshCw className={`w-4 h-4 ${checkingFirmware ? 'animate-spin' : ''}`} />
                      {t('modal.livelink.checkNow')}
                    </button>
                    {firmware?.release_url && (
                      <button
                        onClick={() => window.open(firmware.release_url!, '_blank')}
                        className="flex items-center gap-2 px-4 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text hover:bg-garage-bg"
                      >
                        <ExternalLink className="w-4 h-4" />
                        {t('modal.livelink.viewRelease')}
                      </button>
                    )}
                  </div>
                </div>
              </section>
            </>
          )}
        </div>
    </Drawer>

    {/* Device Token dialog — portalled to <body> so it escapes the drawer's
        root-level inert and the panel's transform, staying a centred modal on
        top of the drawer. */}
    {deviceTokenModal && createPortal(
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-drawer-nested">
          <div className="bg-garage-surface rounded-lg border border-garage-border p-6 max-w-lg w-full mx-4">
            <h3 className="text-lg font-semibold text-garage-text mb-4">
              {t('modal.livelink.deviceTokenGenerated')}
            </h3>
            <div className="space-y-4">
              <div>
                <label className="block text-sm text-garage-text-muted mb-2">
                  {t('modal.livelink.tokenForDevice', { deviceId: deviceTokenModal.deviceId })}
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    readOnly
                    value={deviceTokenModal.token ?? ''}
                    className="flex-1 px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text font-mono text-sm"
                  />
                  <button
                    onClick={() => copyToClipboard(deviceTokenModal.token ?? '', t('modal.livelink.tokenLabel'))}
                    className="px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text hover:bg-garage-surface"
                  >
                    <Copy className="w-4 h-4" />
                  </button>
                </div>
              </div>
              <div className="p-3 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
                <p className="text-sm text-yellow-500">
                  <strong>{t('modal.livelink.saveTokenNowLabel')}</strong>{' '}
                  {t('modal.livelink.saveTokenNowDesc')}
                </p>
              </div>
              <div className="flex justify-end">
                <button
                  onClick={() => setDeviceTokenModal(null)}
                  className="btn btn-primary rounded-lg"
                >
                  {t('modal.livelink.done')}
                </button>
              </div>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </>
  )
}

// Device row component
function DeviceRow({
  device,
  vehicles,
  deviceFirmware,
  mqttConnected,
  onUpdate,
  onDelete,
  onGenerateToken,
  onRevokeToken,
  onSendCommand,
  onSetSdConfig,
  onSdBackfill,
}: {
  device: LiveLinkDevice
  vehicles: Vehicle[]
  deviceFirmware?: DeviceFirmwareStatus
  mqttConnected?: boolean
  onUpdate: (deviceId: string, update: { vin?: string | null; label?: string; enabled?: boolean; odometer_unit?: 'km' | 'mi' | 'auto' }) => void
  onDelete: (deviceId: string) => void
  onGenerateToken: (deviceId: string) => void
  onRevokeToken: (deviceId: string) => void
  onSendCommand: (deviceId: string, command: string) => void
  onSetSdConfig: (
    deviceId: string,
    config: { device_address: string | null; sd_backfill_enabled: boolean }
  ) => Promise<void>
  onSdBackfill: (deviceId: string) => Promise<BackfillResultResponse | null>
}) {
  const { t } = useTranslation('forms')
  const [editing, setEditing] = useState(false)
  const [label, setLabel] = useState(device.label ?? '')
  const [showSdConfig, setShowSdConfig] = useState(false)
  const [sdAddress, setSdAddress] = useState(device.device_address ?? '')
  const [sdEnabled, setSdEnabled] = useState(device.sd_backfill_enabled ?? false)
  const [odometerUnit, setOdometerUnit] = useState<'km' | 'mi' | 'auto'>(
    (device.odometer_unit as 'km' | 'mi' | null) ?? 'auto'
  )
  const [savingSd, setSavingSd] = useState(false)
  const [backfilling, setBackfilling] = useState(false)

  const handleSaveLabel = () => {
    onUpdate(device.device_id, { label: label || undefined })
    setEditing(false)
  }

  const handleSaveSdConfig = async (): Promise<void> => {
    setSavingSd(true)
    await onSetSdConfig(device.device_id, {
      device_address: sdAddress.trim() || null,
      sd_backfill_enabled: sdEnabled,
    })
    setSavingSd(false)
  }

  const handleBackfill = async (): Promise<void> => {
    setBackfilling(true)
    await onSdBackfill(device.device_id)
    setBackfilling(false)
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'online':
        return 'text-green-500'
      case 'offline':
        return 'text-red-500'
      default:
        return 'text-gray-500'
    }
  }

  return (
    <>
    <tr className="border-b border-garage-border hover:bg-garage-surface/50">
      <td className="py-2 px-3">
        <div>
          {editing ? (
            <div className="flex gap-2">
              <input
                type="text"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder={t('modal.livelink.labelPlaceholder')}
                className="px-2 py-1 bg-garage-surface border border-garage-border rounded text-xs text-garage-text w-24"
              />
              <button onClick={handleSaveLabel} className="text-green-500 hover:text-green-400">
                <CheckCircle className="w-4 h-4" />
              </button>
            </div>
          ) : (
            <button onClick={() => setEditing(true)} className="text-garage-text hover:text-primary text-sm">
              {device.label || device.device_id.substring(0, 8) + '...'}
            </button>
          )}
          <p className="text-xs text-garage-text-muted font-mono">{device.device_id}</p>
        </div>
      </td>
      <td className="py-2 px-3">
        <div className="flex flex-col gap-0.5">
          <span className={`flex items-center gap-1 text-xs ${getStatusColor(device.device_status)}`}>
            {device.device_status === 'online' ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
            {device.device_status}
          </span>
          <span className={`flex items-center gap-1 text-xs ${getStatusColor(device.ecu_status)}`}>
            {device.ecu_status === 'online' ? <Link2 className="w-3 h-3" /> : <Link2Off className="w-3 h-3" />}
            {t('modal.livelink.ecuLabel')} {device.ecu_status}
          </span>
        </div>
      </td>
      <td className="py-2 px-3">
        <Select
          value={device.vin ?? ''}
          onChange={(e) => onUpdate(device.device_id, { vin: e.target.value || null })}
          placeholder={t('modal.livelink.unlinked')}
          options={vehicles.map((v) => ({
            value: v.vin,
            label: v.nickname || `${v.year} ${v.make} ${v.model}`,
          }))}
        />
      </td>
      <td className="py-2 px-3">
        <span className="text-xs text-garage-text">{device.fw_version ?? t('modal.livelink.unknown')}</span>
        {deviceFirmware?.update_available && (
          <span className="ml-1 px-1 py-0.5 bg-yellow-500/20 text-yellow-500 text-xs rounded">
            {t('modal.livelink.updateBadge')}
          </span>
        )}
      </td>
      <td className="py-2 px-3 text-right">
        <div className="flex items-center justify-end gap-1">
          {mqttConnected && device.device_status === 'online' && (
            <button
              onClick={() => onSendCommand(device.device_id, 'get_vbatt')}
              className="p-1 text-garage-text-muted hover:text-green-500"
              title={t('modal.livelink.checkBatteryVoltage')}
            >
              <Battery className="w-4 h-4" />
            </button>
          )}
          {device.sta_ip && (
            <a
              href={`http://${device.sta_ip}`}
              target="_blank"
              rel="noopener noreferrer"
              className="p-1 text-garage-text-muted hover:text-primary"
              title={t('modal.livelink.openDeviceUi')}
            >
              <ExternalLink className="w-4 h-4" />
            </a>
          )}
          {device.has_device_token ? (
            <button
              onClick={() => onRevokeToken(device.device_id)}
              className="p-1 text-yellow-500 hover:text-yellow-400"
              title={t('modal.livelink.revokeDeviceToken')}
            >
              <Key className="w-4 h-4" />
            </button>
          ) : (
            <button
              onClick={() => onGenerateToken(device.device_id)}
              className="p-1 text-garage-text-muted hover:text-primary"
              title={t('modal.livelink.generateDeviceToken')}
            >
              <Key className="w-4 h-4" />
            </button>
          )}
          <button
            onClick={() => setShowSdConfig(!showSdConfig)}
            className={`p-1 ${showSdConfig ? 'text-primary' : 'text-garage-text-muted hover:text-primary'}`}
            title={t('modal.livelink.sdBackfillConfig')}
          >
            <Download className="w-4 h-4" />
          </button>
          <button
            onClick={() => onDelete(device.device_id)}
            className="p-1 text-garage-text-muted hover:text-red-500"
            title={t('modal.livelink.deleteDevice')}
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </td>
    </tr>
    {showSdConfig && (
      <tr className="bg-garage-surface/30 border-b border-garage-border">
        <td colSpan={5} className="px-4 py-3">
          <div className="flex flex-wrap items-end gap-4">
            <div>
              <label className="block text-xs font-medium text-garage-text mb-1">
                {t('modal.livelink.deviceAddress')}
              </label>
              <input
                type="text"
                value={sdAddress}
                onChange={(e) => setSdAddress(e.target.value)}
                placeholder="192.168.1.x"
                className="px-2 py-1 bg-garage-bg border border-garage-border rounded text-xs text-garage-text w-40 focus:ring-1 focus:ring-primary"
              />
            </div>
            <div className="mb-1">
              <Toggle
                label={t('modal.livelink.autoSdBackfill')}
                checked={sdEnabled}
                onChange={setSdEnabled}
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-garage-text mb-1">
                {t('modal.livelink.odometerUnit')}
              </label>
              <Select
                value={odometerUnit}
                onChange={(e) => {
                  const next = e.target.value as 'km' | 'mi' | 'auto'
                  setOdometerUnit(next)
                  onUpdate(device.device_id, { odometer_unit: next })
                }}
                options={[
                  { value: 'auto', label: t('modal.livelink.odometerUnitAuto') },
                  { value: 'km', label: t('modal.livelink.odometerUnitKm') },
                  { value: 'mi', label: t('modal.livelink.odometerUnitMi') },
                ]}
              />
              <p className="mt-1 text-[11px] text-garage-text-muted max-w-56">
                {t('modal.livelink.odometerUnitHelp')}
              </p>
            </div>
            <button
              onClick={handleSaveSdConfig}
              disabled={savingSd || sdAddress.trim() === ''}
              className="flex items-center gap-1 px-3 py-1 bg-garage-surface border border-garage-border rounded text-xs text-garage-text hover:bg-garage-bg disabled:opacity-50"
            >
              {savingSd ? <RefreshCw className="w-3 h-3 animate-spin" /> : <CheckCircle className="w-3 h-3" />}
              {t('modal.livelink.save')}
            </button>
            <button
              onClick={handleBackfill}
              disabled={backfilling}
              className="flex items-center gap-1 px-3 py-1 btn btn-primary rounded text-xs disabled:opacity-50"
            >
              {backfilling ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Download className="w-3 h-3" />}
              {t('modal.livelink.pullSdLogsNow')}
            </button>
          </div>
        </td>
      </tr>
    )}
    </>
  )
}
