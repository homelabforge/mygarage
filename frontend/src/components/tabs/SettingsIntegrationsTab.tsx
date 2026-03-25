import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
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
  const { t } = useTranslation('settings')
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
      setMessage({ type: 'error', text: t('integrations.loadError') })
    } finally {
      setLoading(false)
    }
  }, [t])

  const loadProviders = useCallback(async () => {
    try {
      console.log('Loading POI providers...')
      const response = await api.get('/settings/poi-providers')
      console.log('POI providers response:', response.data)
      setProviders(response.data.providers || [])
    } catch (error) {
      console.error('Failed to load POI providers:', error)
      setMessage({ type: 'error', text: t('integrations.loadProvidersError') })
    }
  }, [t])

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
  }, [loadSettings, loadLiveLinkData, loadProviders])

  const handleEditProvider = (provider: POIProvider) => {
    setSelectedProvider(provider)
    setIsEditModalOpen(true)
  }

  const handleRemoveProvider = async (providerName: string) => {
    if (!confirm(`Remove ${providerName} provider?`)) return

    try {
      await api.delete(`/settings/poi-providers/${providerName}`)
      await loadProviders()
      setMessage({ type: 'success', text: t('integrations.providerRemoved') })
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } }
      setMessage({ type: 'error', text: err.response?.data?.detail || t('integrations.removeProviderError') })
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

      setMessage({ type: 'success', text: t('integrations.nhtsaTestSuccess') })
      setTimeout(() => setMessage(null), 3000)
    } catch {
      // Removed console.error
      setMessage({ type: 'error', text: t('integrations.nhtsaTestFailed') })
    } finally {
      setTesting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">{t('integrations.loading')}</div>
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
            <h2 className="text-xl font-semibold text-garage-text mb-2">{t('integrations.nhtsa')}</h2>
            <p className="text-sm text-garage-text-muted">
              {t('integrations.nhtsaDesc')}
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
                {t('integrations.enableNHTSA')}
              </span>
            </label>
            <p className="mt-1 ml-6 text-sm text-garage-text-muted">
              {t('integrations.enableNHTSADesc')}
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
                {t('integrations.enableAutoCheck')}
              </span>
            </label>
            <p className="mt-1 ml-6 text-sm text-garage-text-muted">
              {t('integrations.enableAutoCheckDesc')}
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
              <option value="1">{t('integrations.daily')}</option>
              <option value="7">{t('integrations.weeklyRecommended')}</option>
              <option value="14">{t('integrations.biWeekly')}</option>
              <option value="30">{t('integrations.monthly')}</option>
              <option value="90">{t('integrations.quarterly')}</option>
            </select>
            <p className="mt-1 text-sm text-garage-text-muted">
              {t('integrations.recallCheckIntervalDesc')}
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
              {t('integrations.nhtsaApiUrlDesc')}
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
              {testing ? t('integrations.testingConnection') : t('integrations.testNHTSA')}
            </button>
            <p className="mt-2 text-sm text-garage-text-muted">
              {t('integrations.testNHTSADesc')}
            </p>
          </div>
        </div>
        </div>

        {/* CarComplaints Integration */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
        <div className="flex items-start gap-3 mb-6">
          <Plug className="w-6 h-6 text-primary mt-1" />
          <div className="flex-1">
            <h2 className="text-xl font-semibold text-garage-text mb-2">{t('integrations.carComplaints')}</h2>
            <p className="text-sm text-garage-text-muted">
              {t('integrations.carComplaintsDesc')}
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
                {t('integrations.enableCarComplaints')}
              </span>
            </label>
            <p className="mt-1 ml-6 text-sm text-garage-text-muted">
              {t('integrations.enableCarComplaintsDesc')}
            </p>
          </div>

          <div className="bg-garage-bg rounded-lg p-4 border border-garage-border">
            <h3 className="text-sm font-medium text-garage-text mb-2">{t('integrations.aboutCarComplaints')}</h3>
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
            <h2 className="text-xl font-semibold text-garage-text mb-2">{t('integrations.shopFinder')}</h2>
            <p className="text-sm text-garage-text-muted">
              {t('integrations.shopFinderDesc')}
            </p>
          </div>
        </div>

        <div className="space-y-4">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-garage-border">
                <th className="text-left py-2 px-3 text-garage-text">{t('integrations.provider')}</th>
                <th className="text-left py-2 px-3 text-garage-text">{t('integrations.active')}</th>
                <th className="text-left py-2 px-3 text-garage-text">{t('integrations.apiLimits')}</th>
                <th className="text-right py-2 px-3 text-garage-text">{t('integrations.options')}</th>
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
            {t('integrations.addService')}
          </button>
        </div>
        </div>

        {/* LiveLink Integration */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
          <div className="flex items-start gap-3 mb-6">
            <Radio className="w-6 h-6 text-primary mt-1" />
            <div className="flex-1">
              <h2 className="text-xl font-semibold text-garage-text mb-2">{t('integrations.livelink')}</h2>
              <p className="text-sm text-garage-text-muted">
                {t('integrations.livelinkDesc')}
              </p>
            </div>
          </div>

          <div className="space-y-6">
            {livelinkLoading ? (
              <div className="text-sm text-garage-text-muted">{t('integrations.livelinkLoading')}</div>
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
                      ? t('integrations.disabled')
                      : livelinkDevices && livelinkDevices.online_count > 0
                      ? t('integrations.receivingData')
                      : livelinkDevices && livelinkDevices.total > 0
                      ? 'No data (devices offline)'
                      : t('integrations.noDevices')}
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
                    <span>{t('integrations.firmwareUpdate')}</span>
                  </div>
                )}

                {/* Configure Button */}
                <div className="pt-4 border-t border-garage-border">
                  <button
                    onClick={() => setIsLiveLinkModalOpen(true)}
                    className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
                  >
                    <Settings size={16} />
                    {t('integrations.configureLiveLink')}
                  </button>
                  <p className="mt-2 text-sm text-garage-text-muted">
                    {t('integrations.configureDesc')}
                  </p>
                </div>
              </>
            )}

            {/* Info Box */}
            <div className="bg-garage-bg rounded-lg p-4 border border-garage-border">
              <h3 className="text-sm font-medium text-garage-text mb-2">{t('integrations.aboutLiveLink')}</h3>
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
