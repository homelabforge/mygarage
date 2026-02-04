import { useState, useEffect, useCallback } from 'react'
import { CheckCircle, AlertCircle, Plug, Check, X, Plus, Radio, Settings, ArrowUpCircle } from 'lucide-react'
import { useSettings } from '@/contexts/SettingsContext'
import api from '@/services/api'
import { livelinkService } from '@/services/livelinkService'
import type { LiveLinkSettings, LiveLinkDeviceListResponse, DeviceFirmwareStatus } from '@/types/livelink'
import AddProviderModal from '../modals/AddProviderModal'
import EditProviderModal from '../modals/EditProviderModal'
import LiveLinkSettingsModal from '../modals/LiveLinkSettingsModal'

// Sample VIN for testing NHTSA API connection
const TEST_VIN = '1HGCM82633A123456'

type SettingRecord = {
  key: string
  value: string | null
}

type SettingsResponse = {
  settings: SettingRecord[]
}

type POIProvider = {
  name: string
  display_name: string
  enabled: boolean
  is_default: boolean
  api_key_masked?: string
  api_usage: number
  api_limit: number | null
  priority: number
}

export default function SettingsIntegrationsTab() {
  const [loading, setLoading] = useState(true)
  const { triggerSave, registerSaveHandler, unregisterSaveHandler } = useSettings()
  const [testing, setTesting] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null)
  const [providers, setProviders] = useState<POIProvider[]>([])
  const [isAddProviderModalOpen, setIsAddProviderModalOpen] = useState(false)
  const [selectedProvider, setSelectedProvider] = useState<POIProvider | null>(null)
  const [isEditModalOpen, setIsEditModalOpen] = useState(false)
  const [isLiveLinkModalOpen, setIsLiveLinkModalOpen] = useState(false)

  // LiveLink state
  const [livelinkSettings, setLivelinkSettings] = useState<LiveLinkSettings | null>(null)
  const [livelinkDevices, setLivelinkDevices] = useState<LiveLinkDeviceListResponse | null>(null)
  const [livelinkFirmware, setLivelinkFirmware] = useState<DeviceFirmwareStatus[]>([])
  const [livelinkLoading, setLivelinkLoading] = useState(true)

  const [formData, setFormData] = useState({
    nhtsa_enabled: 'true',
    nhtsa_auto_check: 'true',
    nhtsa_recall_check_interval: '7',
    nhtsa_recalls_api_url: 'https://api.nhtsa.gov/recalls/recallsByVehicle',
    carcomplaints_enabled: 'true',
    tomtom_api_key: '',
    tomtom_enabled: 'false',
  })
  const [loadedFormData, setLoadedFormData] = useState<typeof formData | null>(null)

  const loadSettings = useCallback(async () => {
    try {
      const response = await api.get('/settings')
      const data: SettingsResponse = response.data

      const settingsMap: Record<string, string> = {}
      data.settings.forEach((setting) => {
        settingsMap[setting.key] = setting.value || ''
      })

      const newFormData = {
        nhtsa_enabled: settingsMap['nhtsa_enabled'] || 'true',
        nhtsa_auto_check: settingsMap['nhtsa_auto_check'] || 'true',
        nhtsa_recall_check_interval: settingsMap['nhtsa_recall_check_interval'] || '7',
        nhtsa_recalls_api_url: settingsMap['nhtsa_recalls_api_url'] || 'https://api.nhtsa.gov/recalls/recallsByVehicle',
        carcomplaints_enabled: settingsMap['carcomplaints_enabled'] || 'true',
        tomtom_api_key: settingsMap['tomtom_api_key'] || '',
        tomtom_enabled: settingsMap['tomtom_enabled'] || 'false',
      }
      setFormData(newFormData)
      setLoadedFormData(newFormData)
    } catch {
      // Removed console.error
      setMessage({ type: 'error', text: 'Failed to load settings' })
    } finally {
      setLoading(false)
    }
  }, [])

  const loadProviders = async () => {
    try {
      console.log('Loading POI providers...')
      const response = await api.get('/settings/poi-providers')
      console.log('POI providers response:', response.data)
      setProviders(response.data.providers || [])
    } catch (error) {
      console.error('Failed to load POI providers:', error)
      setMessage({ type: 'error', text: 'Failed to load POI providers' })
    }
  }

  const loadLiveLinkData = useCallback(async () => {
    setLivelinkLoading(true)
    try {
      const [settings, devices, firmware] = await Promise.all([
        livelinkService.getSettings(),
        livelinkService.getDevices(),
        livelinkService.getDeviceFirmwareStatus(),
      ])
      setLivelinkSettings(settings)
      setLivelinkDevices(devices)
      setLivelinkFirmware(firmware)
    } catch {
      // LiveLink may not be configured yet, silently ignore
      setLivelinkSettings(null)
      setLivelinkDevices(null)
      setLivelinkFirmware([])
    } finally {
      setLivelinkLoading(false)
    }
  }, [])

  useEffect(() => {
    loadSettings()
    loadProviders()
    loadLiveLinkData()
  }, [loadSettings, loadLiveLinkData])

  const handleEditProvider = (provider: POIProvider) => {
    setSelectedProvider(provider)
    setIsEditModalOpen(true)
  }

  const handleRemoveProvider = async (providerName: string) => {
    if (!confirm(`Remove ${providerName} provider?`)) return

    try {
      await api.delete(`/settings/poi-providers/${providerName}`)
      await loadProviders()
      setMessage({ type: 'success', text: 'Provider removed' })
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } }
      setMessage({ type: 'error', text: err.response?.data?.detail || 'Failed to remove provider' })
    }
  }

  const handleSave = useCallback(async () => {
    await api.post('/settings/batch', {
      settings: {
        nhtsa_enabled: formData.nhtsa_enabled,
        nhtsa_auto_check: formData.nhtsa_auto_check,
        nhtsa_recall_check_interval: formData.nhtsa_recall_check_interval,
        nhtsa_recalls_api_url: formData.nhtsa_recalls_api_url,
        carcomplaints_enabled: formData.carcomplaints_enabled,
        tomtom_api_key: formData.tomtom_api_key,
        tomtom_enabled: formData.tomtom_enabled,
      },
    })
  }, [formData])

  // Register save handler
  useEffect(() => {
    registerSaveHandler('integrations', handleSave)
    return () => unregisterSaveHandler('integrations')
  }, [handleSave, registerSaveHandler, unregisterSaveHandler])

  // Auto-save when form data changes (after initial load)
  useEffect(() => {
    if (!loadedFormData) return // Nothing loaded yet

    if (JSON.stringify(formData) !== JSON.stringify(loadedFormData)) {
      triggerSave()
    }
  }, [formData, loadedFormData, triggerSave])

  const handleTestNHTSA = async () => {
    setTesting(true)
    setMessage(null)

    try {
      // Test NHTSA API by trying to decode a sample VIN
      await api.get(`/vin/decode/${TEST_VIN}`)

      setMessage({ type: 'success', text: 'NHTSA API connection successful!' })
      setTimeout(() => setMessage(null), 3000)
    } catch {
      // Removed console.error
      setMessage({ type: 'error', text: 'NHTSA API connection failed. Please check your internet connection.' })
    } finally {
      setTesting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">Loading integration settings...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Success/Error Messages */}
      {message && (
        <div
          className={`mb-6 p-4 rounded-lg border flex items-start gap-2 ${
            message.type === 'success'
              ? 'bg-success-500/10 border-success-500 text-success-500'
              : 'bg-danger-500/10 border-danger-500 text-danger-500'
          }`}
        >
          {message.type === 'success' ? (
            <CheckCircle className="w-5 h-5 mt-0.5" />
          ) : (
            <AlertCircle className="w-5 h-5 mt-0.5" />
          )}
          <div>{message.text}</div>
        </div>
      )}

      {/* Integration Cards Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* NHTSA Integration */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
        <div className="flex items-start gap-3 mb-6">
          <Plug className="w-6 h-6 text-primary mt-1" />
          <div className="flex-1">
            <h2 className="text-xl font-semibold text-garage-text mb-2">NHTSA</h2>
            <p className="text-sm text-garage-text-muted">
              Configure automatic recall checking from the National Highway Traffic Safety Administration
            </p>
          </div>
        </div>

        <div className="space-y-6">
          {/* Enable NHTSA Integration */}
          <div>
            <label className="flex items-center">
              <input
                type="checkbox"
                checked={formData.nhtsa_enabled === 'true'}
                onChange={(e) => setFormData({ ...formData, nhtsa_enabled: e.target.checked ? 'true' : 'false' })}
                className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2"
              />
              <span className="ml-2 text-sm text-garage-text font-medium">
                Enable NHTSA recall integration
              </span>
            </label>
            <p className="mt-1 ml-6 text-sm text-garage-text-muted">
              Allow MyGarage to fetch recall information from NHTSA's database
            </p>
          </div>

          {/* Auto-Check */}
          <div>
            <label className="flex items-center">
              <input
                type="checkbox"
                checked={formData.nhtsa_auto_check === 'true'}
                disabled={formData.nhtsa_enabled === 'false'}
                onChange={(e) => setFormData({ ...formData, nhtsa_auto_check: e.target.checked ? 'true' : 'false' })}
                className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2 disabled:opacity-50"
              />
              <span className="ml-2 text-sm text-garage-text font-medium">
                Enable automatic recall checking
              </span>
            </label>
            <p className="mt-1 ml-6 text-sm text-garage-text-muted">
              Automatically check for new recalls on a schedule
            </p>
          </div>

          {/* Check Interval */}
          <div>
            <label htmlFor="recall_interval" className="block text-sm font-medium text-garage-text mb-2">
              Recall Check Interval
            </label>
            <select
              id="recall_interval"
              value={formData.nhtsa_recall_check_interval}
              disabled={formData.nhtsa_enabled === 'false' || formData.nhtsa_auto_check === 'false'}
              onChange={(e) => setFormData({ ...formData, nhtsa_recall_check_interval: e.target.value })}
              className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
            >
              <option value="1">Daily</option>
              <option value="7">Weekly (Recommended)</option>
              <option value="14">Bi-weekly</option>
              <option value="30">Monthly</option>
              <option value="90">Quarterly</option>
            </select>
            <p className="mt-1 text-sm text-garage-text-muted">
              How often to automatically check NHTSA for new recalls
            </p>
          </div>

          {/* NHTSA Recalls API URL */}
          <div>
            <label htmlFor="recalls_api_url" className="block text-sm font-medium text-garage-text mb-2">
              NHTSA Recalls API URL
            </label>
            <input
              type="url"
              id="recalls_api_url"
              value={formData.nhtsa_recalls_api_url}
              disabled={formData.nhtsa_enabled === 'false'}
              onChange={(e) => setFormData({ ...formData, nhtsa_recalls_api_url: e.target.value })}
              className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50 font-mono text-sm"
              placeholder="https://api.nhtsa.gov/recalls/recallsByVehicle"
            />
            <p className="mt-1 text-sm text-garage-text-muted">
              Base URL for NHTSA recall queries. Change only if using a different API endpoint.
            </p>
          </div>

          {/* Test Connection */}
          <div className="pt-4 border-t border-garage-border">
            <button
              onClick={handleTestNHTSA}
              disabled={testing || formData.nhtsa_enabled === 'false'}
              className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50"
            >
              <CheckCircle size={16} />
              {testing ? 'Testing Connection...' : 'Test NHTSA Connection'}
            </button>
            <p className="mt-2 text-sm text-garage-text-muted">
              Verify that MyGarage can connect to NHTSA's API
            </p>
          </div>
        </div>
        </div>

        {/* CarComplaints Integration */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
        <div className="flex items-start gap-3 mb-6">
          <Plug className="w-6 h-6 text-primary mt-1" />
          <div className="flex-1">
            <h2 className="text-xl font-semibold text-garage-text mb-2">CarComplaints</h2>
            <p className="text-sm text-garage-text-muted">
              Enable direct links to CarComplaints.com for vehicle issue research and common problems
            </p>
          </div>
        </div>

        <div className="space-y-6">
          {/* Enable CarComplaints Integration */}
          <div>
            <label className="flex items-center">
              <input
                type="checkbox"
                checked={formData.carcomplaints_enabled === 'true'}
                onChange={(e) => setFormData({ ...formData, carcomplaints_enabled: e.target.checked ? 'true' : 'false' })}
                className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2"
              />
              <span className="ml-2 text-sm text-garage-text font-medium">
                Enable CarComplaints integration
              </span>
            </label>
            <p className="mt-1 ml-6 text-sm text-garage-text-muted">
              Show links to CarComplaints.com in the Recalls tab for researching common vehicle issues
            </p>
          </div>

          <div className="bg-garage-bg rounded-lg p-4 border border-garage-border">
            <h3 className="text-sm font-medium text-garage-text mb-2">About CarComplaints</h3>
            <p className="text-sm text-garage-text-muted">
              CarComplaints.com provides a database of consumer complaints, common problems, and issue trends for vehicles.
              This integration adds convenient links to research known issues for your specific vehicle make, model, and year.
            </p>
            <p className="text-sm text-garage-text-muted mt-2">
              <strong>Note:</strong> This integration is only available for cars and trucks, not RVs, trailers, or fifth wheels.
            </p>
          </div>
        </div>
        </div>

        {/* Shop Finder Integration */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
        <div className="flex items-start gap-3 mb-6">
          <Plug className="w-6 h-6 text-primary mt-1" />
          <div className="flex-1">
            <h2 className="text-xl font-semibold text-garage-text mb-2">Shop Finder</h2>
            <p className="text-sm text-garage-text-muted">
              Optional Service API Keys for enhanced POI discovery (automatically falls back to OSM)
            </p>
          </div>
        </div>

        <div className="space-y-4">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-garage-border">
                <th className="text-left py-2 px-3 text-garage-text">Provider</th>
                <th className="text-left py-2 px-3 text-garage-text">Active</th>
                <th className="text-left py-2 px-3 text-garage-text">API Limits</th>
                <th className="text-right py-2 px-3 text-garage-text">Options</th>
              </tr>
            </thead>
            <tbody>
              {providers.map((provider) => (
                <tr key={provider.name} className="border-b border-garage-border">
                  <td className="py-3 px-3 text-garage-text">
                    {provider.is_default ? `${provider.display_name} (Default)` : provider.display_name}
                  </td>
                  <td className="py-3 px-3">
                    {provider.enabled ? (
                      <Check className="w-4 h-4 text-green-500" />
                    ) : (
                      <X className="w-4 h-4 text-red-500" />
                    )}
                  </td>
                  <td className="py-3 px-3 text-garage-text-muted">
                    {provider.api_limit
                      ? `${provider.api_usage}/${provider.api_limit}`
                      : `${provider.api_usage || 0}/Unlimited`}
                  </td>
                  <td className="py-3 px-3 text-right space-x-2">
                    <button
                      onClick={() => handleEditProvider(provider)}
                      className="text-blue-400 hover:text-blue-300"
                    >
                      Edit
                    </button>
                    {!provider.is_default && (
                      <button
                        onClick={() => handleRemoveProvider(provider.name)}
                        className="text-red-400 hover:text-red-300"
                      >
                        Remove
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <button
            onClick={() => setIsAddProviderModalOpen(true)}
            className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" />
            Add Service
          </button>
        </div>
        </div>

        {/* LiveLink Integration */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
          <div className="flex items-start gap-3 mb-6">
            <Radio className="w-6 h-6 text-primary mt-1" />
            <div className="flex-1">
              <h2 className="text-xl font-semibold text-garage-text mb-2">LiveLink</h2>
              <p className="text-sm text-garage-text-muted">
                Real-time vehicle telemetry from WiCAN PRO OBD2 devices
              </p>
            </div>
          </div>

          <div className="space-y-6">
            {livelinkLoading ? (
              <div className="text-sm text-garage-text-muted">Loading LiveLink status...</div>
            ) : (
              <>
                {/* Status Indicator */}
                <div className="flex items-center gap-2">
                  <div
                    className={`w-3 h-3 rounded-full ${
                      !livelinkSettings?.enabled
                        ? 'bg-gray-500'
                        : livelinkDevices && livelinkDevices.online_count > 0
                        ? 'bg-green-500'
                        : 'bg-yellow-500'
                    }`}
                  />
                  <span className="text-sm text-garage-text">
                    {!livelinkSettings?.enabled
                      ? 'Disabled'
                      : livelinkDevices && livelinkDevices.online_count > 0
                      ? 'Receiving data'
                      : livelinkDevices && livelinkDevices.total > 0
                      ? 'No data (devices offline)'
                      : 'No devices configured'}
                  </span>
                </div>

                {/* Device Summary */}
                {livelinkDevices && livelinkDevices.total > 0 && (
                  <div className="text-sm text-garage-text-muted">
                    {livelinkDevices.total} device{livelinkDevices.total !== 1 ? 's' : ''} linked
                    {livelinkDevices.online_count > 0 && (
                      <span className="text-green-500">
                        , {livelinkDevices.online_count} online
                      </span>
                    )}
                  </div>
                )}

                {/* Firmware Update Badge */}
                {livelinkFirmware.some((d) => d.update_available) && (
                  <div className="flex items-center gap-2 text-sm text-yellow-500">
                    <ArrowUpCircle className="w-4 h-4" />
                    <span>Firmware update available</span>
                  </div>
                )}

                {/* Configure Button */}
                <div className="pt-4 border-t border-garage-border">
                  <button
                    onClick={() => setIsLiveLinkModalOpen(true)}
                    className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
                  >
                    <Settings size={16} />
                    Configure LiveLink
                  </button>
                  <p className="mt-2 text-sm text-garage-text-muted">
                    Manage devices, tokens, alerts, and data retention
                  </p>
                </div>
              </>
            )}

            {/* Info Box */}
            <div className="bg-garage-bg rounded-lg p-4 border border-garage-border">
              <h3 className="text-sm font-medium text-garage-text mb-2">About LiveLink</h3>
              <p className="text-sm text-garage-text-muted">
                LiveLink connects WiCAN PRO OBD2 devices to MyGarage for real-time vehicle telemetry.
                Track engine parameters, detect drive sessions, and receive diagnostic trouble code alerts.
              </p>
              <p className="text-sm text-garage-text-muted mt-2">
                <strong>Requires:</strong> WiCAN PRO with firmware v4.40 or newer
              </p>
            </div>
          </div>
        </div>

        <AddProviderModal
          isOpen={isAddProviderModalOpen}
          onClose={() => setIsAddProviderModalOpen(false)}
          onProviderAdded={loadProviders}
        />

        <EditProviderModal
          isOpen={isEditModalOpen}
          provider={selectedProvider}
          onClose={() => setIsEditModalOpen(false)}
          onSave={loadProviders}
        />

        <LiveLinkSettingsModal
          isOpen={isLiveLinkModalOpen}
          onClose={() => setIsLiveLinkModalOpen(false)}
        />
      </div>
    </div>
  )
}
