import { useState, useEffect, useCallback, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { CheckCircle, AlertCircle, Plug, Shield, Radio, HelpCircle, Webhook, Sparkles, Settings, Fuel } from 'lucide-react'
import { useSettings } from '@/contexts/SettingsContext'
import { useCanManageInstance } from '@/hooks/useCanManageInstance'
import api from '@/services/api'
import { isSettingOn } from '@/utils/settingSwitch'
import WidgetKeysPanel from '../settings/WidgetKeysPanel'
import { Card, IconButton, Select, Toggle, Drawer } from '../ui'
import type { IconType } from '../ui/types'
import type { components } from '@/types/api.generated'
import AddSourceDrawer from '@/components/livelink/AddSourceDrawer'
import LiveLinkIntegrationsCard from '@/components/livelink/LiveLinkIntegrationsCard'
import LiveLinkSettingsDrawers, { type SettingsTarget } from '@/components/livelink/settings/LiveLinkSettingsDrawers'

// Sample VIN for testing NHTSA API connection
const TEST_VIN = '1HGCM82633A123456'
// The base, not the endpoint: the backend adds /recallsByVehicle itself, so the
// full endpoint got saved and fetched with the path twice. Same as the
// backend's DEFAULT_RECALLS_API_URL.
const NHTSA_RECALLS_BASE_URL = 'https://api.nhtsa.gov/recalls'
// The French product recall register's records endpoint (#211). Same as the
// backend's DEFAULT_API_URL; the setting only accepts https on this host.
const RAPPELCONSO_API_URL =
  'https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/rappelconso-v2-gtin-espaces/records'
const FUEL_PRICES_API_URL =
  'https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/prix-des-carburants-en-france-flux-instantane-v2/records'

type SettingRecord = {
  key: string
  value: string | null
}

type SettingsResponse = {
  settings: SettingRecord[]
}

type LlmTestResult = components['schemas']['LlmTestResponse']

// The base URL each preset fills in. `custom` fills nothing. The vocabulary
// is the backend's `LLM_PROVIDER_PRESETS`; a value outside it is a 422.
const LLM_PRESET_BASE_URLS: Record<string, string | undefined> = {
  custom: undefined,
  openrouter: 'https://openrouter.ai/api/v1',
  ollama: 'http://127.0.0.1:11434/v1',
  openai: 'https://api.openai.com/v1',
}

// Example model names shown as placeholders only; never written to the form.
const LLM_PRESET_PLACEHOLDERS: Record<string, { model: string; vision: string }> = {
  custom: { model: 'llama3.2', vision: 'llava' },
  openrouter: { model: 'vendor/model', vision: 'vendor/vision-model' },
  ollama: { model: 'llama3.2', vision: 'llava' },
  openai: { model: 'gpt-4o-mini', vision: 'gpt-4o' },
}

const AI_FEATURES_DOC_URL = 'https://github.com/homelabforge/mygarage/blob/main/docs/ai-features.md'

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
  const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null)
  // Which card's "About" help sidecar is open (null = closed).
  const [helpDrawer, setHelpDrawer] = useState<'carcomplaints' | 'livelink' | null>(null)

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
    carcomplaints_enabled: 'true',
    tomtom_api_key: '',
    tomtom_enabled: 'false',
    webhook_ingest_token: '',
    llm_receipt_parse_enabled: 'false',
    llm_garage_assistant_enabled: 'false',
    llm_base_url: 'http://127.0.0.1:11434/v1',
    llm_model: 'llama3.2',
    llm_api_key: '',
    llm_document_reading_enabled: 'false',
    llm_vision_model: '',
    llm_provider_preset: 'custom',
    rappelconso_enabled: 'true',
    rappelconso_api_url: RAPPELCONSO_API_URL,
    fuel_prices_enabled: 'true',
    fuel_prices_api_url: FUEL_PRICES_API_URL,
  })
  const [loadedFormData, setLoadedFormData] = useState<typeof formData | null>(null)
  const [llmTesting, setLlmTesting] = useState(false)

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
        carcomplaints_enabled: settingsMap['carcomplaints_enabled'] || 'true',
        tomtom_api_key: settingsMap['tomtom_api_key'] || '',
        tomtom_enabled: settingsMap['tomtom_enabled'] || 'false',
        webhook_ingest_token: settingsMap['webhook_ingest_token'] || '',
        llm_receipt_parse_enabled: settingsMap['llm_receipt_parse_enabled'] || 'false',
        llm_garage_assistant_enabled: settingsMap['llm_garage_assistant_enabled'] || 'false',
        llm_base_url: settingsMap['llm_base_url'] || 'http://127.0.0.1:11434/v1',
        llm_model: settingsMap['llm_model'] || 'llama3.2',
        llm_api_key: settingsMap['llm_api_key'] || '',
        llm_document_reading_enabled: settingsMap['llm_document_reading_enabled'] || 'false',
        llm_vision_model: settingsMap['llm_vision_model'] || '',
        llm_provider_preset: settingsMap['llm_provider_preset'] || 'custom',
        rappelconso_enabled: settingsMap['rappelconso_enabled'] || 'true',
        rappelconso_api_url: settingsMap['rappelconso_api_url'] || RAPPELCONSO_API_URL,
        fuel_prices_enabled: settingsMap['fuel_prices_enabled'] || 'true',
        fuel_prices_api_url: settingsMap['fuel_prices_api_url'] || FUEL_PRICES_API_URL,
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
        carcomplaints_enabled: formData.carcomplaints_enabled,
        tomtom_api_key: formData.tomtom_api_key,
        tomtom_enabled: formData.tomtom_enabled,
        webhook_ingest_token: formData.webhook_ingest_token,
        llm_receipt_parse_enabled: formData.llm_receipt_parse_enabled,
        llm_garage_assistant_enabled: formData.llm_garage_assistant_enabled,
        llm_base_url: formData.llm_base_url,
        llm_model: formData.llm_model,
        llm_api_key: formData.llm_api_key,
        llm_document_reading_enabled: formData.llm_document_reading_enabled,
        llm_vision_model: formData.llm_vision_model,
        llm_provider_preset: formData.llm_provider_preset,
        rappelconso_enabled: formData.rappelconso_enabled,
        rappelconso_api_url: formData.rappelconso_api_url,
        fuel_prices_enabled: formData.fuel_prices_enabled,
        fuel_prices_api_url: formData.fuel_prices_api_url,
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

  // The server tests what is STORED, so the form is saved first: the button
  // is pressed right after typing a key or a model, before the debounced
  // auto-save has run. A 502 from the endpoint comes back as a 200 with
  // `valid: false` and the endpoint's own sentence; only a transport failure
  // to our own backend lands in the catch.
  const handleTestLlm = async () => {
    setLlmTesting(true)
    setMessage(null)
    try {
      await handleSave()
      const { data } = await api.post<LlmTestResult>('/settings/test/llm')
      if (data.valid) {
        setMessage({
          type: 'success',
          text: data.vision_ok ? t('integrations.llmTestVisionOk') : t('integrations.llmTestOk'),
        })
      } else {
        setMessage({
          type: 'error',
          text: t('integrations.llmTestFailed', { message: data.message }),
        })
      }
    } catch {
      setMessage({ type: 'error', text: t('integrations.llmTestFailed', { message: '' }) })
    } finally {
      setLlmTesting(false)
    }
  }

  // A preset fills the base URL in; the model names stay the person's own
  // choice (a preset that typed a model would pick one that costs money, or
  // one that is not pulled on their Ollama).
  const applyPreset = (preset: string) => {
    const baseUrl = LLM_PRESET_BASE_URLS[preset]
    setFormData({
      ...formData,
      llm_provider_preset: preset,
      ...(baseUrl ? { llm_base_url: baseUrl } : {}),
    })
  }

  const llmFieldsDisabled =
    !isSettingOn(formData.llm_receipt_parse_enabled, false) &&
    !isSettingOn(formData.llm_garage_assistant_enabled, false) &&
    !isSettingOn(formData.llm_document_reading_enabled, false)
  const llmPlaceholders = LLM_PRESET_PLACEHOLDERS[formData.llm_provider_preset] ?? LLM_PRESET_PLACEHOLDERS.custom

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
              checked={isSettingOn(formData.llm_receipt_parse_enabled, false)}
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
                checked={isSettingOn(formData.llm_garage_assistant_enabled, false)}
                onChange={(next) =>
                  setFormData({ ...formData, llm_garage_assistant_enabled: next ? 'true' : 'false' })
                }
              />
              <p className="mt-1 ml-14 text-sm text-garage-text-muted">
                {t('integrations.enableLlmAssistantDesc')}
              </p>
            </div>
            {/* Document reading sends IMAGES of what people upload to the
                endpoint, so its description says so in full: it is the one
                toggle here with a privacy consequence (#211). */}
            <div>
              <Toggle
                label={t('integrations.enableLlmDocuments')}
                checked={isSettingOn(formData.llm_document_reading_enabled, false)}
                onChange={(next) =>
                  setFormData({ ...formData, llm_document_reading_enabled: next ? 'true' : 'false' })
                }
              />
              <p className="mt-1 ml-14 text-sm text-garage-text-muted">
                {t('integrations.enableLlmDocumentsDesc')}
              </p>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div>
                <label htmlFor="llm_provider_preset" className="block text-sm font-medium text-garage-text mb-2">
                  {t('integrations.llmPreset')}
                </label>
                <Select
                  id="llm_provider_preset"
                  value={formData.llm_provider_preset}
                  disabled={llmFieldsDisabled}
                  onChange={(e) => applyPreset(e.target.value)}
                  options={[
                    { value: 'custom', label: t('integrations.llmPresetCustom') },
                    { value: 'openrouter', label: t('integrations.llmPresetOpenRouter') },
                    { value: 'ollama', label: t('integrations.llmPresetOllama') },
                    { value: 'openai', label: t('integrations.llmPresetOpenAI') },
                  ]}
                />
              </div>
              <div>
                <label htmlFor="llm_base_url" className="block text-sm font-medium text-garage-text mb-2">
                  {t('integrations.llmBaseUrl')}
                </label>
                <input
                  type="url"
                  id="llm_base_url"
                  value={formData.llm_base_url}
                  disabled={llmFieldsDisabled}
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
                  disabled={llmFieldsDisabled}
                  onChange={(e) => setFormData({ ...formData, llm_model: e.target.value })}
                  className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
                  placeholder={llmPlaceholders.model}
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
                  disabled={llmFieldsDisabled}
                  onChange={(e) => setFormData({ ...formData, llm_api_key: e.target.value })}
                  className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
                  autoComplete="off"
                />
              </div>
            </div>
            {isSettingOn(formData.llm_document_reading_enabled, false) && (
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="md:col-span-2">
                  <label htmlFor="llm_vision_model" className="block text-sm font-medium text-garage-text mb-2">
                    {t('integrations.llmVisionModel')}
                  </label>
                  <input
                    type="text"
                    id="llm_vision_model"
                    value={formData.llm_vision_model}
                    onChange={(e) => setFormData({ ...formData, llm_vision_model: e.target.value })}
                    className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
                    placeholder={llmPlaceholders.vision}
                  />
                  <p className="mt-1 text-sm text-garage-text-muted">{t('integrations.llmVisionModelHint')}</p>
                </div>
              </div>
            )}
            <p className="text-sm text-garage-text-muted">
              {t('integrations.llmHint')}{' '}
              <a
                href={AI_FEATURES_DOC_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="text-(--accent-fg) underline-offset-2 hover:underline"
              >
                {t('integrations.llmDocsLink')}
              </a>
            </p>
            <div className="pt-4 border-t border-garage-border">
              <button
                type="button"
                onClick={handleTestLlm}
                disabled={llmTesting || llmFieldsDisabled}
                className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50"
              >
                <CheckCircle size={16} />
                {llmTesting ? t('integrations.testingConnection') : t('integrations.llmTest')}
              </button>
            </div>
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
              checked={isSettingOn(formData.nhtsa_enabled, true)}
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
              checked={isSettingOn(formData.nhtsa_auto_check, true)}
              disabled={!isSettingOn(formData.nhtsa_enabled, true)}
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
              disabled={!isSettingOn(formData.nhtsa_enabled, true) || !isSettingOn(formData.nhtsa_auto_check, true)}
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
              disabled={!isSettingOn(formData.nhtsa_enabled, true)}
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
              disabled={testing || !isSettingOn(formData.nhtsa_enabled, true)}
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

        {/* RappelConso (#211): the French recall register, for vehicles
            registered in France. One switch and the endpoint. */}
        <IntegrationCard
          icon={Shield}
          title={t('integrations.rappelconso')}
          description={t('integrations.rappelconsoDesc')}
        >
          <div className="space-y-6">
            <div>
              <Toggle
                label={t('integrations.enableRappelConso')}
                checked={isSettingOn(formData.rappelconso_enabled, true)}
                onChange={(next) => setFormData({ ...formData, rappelconso_enabled: next ? 'true' : 'false' })}
              />
              <p className="mt-1 ml-14 text-sm text-garage-text-muted">
                {t('integrations.enableRappelConsoDesc')}
              </p>
            </div>
            <div>
              <label htmlFor="rappelconso_api_url" className="block text-sm font-medium text-garage-text mb-2">
                {t('integrations.rappelconsoApiUrl')}
              </label>
              <input
                type="url"
                id="rappelconso_api_url"
                value={formData.rappelconso_api_url}
                disabled={!isSettingOn(formData.rappelconso_enabled, true)}
                onChange={(e) => setFormData({ ...formData, rappelconso_api_url: e.target.value })}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50 font-mono text-sm"
                placeholder={RAPPELCONSO_API_URL}
              />
              <p className="text-xs text-garage-text-muted mt-1">{t('integrations.rappelconsoApiUrlDesc')}</p>
            </div>
          </div>
        </IntegrationCard>

        {/* Fuel prices (#211): the French open-data feed every station
            reports to, shown on the fill-up form for a saved station. */}
        <IntegrationCard
          icon={Fuel}
          title={t('integrations.fuelPrices')}
          description={t('integrations.fuelPricesDesc')}
        >
          <div className="space-y-6">
            <div>
              <Toggle
                label={t('integrations.enableFuelPrices')}
                checked={formData.fuel_prices_enabled === 'true'}
                onChange={(next) => setFormData({ ...formData, fuel_prices_enabled: next ? 'true' : 'false' })}
              />
              <p className="mt-1 ml-14 text-sm text-garage-text-muted">
                {t('integrations.enableFuelPricesDesc')}
              </p>
            </div>
            <div>
              <label htmlFor="fuel_prices_api_url" className="block text-sm font-medium text-garage-text mb-2">
                {t('integrations.fuelPricesApiUrl')}
              </label>
              <input
                type="url"
                id="fuel_prices_api_url"
                value={formData.fuel_prices_api_url}
                disabled={formData.fuel_prices_enabled === 'false'}
                onChange={(e) => setFormData({ ...formData, fuel_prices_api_url: e.target.value })}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50 font-mono text-sm"
                placeholder={FUEL_PRICES_API_URL}
              />
              <p className="text-xs text-garage-text-muted mt-1">{t('integrations.fuelPricesApiUrlDesc')}</p>
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
              checked={isSettingOn(formData.carcomplaints_enabled, true)}
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
