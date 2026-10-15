import { useState, useEffect, useCallback, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { CheckCircle, AlertCircle, Plug, Shield, Radio, HelpCircle, Webhook, Sparkles, Settings, Globe } from 'lucide-react'
import { useSettings } from '@/contexts/SettingsContext'
import { useCanManageInstance } from '@/hooks/useCanManageInstance'
import api, { getErrorMessage } from '@/services/api'
import WidgetKeysPanel from '../settings/WidgetKeysPanel'
import { Card, IconButton, Select, Toggle, Drawer } from '../ui'
import type { IconType } from '../ui/types'
import AddSourceDrawer from '@/components/livelink/AddSourceDrawer'
import LiveLinkIntegrationsCard from '@/components/livelink/LiveLinkIntegrationsCard'
import LiveLinkSettingsDrawers, { type SettingsTarget } from '@/components/livelink/settings/LiveLinkSettingsDrawers'

// Sample VIN for testing NHTSA API connection
const TEST_VIN = '1HGCM82633A123456'
// The base, not the endpoint: the backend adds /recallsByVehicle itself, so the
// full endpoint got saved and fetched with the path twice. Same as the
// backend's DEFAULT_RECALLS_API_URL.
const NHTSA_RECALLS_BASE_URL = 'https://api.nhtsa.gov/recalls'

type SettingRecord = {
  key: string
  value: string | null
}

type SettingsResponse = {
  settings: SettingRecord[]
}

/**
 * One integration section.
 *
 * Replaces seven copies of `bg-garage-surface rounded-lg border
 * border-garage-border p-6` wrapping a hand-rolled `<h2>` — pre-reskin markup
 * that the rest of the app stopped using at v3.0.0, which is why this tab drifted
 * out of step with every card beside it.
 *
 * The title row is written out here rather than delegated to `CardHeader`, which
 * would otherwise be the obvious reuse: `CardHeader` renders its icon on the
 * RIGHT, beside the actions, and has no slot for a subtitle. This tab needs the
 * icon leading the title with the description stacked under it, which is what
 * `settings/WidgetKeysPanel.tsx` does at the top of this same page -- so taking
 * `CardHeader` put two different header shapes on one screen. The `h3`
 * typography is copied from it so the two stay identical. Seven hand-rolled
 * headers becoming one is still the point; promoting a `description` +
 * leading-icon variant into `CardHeader` is the follow-up, and is a change to a
 * primitive with ~40 call sites rather than to this tab.
 *
 * `breakInside` matters: the middle group is a CSS-columns masonry, and a card
 * allowed to split across a column boundary loses its header.
 */
function IntegrationCard({
  icon: Icon,
  title,
  description,
  actions,
  children,
}: {
  icon: IconType
  title: string
  description: string
  /** Rendered in the title row, left of the icon — the About sidecar trigger. */
  actions?: ReactNode
  children: ReactNode
}) {
  return (
    <Card breakInside>
      <header className="mb-4 flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <Icon aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-(--accent-fg)" />
          <div>
            <h3 className="text-[15px] font-bold tracking-[-.02em] text-text">{title}</h3>
            <p className="mt-0.5 text-sm text-text-mute">{description}</p>
          </div>
        </div>
        {actions}
      </header>
      {children}
    </Card>
  )
}

/**
 * Settings > Integrations. A non-admin gets only their own widget keys: every
 * other card is an instance setting, admin-only on the server (LiveLink infra
 * since v2.28.0), so the admin view never mounts for them and loads nothing.
 */
export default function SettingsIntegrationsTab(): React.ReactElement {
  const canManageInstance = useCanManageInstance()
  if (!canManageInstance) {
    return (
      <div className="max-w-6xl mx-auto space-y-6">
        <WidgetKeysPanel />
      </div>
    )
  }
  return <IntegrationsAdminView />
}

function IntegrationsAdminView(): React.ReactElement {
  const { t } = useTranslation('settings')
  const [loading, setLoading] = useState(true)
  const { triggerSave, registerSaveHandler, unregisterSaveHandler } = useSettings()
  const [testing, setTesting] = useState(false)
  const [testingAutoRef, setTestingAutoRef] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null)
  // Which card's "About" help sidecar is open (null = closed).
  const [helpDrawer, setHelpDrawer] = useState<'carcomplaints' | 'livelink' | 'european_vin' | null>(null)

  // Bumped whenever something that can change the integrations strip closes,
  // so the card refetches instead of showing the state from before the edit.
  const [integrationsRefresh, setIntegrationsRefresh] = useState(0)
  const [addSourceOpen, setAddSourceOpen] = useState(false)
  const bumpStrip = useCallback(() => setIntegrationsRefresh((n) => n + 1), [])
  // Which LiveLink settings drawer is open: the gear's, or one tab's.
  const [settingsTarget, setSettingsTarget] = useState<SettingsTarget | null>(null)

  const [formData, setFormData] = useState({
    nhtsa_enabled: 'true',
    nhtsa_auto_check: 'true',
    nhtsa_recall_check_interval: '7',
    nhtsa_recalls_api_url: NHTSA_RECALLS_BASE_URL,
    european_vin_enabled: 'true',
    european_vin_api_key: '',
    carcomplaints_enabled: 'true',
    tomtom_api_key: '',
    tomtom_enabled: 'false',
    webhook_ingest_token: '',
    llm_receipt_parse_enabled: 'false',
    llm_garage_assistant_enabled: 'false',
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
        nhtsa_recalls_api_url: settingsMap['nhtsa_recalls_api_url'] || NHTSA_RECALLS_BASE_URL,
        european_vin_enabled: settingsMap['european_vin_enabled'] || 'true',
        european_vin_api_key: settingsMap['european_vin_api_key'] || '',
        carcomplaints_enabled: settingsMap['carcomplaints_enabled'] || 'true',
        tomtom_api_key: settingsMap['tomtom_api_key'] || '',
        tomtom_enabled: settingsMap['tomtom_enabled'] || 'false',
        webhook_ingest_token: settingsMap['webhook_ingest_token'] || '',
        llm_receipt_parse_enabled: settingsMap['llm_receipt_parse_enabled'] || 'false',
        llm_garage_assistant_enabled: settingsMap['llm_garage_assistant_enabled'] || 'false',
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

  useEffect(() => {
    loadSettings()
  }, [loadSettings])

  const handleSave = useCallback(async () => {
    await api.post('/settings/batch', {
      settings: {
        nhtsa_enabled: formData.nhtsa_enabled,
        nhtsa_auto_check: formData.nhtsa_auto_check,
        nhtsa_recall_check_interval: formData.nhtsa_recall_check_interval,
        nhtsa_recalls_api_url: formData.nhtsa_recalls_api_url,
        european_vin_enabled: formData.european_vin_enabled,
        european_vin_api_key: formData.european_vin_api_key,
        carcomplaints_enabled: formData.carcomplaints_enabled,
        tomtom_api_key: formData.tomtom_api_key,
        tomtom_enabled: formData.tomtom_enabled,
        webhook_ingest_token: formData.webhook_ingest_token,
        llm_receipt_parse_enabled: formData.llm_receipt_parse_enabled,
        llm_garage_assistant_enabled: formData.llm_garage_assistant_enabled,
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

  const handleTestAutoRef = async () => {
    setTestingAutoRef(true)
    setMessage(null)

    try {
      const response = await api.post('/vin/test-european', {
        api_key: formData.european_vin_api_key.trim() || undefined,
      })

      const { plan, remaining, limit } = response.data
      let successMsg = t('integrations.europeanVinTestSuccess')
      if (remaining !== undefined && limit !== undefined) {
        successMsg += ` (${t('integrations.europeanVinQuota')}: ${remaining}/${limit})`
      } else if (plan) {
        successMsg += ` (${plan})`
      }

      setMessage({ type: 'success', text: successMsg })
      setTimeout(() => setMessage(null), 5000)
    } catch (err: unknown) {
      const errMsg = getErrorMessage(err, t('integrations.europeanVinTestFailed'))
      setMessage({ type: 'error', text: errMsg })
    } finally {
      setTestingAutoRef(false)
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

      {/* LLM is full width: its three credential fields want a row, and a
          half-width column would stack them into a tower. */}
      <IntegrationCard
          icon={Sparkles}
          title={t('integrations.llmSection')}
          description={t('integrations.llmSectionDesc')}
        >
          <div className="space-y-4">
            <Toggle
              label={t('integrations.enableLlmReceipt')}
              checked={formData.llm_receipt_parse_enabled === 'true'}
              onChange={(next) =>
                setFormData({ ...formData, llm_receipt_parse_enabled: next ? 'true' : 'false' })
              }
            />
            {/* Wrapped like every other toggle-plus-description pair on this tab.
                Left as a bare sibling of `space-y-4`, the description took the
                container's 16px gap instead of its own 4px and had to be dragged
                back up with a negative margin. */}
            <div>
              <Toggle
                label={t('integrations.enableLlmAssistant')}
                checked={formData.llm_garage_assistant_enabled === 'true'}
                onChange={(next) =>
                  setFormData({ ...formData, llm_garage_assistant_enabled: next ? 'true' : 'false' })
                }
              />
              <p className="mt-1 ml-14 text-sm text-garage-text-muted">
                {t('integrations.enableLlmAssistantDesc')}
              </p>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label htmlFor="llm_base_url" className="block text-sm font-medium text-garage-text mb-2">
                  {t('integrations.llmBaseUrl')}
                </label>
                <input
                  type="url"
                  id="llm_base_url"
                  value={formData.llm_base_url}
                  disabled={
                    formData.llm_receipt_parse_enabled === 'false' &&
                    formData.llm_garage_assistant_enabled === 'false'
                  }
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
                  disabled={
                    formData.llm_receipt_parse_enabled === 'false' &&
                    formData.llm_garage_assistant_enabled === 'false'
                  }
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
                  disabled={
                    formData.llm_receipt_parse_enabled === 'false' &&
                    formData.llm_garage_assistant_enabled === 'false'
                  }
                  onChange={(e) => setFormData({ ...formData, llm_api_key: e.target.value })}
                  className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
                  autoComplete="off"
                />
              </div>
            </div>
            <p className="text-sm text-garage-text-muted">{t('integrations.llmHint')}</p>
          </div>
        </IntegrationCard>

      {/* The remaining cards flow as a masonry rather than sitting in a fixed
          2-col grid. The grid paired a ~530px NHTSA card
          against ~280px of stacked cards and left the rest of that row empty;
          columns let the short ones close the gap themselves. Source order is
          preserved, so the one-column mobile reading order still groups. */}
      <div className="columns-1 gap-6 lg:columns-2 [&>*]:mb-6">
        <IntegrationCard
          icon={Shield}
          title={t('integrations.nhtsa')}
          description={t('integrations.nhtsaDesc')}
        >

        <div className="space-y-6">
          {/* Enable NHTSA Integration */}
          <div>
            <Toggle
              label={t('integrations.enableNHTSA')}
              checked={formData.nhtsa_enabled === 'true'}
              onChange={(next) => setFormData({ ...formData, nhtsa_enabled: next ? 'true' : 'false' })}
            />
            <p className="mt-1 ml-14 text-sm text-garage-text-muted">
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
            <p className="mt-1 ml-14 text-sm text-garage-text-muted">
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
              placeholder={NHTSA_RECALLS_BASE_URL}
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
        </IntegrationCard>

        <IntegrationCard
          icon={Globe}
          title={t('integrations.europeanVin')}
          description={t('integrations.europeanVinDesc')}
          actions={
            <IconButton
              icon={HelpCircle}
              label={t('integrations.aboutEuropeanVin')}
              variant="surface"
              onClick={() => setHelpDrawer('european_vin')}
            />
          }
        >
          <div className="space-y-6">
            {/* Enable European VIN Integration */}
            <div>
              <Toggle
                label={t('integrations.enableEuropeanVin')}
                checked={formData.european_vin_enabled === 'true'}
                onChange={(next) => setFormData({ ...formData, european_vin_enabled: next ? 'true' : 'false' })}
              />
              <p className="mt-1 ml-14 text-sm text-garage-text-muted">
                {t('integrations.enableEuropeanVinDesc')}
              </p>
            </div>

            {/* API Key */}
            <div>
              <label htmlFor="european_vin_api_key" className="block text-sm font-medium text-garage-text mb-2">
                {t('integrations.europeanVinApiKey')}
              </label>
              <input
                type="password"
                id="european_vin_api_key"
                value={formData.european_vin_api_key}
                disabled={formData.european_vin_enabled === 'false'}
                onChange={(e) => setFormData({ ...formData, european_vin_api_key: e.target.value })}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50 font-mono text-sm"
                placeholder={t('integrations.europeanVinApiKeyPlaceholder')}
                autoComplete="off"
              />
              <p className="mt-1 text-sm text-garage-text-muted">
                {t('integrations.europeanVinApiKeyHint')}
              </p>
            </div>

            {/* Test Connection */}
            <div className="pt-4 border-t border-garage-border">
              <button
                type="button"
                onClick={handleTestAutoRef}
                disabled={
                  testingAutoRef ||
                  formData.european_vin_enabled === 'false' ||
                  !formData.european_vin_api_key.trim()
                }
                className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50"
              >
                <CheckCircle size={16} />
                {testingAutoRef ? t('integrations.testingConnection') : t('integrations.testEuropeanVin')}
              </button>
              <p className="mt-2 text-sm text-garage-text-muted">
                {t('integrations.testEuropeanVinDesc')}
              </p>
            </div>
          </div>
        </IntegrationCard>

        <IntegrationCard
          icon={Webhook}
          title={t('integrations.webhooks')}
          description={t('integrations.webhooksDesc')}
        >
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
        </IntegrationCard>

        <IntegrationCard
          icon={Plug}
          title={t('integrations.carComplaints')}
          description={t('integrations.carComplaintsDesc')}
          actions={
            <IconButton
              icon={HelpCircle}
              label={t('integrations.aboutCarComplaints')}
              variant="surface"
              onClick={() => setHelpDrawer('carcomplaints')}
            />
          }
        >

        <div className="space-y-6">
          {/* Enable CarComplaints Integration */}
          <div>
            <Toggle
              label={t('integrations.enableCarComplaints')}
              checked={formData.carcomplaints_enabled === 'true'}
              onChange={(next) => setFormData({ ...formData, carcomplaints_enabled: next ? 'true' : 'false' })}
            />
            <p className="mt-1 ml-14 text-sm text-garage-text-muted">
              {t('integrations.enableCarComplaintsDesc')}
            </p>
          </div>
        </div>
        </IntegrationCard>

        <IntegrationCard
          icon={Radio}
          title={t('integrations.livelink')}
          description={t('integrations.livelinkSourcesDesc')}
          actions={
            <div className="flex items-center gap-2">
              {/* LiveLink's global settings (master switch, retention,
                  alerts), which belong to no single source's drawer. */}
              <IconButton
                icon={Settings}
                label={t('integrations.livelinkGeneral')}
                variant="surface"
                onClick={() => setSettingsTarget({ type: 'general' })}
              />
              <IconButton
                icon={HelpCircle}
                label={t('integrations.aboutLiveLink')}
                variant="surface"
                onClick={() => setHelpDrawer('livelink')}
              />
            </div>
          }
        >

          {/* Admin-only like this whole view: /integrations is an admin
              endpoint. */}
          <LiveLinkIntegrationsCard
            refreshKey={integrationsRefresh}
            onOpenSettings={(tab) => setSettingsTarget({ type: 'tab', tab })}
            onAddSource={() => setAddSourceOpen(true)}
          />
        </IntegrationCard>
      </div>

      <AddSourceDrawer
        open={addSourceOpen}
        onClose={() => setAddSourceOpen(false)}
        onCreated={bumpStrip}
      />

      <LiveLinkSettingsDrawers
        target={settingsTarget}
        onClose={() => {
          setSettingsTarget(null)
          // Closing is also a refresh point: whatever the drawer changed
          // may have changed a tab's status.
          bumpStrip()
        }}
        onChanged={bumpStrip}
      />

      {/* About / help sidecar — opened from each card's upper-right help button. */}
      <Drawer
        open={helpDrawer !== null}
        onClose={() => setHelpDrawer(null)}
        title={
          helpDrawer === 'livelink'
            ? t('integrations.aboutLiveLink')
            : helpDrawer === 'european_vin'
            ? t('integrations.aboutEuropeanVin')
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
        {helpDrawer === 'european_vin' && (
          <div className="space-y-4">
            <p className="text-sm text-garage-text-muted">
              {t('integrations.europeanVinHelpIntro')}
            </p>
            <div className="p-3 bg-garage-bg/50 border border-garage-border rounded-lg">
              <h4 className="text-sm font-semibold text-garage-text mb-1">
                {t('integrations.europeanVinHelpFreeTierTitle')}
              </h4>
              <p className="text-xs text-garage-text-muted">
                {t('integrations.europeanVinHelpFreeTierDesc')}
              </p>
            </div>
            <div className="space-y-2 text-sm text-garage-text-muted">
              <p>
                <strong>1.</strong> {t('integrations.europeanVinStep1')}{' '}
                <a
                  href="https://www.autoref.eu"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary hover:underline font-medium inline-flex items-center gap-1"
                >
                  autoref.eu
                </a>
              </p>
              <p>
                <strong>2.</strong> {t('integrations.europeanVinStep2')}
              </p>
              <p>
                <strong>3.</strong> {t('integrations.europeanVinStep3')}
              </p>
            </div>
            <p className="text-xs text-garage-text-muted pt-2 border-t border-garage-border">
              {t('integrations.europeanVinHelpNote')}
            </p>
          </div>
        )}
      </Drawer>
    </div>
  )
}
