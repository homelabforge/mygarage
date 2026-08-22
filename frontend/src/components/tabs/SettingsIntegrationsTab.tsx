import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { CheckCircle, AlertCircle, Plug, Shield, Check, X, Plus, Radio, Settings, ArrowUpCircle, HelpCircle, Webhook, Sparkles, AtSign } from 'lucide-react'
import { useSettings } from '@/contexts/SettingsContext'
import { useAuth } from '@/contexts/AuthContext'
import api from '@/services/api'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'
import { livelinkService } from '@/services/livelinkService'
import type { LiveLinkSettings, LiveLinkDeviceListResponse, DeviceFirmwareStatus } from '@/types/livelink'
import AddProviderModal from '../modals/AddProviderModal'
import EditProviderModal from '../modals/EditProviderModal'
import LiveLinkSettingsModal from '../modals/LiveLinkSettingsModal'
import WidgetKeysPanel from '../settings/WidgetKeysPanel'
import { Select, Toggle, Drawer } from '../ui'

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
  // LiveLink infra (settings/token/MQTT/parameters/firmware/global device list)
  // is admin-only on the backend as of v2.28.0; gate the UI to match so
  // non-admins don't see controls that would 403. In none-mode auth is disabled
  // and the backend allows infra access (get_current_admin_user returns None),
  // so the single dev user must still see the panel.
  const { isAdmin, authMode } = useAuth()
  const canManageLiveLink = isAdmin || authMode === 'none'
  const [loading, setLoading] = useState(true)
  const { triggerSave, registerSaveHandler, unregisterSaveHandler } = useSettings()
  const [testing, setTesting] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null)
  const [providers, setProviders] = useState<POIProvider[]>([])
  const [isAddProviderModalOpen, setIsAddProviderModalOpen] = useState(false)
  const [selectedProvider, setSelectedProvider] = useState<POIProvider | null>(null)
  const [isEditModalOpen, setIsEditModalOpen] = useState(false)
  const [isLiveLinkModalOpen, setIsLiveLinkModalOpen] = useState(false)
  // Which card's "About" help sidecar is open (null = closed).
  const [helpDrawer, setHelpDrawer] = useState<'carcomplaints' | 'livelink' | null>(null)

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
    webhook_ingest_token: '',
    telegram_inbound_enabled: 'false',
    llm_receipt_parse_enabled: 'false',
    llm_base_url: 'http://127.0.0.1:11434/v1',
    llm_model: 'llama3.2',
    llm_api_key: '',
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
        webhook_ingest_token: settingsMap['webhook_ingest_token'] || '',
        telegram_inbound_enabled: settingsMap['telegram_inbound_enabled'] || 'false',
        llm_receipt_parse_enabled: settingsMap['llm_receipt_parse_enabled'] || 'false',
        llm_base_url: settingsMap['llm_base_url'] || 'http://127.0.0.1:11434/v1',
        llm_model: settingsMap['llm_model'] || 'llama3.2',
        llm_api_key: settingsMap['llm_api_key'] || '',
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
    // LiveLink infra endpoints are admin-only (allowed in none-mode); skip the
    // fetch for non-admins in an auth-enabled deployment.
    if (canManageLiveLink) {
      loadLiveLinkData()
    } else {
      setLivelinkLoading(false)
    }
  }, [loadSettings, loadLiveLinkData, loadProviders, canManageLiveLink])

  const handleEditProvider = (provider: POIProvider) => {
    setSelectedProvider(provider)
    setIsEditModalOpen(true)
  }

  const handleRemoveProvider = async (providerName: string) => {
    if (!confirm(t('integrationsTab.confirmRemoveProvider', { name: providerName }))) return

    try {
      await api.delete(`/settings/poi-providers/${providerName}`)
      await loadProviders()
      setMessage({ type: 'success', text: t('integrations.providerRemoved') })
    } catch (error: unknown) {
      setMessage({ type: 'error', text: getActionErrorMessage(error, t('integrations.removeProviderAction')) })
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
        webhook_ingest_token: formData.webhook_ingest_token,
        telegram_inbound_enabled: formData.telegram_inbound_enabled,
        llm_receipt_parse_enabled: formData.llm_receipt_parse_enabled,
        llm_base_url: formData.llm_base_url,
        llm_model: formData.llm_model,
        llm_api_key: formData.llm_api_key,
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
    <div className="max-w-6xl mx-auto space-y-6">
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

      {/* API Keys — user-scoped read keys for external integrations. Full width. */}
      <WidgetKeysPanel />

      {/* Inbound webhooks + Telegram bot + LLM receipt parse */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
          <div className="flex items-start gap-3 mb-6">
            <Webhook className="w-6 h-6 text-primary mt-1" />
            <div className="flex-1">
              <h2 className="text-xl font-semibold text-garage-text mb-2">{t('integrations.webhooks')}</h2>
              <p className="text-sm text-garage-text-muted">{t('integrations.webhooksDesc')}</p>
            </div>
          </div>
          <div className="space-y-4">
            <div>
              <label htmlFor="webhook_ingest_token" className="block text-sm font-medium text-garage-text mb-2">
                {t('integrations.webhookToken')}
              </label>
              <input
                type="password"
                id="webhook_ingest_token"
                value={formData.webhook_ingest_token}
                onChange={(e) => setFormData({ ...formData, webhook_ingest_token: e.target.value })}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary font-mono text-sm"
                placeholder={t('integrations.webhookTokenPlaceholder')}
                autoComplete="off"
              />
              <p className="mt-1 text-sm text-garage-text-muted">{t('integrations.webhookTokenDesc')}</p>
            </div>
            <div className="p-3 bg-garage-bg/50 border border-garage-border rounded-lg">
              <p className="text-xs text-garage-text-muted font-mono break-all">
                POST /api/v1/webhooks/fuel|odometer|reminders/complete
              </p>
              <p className="text-xs text-garage-text-muted mt-1">{t('integrations.webhookHeaderHint')}</p>
            </div>
          </div>
        </div>

        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
          <div className="flex items-start gap-3 mb-6">
            <AtSign className="w-6 h-6 text-primary mt-1" />
            <div className="flex-1">
              <h2 className="text-xl font-semibold text-garage-text mb-2">{t('integrations.telegramInbound')}</h2>
              <p className="text-sm text-garage-text-muted">{t('integrations.telegramInboundDesc')}</p>
            </div>
          </div>
          <div className="space-y-4">
            <div>
              <Toggle
                label={t('integrations.enableTelegramInbound')}
                checked={formData.telegram_inbound_enabled === 'true'}
                onChange={(next) =>
                  setFormData({ ...formData, telegram_inbound_enabled: next ? 'true' : 'false' })
                }
              />
              <p className="mt-1 text-sm text-garage-text-muted">
                {t('integrations.enableTelegramInboundDesc')}
              </p>
            </div>
            <div className="p-3 bg-garage-bg/50 border border-garage-border rounded-lg">
              <p className="text-xs text-garage-text-muted">{t('integrations.telegramCommandHint')}</p>
              <p className="text-xs text-garage-text-muted font-mono mt-1">
                fuel &lt;vin|nickname&gt; &lt;odo&gt;[km|mi] &lt;vol&gt;[L|gal|kWh] [price] [cost]
              </p>
            </div>
          </div>
        </div>

        <div className="bg-garage-surface rounded-lg border border-garage-border p-6 lg:col-span-2">
          <div className="flex items-start gap-3 mb-6">
            <Sparkles className="w-6 h-6 text-primary mt-1" />
            <div className="flex-1">
              <h2 className="text-xl font-semibold text-garage-text mb-2">{t('integrations.llmReceipt')}</h2>
              <p className="text-sm text-garage-text-muted">{t('integrations.llmReceiptDesc')}</p>
            </div>
          </div>
          <div className="space-y-4">
            <Toggle
              label={t('integrations.enableLlmReceipt')}
              checked={formData.llm_receipt_parse_enabled === 'true'}
              onChange={(next) =>
                setFormData({ ...formData, llm_receipt_parse_enabled: next ? 'true' : 'false' })
              }
            />
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label htmlFor="llm_base_url" className="block text-sm font-medium text-garage-text mb-2">
                  {t('integrations.llmBaseUrl')}
                </label>
                <input
                  type="url"
                  id="llm_base_url"
                  value={formData.llm_base_url}
                  disabled={formData.llm_receipt_parse_enabled === 'false'}
                  onChange={(e) => setFormData({ ...formData, llm_base_url: e.target.value })}
                  className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50 font-mono text-sm"
                  placeholder="http://127.0.0.1:11434/v1"
                />
              </div>
              <div>
                <label htmlFor="llm_model" className="block text-sm font-medium text-garage-text mb-2">
                  {t('integrations.llmModel')}
                </label>
                <input
                  type="text"
                  id="llm_model"
                  value={formData.llm_model}
                  disabled={formData.llm_receipt_parse_enabled === 'false'}
                  onChange={(e) => setFormData({ ...formData, llm_model: e.target.value })}
                  className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
                  placeholder="llama3.2"
                />
              </div>
              <div>
                <label htmlFor="llm_api_key" className="block text-sm font-medium text-garage-text mb-2">
                  {t('integrations.llmApiKey')}
                </label>
                <input
                  type="password"
                  id="llm_api_key"
                  value={formData.llm_api_key}
                  disabled={formData.llm_receipt_parse_enabled === 'false'}
                  onChange={(e) => setFormData({ ...formData, llm_api_key: e.target.value })}
                  className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
                  autoComplete="off"
                />
              </div>
            </div>
            <p className="text-sm text-garage-text-muted">{t('integrations.llmReceiptHint')}</p>
          </div>
        </div>
      </div>

      {/* NHTSA (tall) on the left; CarComplaints + LiveLink stacked on the right.
          items-start so the shorter right column doesn't stretch to NHTSA's height. */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
        {/* NHTSA Integration */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
        <div className="flex items-start gap-3 mb-6">
          <Shield className="w-6 h-6 text-primary mt-1" />
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
            <Toggle
              label={t('integrations.enableNHTSA')}
              checked={formData.nhtsa_enabled === 'true'}
              onChange={(next) => setFormData({ ...formData, nhtsa_enabled: next ? 'true' : 'false' })}
            />
            <p className="mt-1 text-sm text-garage-text-muted">
              {t('integrations.enableNHTSADesc')}
            </p>
          </div>

          {/* Auto-Check */}
          <div>
            <Toggle
              label={t('integrations.enableAutoCheck')}
              checked={formData.nhtsa_auto_check === 'true'}
              disabled={formData.nhtsa_enabled === 'false'}
              onChange={(next) => setFormData({ ...formData, nhtsa_auto_check: next ? 'true' : 'false' })}
            />
            <p className="mt-1 text-sm text-garage-text-muted">
              {t('integrations.enableAutoCheckDesc')}
            </p>
          </div>

          {/* Check Interval */}
          <div>
            <label htmlFor="recall_interval" className="block text-sm font-medium text-garage-text mb-2">
              {t('integrationsTab.recallCheckInterval')}
            </label>
            <Select
              id="recall_interval"
              value={formData.nhtsa_recall_check_interval}
              disabled={formData.nhtsa_enabled === 'false' || formData.nhtsa_auto_check === 'false'}
              onChange={(e) => setFormData({ ...formData, nhtsa_recall_check_interval: e.target.value })}
              options={[
                { value: '1', label: t('integrations.daily') },
                { value: '7', label: t('integrations.weeklyRecommended') },
                { value: '14', label: t('integrations.biWeekly') },
                { value: '30', label: t('integrations.monthly') },
                { value: '90', label: t('integrations.quarterly') },
              ]}
            />
            <p className="mt-1 text-sm text-garage-text-muted">
              {t('integrations.recallCheckIntervalDesc')}
            </p>
          </div>

          {/* NHTSA Recalls API URL */}
          <div>
            <label htmlFor="recalls_api_url" className="block text-sm font-medium text-garage-text mb-2">
              {t('integrationsTab.nhtsaRecallsApiUrl')}
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

        {/* Right column: CarComplaints + LiveLink stacked */}
        <div className="space-y-6">
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
          <button
            type="button"
            onClick={() => setHelpDrawer('carcomplaints')}
            aria-label={t('integrations.aboutCarComplaints')}
            className="shrink-0 inline-flex h-7 w-7 items-center justify-center rounded-full border border-garage-border text-garage-text-muted hover:text-(--accent-fg) hover:border-(--accent-line) transition-colors"
          >
            <HelpCircle className="w-4 h-4" />
          </button>
        </div>

        <div className="space-y-6">
          {/* Enable CarComplaints Integration */}
          <div>
            <Toggle
              label={t('integrations.enableCarComplaints')}
              checked={formData.carcomplaints_enabled === 'true'}
              onChange={(next) => setFormData({ ...formData, carcomplaints_enabled: next ? 'true' : 'false' })}
            />
            <p className="mt-1 text-sm text-garage-text-muted">
              {t('integrations.enableCarComplaintsDesc')}
            </p>
          </div>
        </div>
        </div>

        {/* LiveLink Integration — admin-only (infra endpoints require admin, v2.28.0;
            shown in none-mode where auth is disabled) */}
        {canManageLiveLink && (
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
          <div className="flex items-start gap-3 mb-6">
            <Radio className="w-6 h-6 text-primary mt-1" />
            <div className="flex-1">
              <h2 className="text-xl font-semibold text-garage-text mb-2">{t('integrations.livelink')}</h2>
              <p className="text-sm text-garage-text-muted">
                {t('integrations.livelinkDesc')}
              </p>
            </div>
            <button
              type="button"
              onClick={() => setHelpDrawer('livelink')}
              aria-label={t('integrations.aboutLiveLink')}
              className="shrink-0 inline-flex h-7 w-7 items-center justify-center rounded-full border border-garage-border text-garage-text-muted hover:text-(--accent-fg) hover:border-(--accent-line) transition-colors"
            >
              <HelpCircle className="w-4 h-4" />
            </button>
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
                      ? t('integrationsTab.noDataDevicesOffline')
                      : t('integrations.noDevices')}
                  </span>
                </div>

                {/* Device Summary */}
                {livelinkDevices && livelinkDevices.total > 0 && (
                  <div className="text-sm text-garage-text-muted">
                    {t('integrationsTab.devicesLinked', { count: livelinkDevices.total })}
                    {livelinkDevices.online_count > 0 && (
                      <span className="text-green-500">
                        {t('integrationsTab.devicesOnlineSuffix', { count: livelinkDevices.online_count })}
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
          </div>
        </div>
        )}
        </div>

        {/* Shop Finder Integration — full width for the provider table */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6 lg:col-span-2">
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
                    {provider.is_default
                      ? t('integrationsTab.providerDefault', { name: provider.display_name })
                      : provider.display_name}
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
                      : `${provider.api_usage || 0}/${t('integrationsTab.unlimited')}`}
                  </td>
                  <td className="py-3 px-3 text-right space-x-2">
                    <button
                      onClick={() => handleEditProvider(provider)}
                      className="text-(--accent-fg) hover:underline"
                    >
                      {t('integrationsTab.edit')}
                    </button>
                    {!provider.is_default && (
                      <button
                        onClick={() => handleRemoveProvider(provider.name)}
                        className="text-danger hover:underline"
                      >
                        {t('integrationsTab.remove')}
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
      </div>

      {/* Modals — rendered at the tab root, outside the grid */}
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

      {/* About / help sidecar — opened from each card's upper-right help button. */}
      <Drawer
        open={helpDrawer !== null}
        onClose={() => setHelpDrawer(null)}
        title={
          helpDrawer === 'livelink'
            ? t('integrations.aboutLiveLink')
            : t('integrations.aboutCarComplaints')
        }
        icon={HelpCircle}
        width="sm"
        closeLabel={t('common:close')}
      >
        {helpDrawer === 'carcomplaints' && (
          <div className="space-y-3">
            <p className="text-sm text-garage-text-muted">
              {t('integrationsTab.aboutCarComplaintsBody')}
            </p>
            <p className="text-sm text-garage-text-muted">
              <strong>{t('integrationsTab.noteLabel')}</strong> {t('integrationsTab.carComplaintsVehicleNote')}
            </p>
          </div>
        )}
        {helpDrawer === 'livelink' && (
          <div className="space-y-3">
            <p className="text-sm text-garage-text-muted">
              {t('integrationsTab.aboutLiveLinkBody')}
            </p>
            <p className="text-sm text-garage-text-muted">
              <strong>{t('integrationsTab.requiresLabel')}</strong> {t('integrationsTab.livelinkFirmwareRequirement')}
            </p>
          </div>
        )}
      </Drawer>
    </div>
  )
}
