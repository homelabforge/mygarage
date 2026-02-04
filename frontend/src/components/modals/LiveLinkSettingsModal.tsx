import { useState, useEffect, useCallback } from 'react'
import { toast } from 'sonner'
import {
  X,
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
} from 'lucide-react'
import { livelinkService } from '@/services/livelinkService'
import { vehicleService } from '@/services/vehicleService'
import type {
  LiveLinkSettings,
  LiveLinkSettingsUpdate,
  LiveLinkDevice,
  LiveLinkDeviceListResponse,
  FirmwareInfo,
  DeviceFirmwareStatus,
  MQTTSettings,
  MQTTStatus,
} from '@/types/livelink'
import type { Vehicle } from '@/types/vehicle'

interface LiveLinkSettingsModalProps {
  isOpen: boolean
  onClose: () => void
}

export default function LiveLinkSettingsModal({ isOpen, onClose }: LiveLinkSettingsModalProps) {
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
      toast.error('Failed to load LiveLink settings')
    } finally {
      setLoading(false)
    }
  }, [])

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
      toast.success('Settings saved')
    } catch (error) {
      console.error('Failed to save settings:', error)
      toast.error('Failed to save settings')
    } finally {
      setSaving(false)
    }
  }

  // Generate global token
  const handleRegenerateToken = async () => {
    if (
      !confirm(
        'Regenerating the global token will immediately invalidate the current token. Any WiCAN devices using the old token will stop sending data until reconfigured. Continue?'
      )
    ) {
      return
    }

    setGeneratingToken(true)
    try {
      const response = await livelinkService.regenerateGlobalToken()
      setNewToken(response.token)
      setShowToken(true)
      toast.success('New token generated')
      const updated = await livelinkService.getSettings()
      setSettings(updated)
    } catch (error) {
      console.error('Failed to generate token:', error)
      toast.error('Failed to generate token')
    } finally {
      setGeneratingToken(false)
    }
  }

  // Copy to clipboard
  const copyToClipboard = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text)
      toast.success(`${label} copied to clipboard`)
    } catch {
      toast.error('Failed to copy to clipboard')
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
      toast.success('Firmware check complete')
    } catch (error) {
      console.error('Failed to check firmware:', error)
      toast.error('Failed to check firmware updates')
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
      toast.success('MQTT settings saved')
    } catch (error) {
      console.error('Failed to save MQTT settings:', error)
      toast.error('Failed to save MQTT settings')
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
      toast.error('Failed to test MQTT connection')
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
      toast.success('MQTT subscriber restarted')
    } catch (error) {
      console.error('Failed to restart MQTT subscriber:', error)
      toast.error('Failed to restart MQTT subscriber')
    } finally {
      setRestartingMqtt(false)
    }
  }

  // Update device
  const handleUpdateDevice = async (
    deviceId: string,
    update: { vin?: string | null; label?: string; enabled?: boolean }
  ) => {
    try {
      await livelinkService.updateDevice(deviceId, update)
      toast.success('Device updated')
      const updated = await livelinkService.getDevices()
      setDevices(updated)
    } catch (error) {
      console.error('Failed to update device:', error)
      toast.error('Failed to update device')
    }
  }

  // Delete device
  const handleDeleteDevice = async (deviceId: string) => {
    if (
      !confirm(
        'Delete this device? Historical telemetry data will be retained but the device will need to be re-discovered.'
      )
    ) {
      return
    }

    try {
      await livelinkService.deleteDevice(deviceId)
      toast.success('Device deleted')
      const updated = await livelinkService.getDevices()
      setDevices(updated)
    } catch (error) {
      console.error('Failed to delete device:', error)
      toast.error('Failed to delete device')
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
      toast.error('Failed to generate device token')
    }
  }

  // Revoke device token
  const handleRevokeDeviceToken = async (deviceId: string) => {
    if (!confirm('Revoke this device token? The device will fall back to using the global token.')) {
      return
    }

    try {
      await livelinkService.revokeDeviceToken(deviceId)
      toast.success('Device token revoked')
      const updated = await livelinkService.getDevices()
      setDevices(updated)
    } catch (error) {
      console.error('Failed to revoke device token:', error)
      toast.error('Failed to revoke device token')
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-garage-surface rounded-lg border border-garage-border w-full max-w-4xl mx-4 max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-garage-border shrink-0">
          <div className="flex items-center gap-3">
            <Settings className="w-6 h-6 text-primary" />
            <div>
              <h2 className="text-xl font-semibold text-garage-text">LiveLink Settings</h2>
              <p className="text-sm text-garage-text-muted">Configure WiCAN OBD2 telemetry integration</p>
            </div>
          </div>
          <button onClick={onClose} className="text-garage-text-muted hover:text-garage-text">
            <X className="w-6 h-6" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
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
                  <h3 className="text-lg font-semibold text-garage-text">Connection</h3>
                </div>

                <div className="space-y-4">
                  {/* Enable Toggle */}
                  <label className="flex items-center gap-3">
                    <input
                      type="checkbox"
                      checked={settings?.enabled ?? false}
                      onChange={(e) => handleSaveSettings({ enabled: e.target.checked })}
                      disabled={saving}
                      className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2"
                    />
                    <div>
                      <span className="text-garage-text font-medium">Enable LiveLink</span>
                      <p className="text-xs text-garage-text-muted">Accept telemetry data from WiCAN devices</p>
                    </div>
                  </label>

                  {/* Ingestion URL */}
                  <div>
                    <label className="block text-sm font-medium text-garage-text mb-1">Ingestion URL</label>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        readOnly
                        value={settings?.ingestion_url ?? ''}
                        className="flex-1 px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text font-mono text-xs"
                      />
                      <button
                        onClick={() => copyToClipboard(settings?.ingestion_url ?? '', 'URL')}
                        className="px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text hover:bg-garage-bg"
                      >
                        <Copy className="w-4 h-4" />
                      </button>
                    </div>
                  </div>

                  {/* Global Token */}
                  <div>
                    <label className="block text-sm font-medium text-garage-text mb-1">Global API Token</label>
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
                            onClick={() => copyToClipboard(newToken, 'Token')}
                            className="px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text hover:bg-garage-bg"
                          >
                            <Copy className="w-4 h-4" />
                          </button>
                        </div>
                        <div className="p-2 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
                          <p className="text-xs text-yellow-500">
                            <strong>Save this token now!</strong> It will not be shown again.
                          </p>
                        </div>
                      </div>
                    ) : (
                      <div className="flex items-center gap-4">
                        {settings?.has_global_token ? (
                          <span className="flex items-center gap-2 text-sm text-green-500">
                            <CheckCircle className="w-4 h-4" />
                            Token configured
                          </span>
                        ) : (
                          <span className="flex items-center gap-2 text-sm text-yellow-500">
                            <AlertCircle className="w-4 h-4" />
                            No token configured
                          </span>
                        )}
                        <button
                          onClick={handleRegenerateToken}
                          disabled={generatingToken}
                          className="flex items-center gap-2 btn btn-primary rounded-lg disabled:opacity-50"
                        >
                          <RefreshCw className={`w-4 h-4 ${generatingToken ? 'animate-spin' : ''}`} />
                          {settings?.has_global_token ? 'Regenerate' : 'Generate'}
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
                  <h3 className="text-lg font-semibold text-garage-text">MQTT Subscription</h3>
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
                  <label className="flex items-center gap-3">
                    <input
                      type="checkbox"
                      checked={mqttSettings?.enabled ?? false}
                      onChange={(e) => handleSaveMqttSettings({ enabled: e.target.checked })}
                      disabled={savingMqtt}
                      className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2"
                    />
                    <div>
                      <span className="text-garage-text font-medium">Enable MQTT Subscription</span>
                      <p className="text-xs text-garage-text-muted">Subscribe to WiCAN MQTT topics on a local broker</p>
                    </div>
                  </label>

                  {/* Broker Settings */}
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-garage-text mb-1">Broker Host</label>
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
                      <label className="block text-sm font-medium text-garage-text mb-1">Port</label>
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
                      <label className="block text-sm font-medium text-garage-text mb-1">Username</label>
                      <input
                        type="text"
                        value={mqttSettings?.username ?? ''}
                        onChange={(e) => handleSaveMqttSettings({ username: e.target.value })}
                        placeholder="Optional"
                        disabled={savingMqtt}
                        className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text text-sm focus:ring-2 focus:ring-primary"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-garage-text mb-1">
                        Password {mqttSettings?.has_password && <span className="text-green-500 text-xs">(set)</span>}
                      </label>
                      <div className="flex gap-2">
                        <input
                          type="password"
                          value={mqttPassword}
                          onChange={(e) => setMqttPassword(e.target.value)}
                          placeholder={mqttSettings?.has_password ? '••••••••' : 'Optional'}
                          disabled={savingMqtt}
                          className="flex-1 px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text text-sm focus:ring-2 focus:ring-primary"
                        />
                        {mqttPassword && (
                          <button
                            onClick={() => handleSaveMqttSettings({ password: mqttPassword })}
                            disabled={savingMqtt}
                            className="btn btn-primary rounded-lg disabled:opacity-50"
                          >
                            Save
                          </button>
                        )}
                      </div>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-garage-text mb-1">Topic Prefix</label>
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
                      <label className="flex items-center gap-3">
                        <input
                          type="checkbox"
                          checked={mqttSettings?.use_tls ?? false}
                          onChange={(e) => handleSaveMqttSettings({ use_tls: e.target.checked })}
                          disabled={savingMqtt}
                          className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2"
                        />
                        <span className="text-garage-text font-medium text-sm">Use TLS/SSL</span>
                      </label>
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
                        <span className="text-garage-text">{mqttStatus.running ? 'Running' : 'Stopped'}</span>
                        {mqttStatus.messages_processed > 0 && (
                          <span className="text-garage-text-muted">
                            ({mqttStatus.messages_processed.toLocaleString()} msgs)
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
                        Test
                      </button>
                      <button
                        onClick={handleRestartMqtt}
                        disabled={restartingMqtt}
                        className="flex items-center gap-2 btn btn-primary rounded-lg disabled:opacity-50"
                      >
                        {restartingMqtt ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                        {mqttStatus?.running ? 'Restart' : 'Start'}
                      </button>
                    </div>
                  </div>
                </div>
              </section>

              {/* Section: Devices */}
              <section className="bg-garage-bg rounded-lg border border-garage-border p-4">
                <div className="flex items-center gap-2 mb-4">
                  <Cpu className="w-5 h-5 text-primary" />
                  <h3 className="text-lg font-semibold text-garage-text">Devices</h3>
                  <span className="text-sm text-garage-text-muted">
                    ({devices?.total ?? 0} discovered, {devices?.online_count ?? 0} online)
                  </span>
                </div>

                {devices && devices.devices.length > 0 ? (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-garage-border">
                          <th className="text-left py-2 px-3 text-garage-text">Device</th>
                          <th className="text-left py-2 px-3 text-garage-text">Status</th>
                          <th className="text-left py-2 px-3 text-garage-text">Vehicle</th>
                          <th className="text-left py-2 px-3 text-garage-text">Firmware</th>
                          <th className="text-right py-2 px-3 text-garage-text">Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {devices.devices.map((device) => (
                          <DeviceRow
                            key={device.device_id}
                            device={device}
                            vehicles={vehicles}
                            deviceFirmware={deviceFirmware.find((d) => d.device_id === device.device_id)}
                            onUpdate={handleUpdateDevice}
                            onDelete={handleDeleteDevice}
                            onGenerateToken={handleGenerateDeviceToken}
                            onRevokeToken={handleRevokeDeviceToken}
                          />
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="text-center py-6 text-garage-text-muted">
                    <Cpu className="w-10 h-10 mx-auto mb-2 opacity-50" />
                    <p>No WiCAN devices discovered yet</p>
                  </div>
                )}
              </section>

              {/* Section: Data Retention */}
              <section className="bg-garage-bg rounded-lg border border-garage-border p-4">
                <div className="flex items-center gap-2 mb-4">
                  <Database className="w-5 h-5 text-primary" />
                  <h3 className="text-lg font-semibold text-garage-text">Data Retention</h3>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-garage-text mb-1">Raw Telemetry Retention</label>
                    <select
                      value={settings?.telemetry_retention_days ?? 90}
                      onChange={(e) => handleSaveSettings({ telemetry_retention_days: parseInt(e.target.value) })}
                      disabled={saving}
                      className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text text-sm focus:ring-2 focus:ring-primary"
                    >
                      <option value="30">30 days</option>
                      <option value="60">60 days</option>
                      <option value="90">90 days</option>
                      <option value="180">180 days</option>
                      <option value="365">365 days</option>
                    </select>
                  </div>
                  <div className="flex items-center">
                    <label className="flex items-center gap-3">
                      <input
                        type="checkbox"
                        checked={settings?.daily_aggregation_enabled ?? true}
                        onChange={(e) => handleSaveSettings({ daily_aggregation_enabled: e.target.checked })}
                        disabled={saving}
                        className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2"
                      />
                      <div>
                        <span className="text-garage-text font-medium text-sm">Daily Aggregation</span>
                        <p className="text-xs text-garage-text-muted">Keep daily summaries after raw data is deleted</p>
                      </div>
                    </label>
                  </div>
                </div>
              </section>

              {/* Section: Alerts & Notifications */}
              <section className="bg-garage-bg rounded-lg border border-garage-border p-4">
                <div className="flex items-center gap-2 mb-4">
                  <Bell className="w-5 h-5 text-primary" />
                  <h3 className="text-lg font-semibold text-garage-text">Alerts & Notifications</h3>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-garage-text mb-1">Device Offline Timeout</label>
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
                      <span className="text-garage-text-muted text-sm">minutes</span>
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-garage-text mb-1">Alert Cooldown</label>
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
                      <span className="text-garage-text-muted text-sm">minutes</span>
                    </div>
                  </div>
                  <div className="col-span-2 grid grid-cols-2 gap-3">
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={settings?.notify_new_device ?? true}
                        onChange={(e) => handleSaveSettings({ notify_new_device: e.target.checked })}
                        disabled={saving}
                        className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded"
                      />
                      <span className="text-sm text-garage-text">New device discovered</span>
                    </label>
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={settings?.notify_device_offline ?? true}
                        onChange={(e) => handleSaveSettings({ notify_device_offline: e.target.checked })}
                        disabled={saving}
                        className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded"
                      />
                      <span className="text-sm text-garage-text">Device goes offline</span>
                    </label>
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={settings?.notify_threshold_alerts ?? true}
                        onChange={(e) => handleSaveSettings({ notify_threshold_alerts: e.target.checked })}
                        disabled={saving}
                        className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded"
                      />
                      <span className="text-sm text-garage-text">Parameter threshold breaches</span>
                    </label>
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={settings?.notify_firmware_update ?? true}
                        onChange={(e) => handleSaveSettings({ notify_firmware_update: e.target.checked })}
                        disabled={saving}
                        className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded"
                      />
                      <span className="text-sm text-garage-text">Firmware update available</span>
                    </label>
                  </div>
                </div>
              </section>

              {/* Section: Firmware */}
              <section className="bg-garage-bg rounded-lg border border-garage-border p-4">
                <div className="flex items-center gap-2 mb-4">
                  <Settings className="w-5 h-5 text-primary" />
                  <h3 className="text-lg font-semibold text-garage-text">Firmware Updates</h3>
                </div>

                <div className="space-y-4">
                  <label className="flex items-center gap-3">
                    <input
                      type="checkbox"
                      checked={settings?.firmware_check_enabled ?? true}
                      onChange={(e) => handleSaveSettings({ firmware_check_enabled: e.target.checked })}
                      disabled={saving}
                      className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2"
                    />
                    <div>
                      <span className="text-garage-text font-medium text-sm">Auto-check for updates</span>
                      <p className="text-xs text-garage-text-muted">Check GitHub daily for new WiCAN firmware releases</p>
                    </div>
                  </label>

                  <div className="flex items-center gap-4">
                    <div>
                      <p className="text-xs text-garage-text-muted">Latest available</p>
                      <p className="text-lg font-mono text-garage-text">{firmware?.latest_tag ?? 'Unknown'}</p>
                    </div>
                    <button
                      onClick={handleCheckFirmware}
                      disabled={checkingFirmware}
                      className="flex items-center gap-2 px-4 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text hover:bg-garage-bg disabled:opacity-50"
                    >
                      <RefreshCw className={`w-4 h-4 ${checkingFirmware ? 'animate-spin' : ''}`} />
                      Check Now
                    </button>
                    {firmware?.release_url && (
                      <button
                        onClick={() => window.open(firmware.release_url!, '_blank')}
                        className="flex items-center gap-2 px-4 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text hover:bg-garage-bg"
                      >
                        <ExternalLink className="w-4 h-4" />
                        View Release
                      </button>
                    )}
                  </div>
                </div>
              </section>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 p-4 border-t border-garage-border shrink-0">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-garage-surface border border-garage-border rounded-lg text-garage-text hover:bg-garage-bg"
          >
            Close
          </button>
        </div>
      </div>

      {/* Device Token Modal */}
      {deviceTokenModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60]">
          <div className="bg-garage-surface rounded-lg border border-garage-border p-6 max-w-lg w-full mx-4">
            <h3 className="text-lg font-semibold text-garage-text mb-4">Device Token Generated</h3>
            <div className="space-y-4">
              <div>
                <label className="block text-sm text-garage-text-muted mb-2">
                  Token for device {deviceTokenModal.deviceId}
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    readOnly
                    value={deviceTokenModal.token ?? ''}
                    className="flex-1 px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text font-mono text-sm"
                  />
                  <button
                    onClick={() => copyToClipboard(deviceTokenModal.token ?? '', 'Token')}
                    className="px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text hover:bg-garage-surface"
                  >
                    <Copy className="w-4 h-4" />
                  </button>
                </div>
              </div>
              <div className="p-3 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
                <p className="text-sm text-yellow-500">
                  <strong>Save this token now!</strong> It will not be shown again.
                </p>
              </div>
              <div className="flex justify-end">
                <button
                  onClick={() => setDeviceTokenModal(null)}
                  className="btn btn-primary rounded-lg"
                >
                  Done
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// Device row component
function DeviceRow({
  device,
  vehicles,
  deviceFirmware,
  onUpdate,
  onDelete,
  onGenerateToken,
  onRevokeToken,
}: {
  device: LiveLinkDevice
  vehicles: Vehicle[]
  deviceFirmware?: DeviceFirmwareStatus
  onUpdate: (deviceId: string, update: { vin?: string | null; label?: string; enabled?: boolean }) => void
  onDelete: (deviceId: string) => void
  onGenerateToken: (deviceId: string) => void
  onRevokeToken: (deviceId: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [label, setLabel] = useState(device.label ?? '')

  const handleSaveLabel = () => {
    onUpdate(device.device_id, { label: label || undefined })
    setEditing(false)
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
    <tr className="border-b border-garage-border hover:bg-garage-surface/50">
      <td className="py-2 px-3">
        <div>
          {editing ? (
            <div className="flex gap-2">
              <input
                type="text"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="Label"
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
            ECU: {device.ecu_status}
          </span>
        </div>
      </td>
      <td className="py-2 px-3">
        <select
          value={device.vin ?? ''}
          onChange={(e) => onUpdate(device.device_id, { vin: e.target.value || null })}
          className="px-2 py-1 bg-garage-surface border border-garage-border rounded text-xs text-garage-text"
        >
          <option value="">Unlinked</option>
          {vehicles.map((v) => (
            <option key={v.vin} value={v.vin}>
              {v.nickname || `${v.year} ${v.make} ${v.model}`}
            </option>
          ))}
        </select>
      </td>
      <td className="py-2 px-3">
        <span className="text-xs text-garage-text">{device.fw_version ?? 'Unknown'}</span>
        {deviceFirmware?.update_available && (
          <span className="ml-1 px-1 py-0.5 bg-yellow-500/20 text-yellow-500 text-xs rounded">Update</span>
        )}
      </td>
      <td className="py-2 px-3 text-right">
        <div className="flex items-center justify-end gap-1">
          {device.sta_ip && (
            <a
              href={`http://${device.sta_ip}`}
              target="_blank"
              rel="noopener noreferrer"
              className="p-1 text-garage-text-muted hover:text-primary"
              title="Open device UI"
            >
              <ExternalLink className="w-4 h-4" />
            </a>
          )}
          {device.has_device_token ? (
            <button
              onClick={() => onRevokeToken(device.device_id)}
              className="p-1 text-yellow-500 hover:text-yellow-400"
              title="Revoke device token"
            >
              <Key className="w-4 h-4" />
            </button>
          ) : (
            <button
              onClick={() => onGenerateToken(device.device_id)}
              className="p-1 text-garage-text-muted hover:text-primary"
              title="Generate device token"
            >
              <Key className="w-4 h-4" />
            </button>
          )}
          <button
            onClick={() => onDelete(device.device_id)}
            className="p-1 text-garage-text-muted hover:text-red-500"
            title="Delete device"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </td>
    </tr>
  )
}
