import { useState, useCallback, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Server, CheckCircle, AlertCircle, Info, Shield, Users, AlertTriangle, Key, Wrench, Fuel, Bell, FileText, StickyNote, Camera, Sun, Moon, Ruler, Archive, Smartphone, Globe, DollarSign } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { useSettings } from '@/contexts/SettingsContext'
import { useTheme } from '@/contexts/ThemeContext'
import type { DashboardResponse } from '@/types/dashboard'
import api from '@/services/api'
import { toast } from 'sonner'
import { formatCurrency } from '@/utils/formatUtils'
import { SUPPORTED_LANGUAGES, SUPPORTED_CURRENCIES, languageToLocale } from '@/constants/i18n'
import OIDCModal from '@/components/modals/OIDCModal'
import FamilyManagementModal from '@/components/modals/FamilyManagementModal'
import ArchivedVehiclesList from '@/components/ArchivedVehiclesList'

type RawSetting = {
  key: string
  value?: string | null
}

export default function SettingsSystemTab() {
  const { t } = useTranslation('settings')
  const { i18n } = useTranslation()
  const { isAuthenticated, isAdmin, user: currentUser, refreshUser } = useAuth()
  const { triggerSave, registerSaveHandler, unregisterSaveHandler } = useSettings()
  const { theme, setTheme } = useTheme()
  const [formData, setFormData] = useState({
    timezone: 'UTC',
    debug: 'false',
    auth_mode: 'none', // local, none, oidc
    oidc_enabled: 'false',
    oidc_provider_name: '',
    oidc_issuer_url: '',
    oidc_client_id: '',
    oidc_client_secret: '',
    oidc_redirect_uri: '',
    oidc_scopes: 'openid profile email',
    oidc_auto_create_users: 'true',
    oidc_admin_group: '',
    oidc_username_claim: 'preferred_username',
    oidc_email_claim: 'email',
    oidc_full_name_claim: 'name',
  })
  const [loadedFormData, setLoadedFormData] = useState<typeof formData | null>(null)
  const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null)
  const [authenticatorDetected, setAuthenticatorDetected] = useState<boolean | null>(null)
  const [authEverEnabled, setAuthEverEnabled] = useState(false)
  const [dashboardStats, setDashboardStats] = useState<DashboardResponse | null>(null)

  // Modal state
  const [showFamilyManagement, setShowFamilyManagement] = useState(false)
  const [showOIDCModal, setShowOIDCModal] = useState(false)

  // Unit preference state
  const [unitPreference, setUnitPreference] = useState<'imperial' | 'metric'>('imperial')
  const [showBothUnits, setShowBothUnits] = useState(false)
  const [unitPreferenceSaving, setUnitPreferenceSaving] = useState(false)

  // Mobile experience state
  const [mobileQuickEntry, setMobileQuickEntry] = useState(true)
  const [mobileQuickEntrySaving, setMobileQuickEntrySaving] = useState(false)

  // Language & currency state
  const [selectedLanguage, setSelectedLanguage] = useState('en')
  const [languageSaving, setLanguageSaving] = useState(false)
  const [selectedCurrency, setSelectedCurrency] = useState('USD')
  const [currencySaving, setCurrencySaving] = useState(false)
  const [showCurrencyConfirm, setShowCurrencyConfirm] = useState(false)
  const [pendingCurrency, setPendingCurrency] = useState<string | null>(null)

  // Common timezones
  const timezones = [
    'UTC',
    'America/New_York',
    'America/Chicago',
    'America/Denver',
    'America/Los_Angeles',
    'America/Phoenix',
    'America/Anchorage',
    'America/Juneau',
    'Pacific/Honolulu',
    'Europe/London',
    'Europe/Paris',
    'Europe/Berlin',
    'Europe/Rome',
    'Europe/Madrid',
    'Asia/Tokyo',
    'Asia/Shanghai',
    'Asia/Dubai',
    'Australia/Sydney',
    'Australia/Melbourne',
    'Pacific/Auckland',
  ]

  // Load settings
  const loadSettings = useCallback(async () => {
    try {
      const response = await api.get('/settings')
      const data = response.data

      const settingsMap: Record<string, string> = {}
      data.settings.forEach((s: RawSetting) => {
        settingsMap[s.key] = s.value || ''
      })

      const newFormData = {
        timezone: settingsMap.timezone || 'UTC',
        debug: settingsMap.debug || 'false',
        auth_mode: settingsMap.auth_mode || 'none',
        oidc_enabled: settingsMap.oidc_enabled || 'false',
        oidc_provider_name: settingsMap.oidc_provider_name || '',
        oidc_issuer_url: settingsMap.oidc_issuer_url || '',
        oidc_client_id: settingsMap.oidc_client_id || '',
        oidc_client_secret: settingsMap.oidc_client_secret || '',
        oidc_redirect_uri: settingsMap.oidc_redirect_uri || '',
        oidc_scopes: settingsMap.oidc_scopes || 'openid profile email',
        oidc_auto_create_users: settingsMap.oidc_auto_create_users || 'true',
        oidc_admin_group: settingsMap.oidc_admin_group || '',
        oidc_username_claim: settingsMap.oidc_username_claim || 'preferred_username',
        oidc_email_claim: settingsMap.oidc_email_claim || 'email',
        oidc_full_name_claim: settingsMap.oidc_full_name_claim || 'name',
      }
      setFormData(newFormData)
      setLoadedFormData(newFormData)

      // Check user count to determine if auth has ever been enabled
      try {
        const countResponse = await api.get('/auth/users/count')
        const countData = countResponse.data
        setAuthEverEnabled(countData.count > 0)
      } catch {
        setAuthEverEnabled(false)
      }
    } catch {
      setMessage({ type: 'error', text: 'Failed to load system settings' })
    }
  }, [])

  useEffect(() => {
    void loadSettings()
  }, [loadSettings])

  // Load user's preferences
  useEffect(() => {
    if (currentUser) {
      setUnitPreference(currentUser.unit_preference || 'imperial')
      setShowBothUnits(currentUser.show_both_units || false)
      setMobileQuickEntry(currentUser.mobile_quick_entry_enabled ?? true)
      setSelectedLanguage(currentUser.language || 'en')
      setSelectedCurrency(currentUser.currency_code || 'USD')
    } else {
      const storedSystem = localStorage.getItem('unit_preference') as 'imperial' | 'metric' | null
      const storedShowBoth = localStorage.getItem('show_both_units') === 'true'
      setUnitPreference(storedSystem || 'imperial')
      setShowBothUnits(storedShowBoth)
      setSelectedLanguage(localStorage.getItem('i18nextLng') || 'en')
      setSelectedCurrency(localStorage.getItem('currency_code') || 'USD')
    }
  }, [currentUser])

  // Load dashboard stats
  useEffect(() => {
    const loadDashboardStats = async () => {
      try {
        const response = await api.get('/dashboard')
        setDashboardStats(response.data)
      } catch {
        // Removed console.error
      }
    }
    loadDashboardStats()
  }, [])

  // Detect reverse proxy authenticators
  useEffect(() => {
    const detectAuthenticator = async () => {
      try {
        const response = await api.get('/health')
        setAuthenticatorDetected(response.data.authenticator_detected || false)
      } catch {
        setAuthenticatorDetected(false)
      }
    }

    detectAuthenticator()
  }, [])

  // Save settings
  const handleSave = useCallback(async () => {
    await api.post('/settings/batch', { settings: formData })

    const restartRequired = formData.debug !== 'false'
    if (restartRequired) {
      setMessage({
        type: 'success',
        text: '⚠️ Restart the application for debug mode changes to take effect.'
      })
      setTimeout(() => setMessage(null), 5000)
    }
  }, [formData])

  // Handle unit preference change
  const handleUnitPreferenceChange = async (system: 'imperial' | 'metric') => {
    setUnitPreferenceSaving(true)
    setUnitPreference(system)

    try {
      if (isAuthenticated) {
        // Save to user profile if authenticated
        await api.put('/auth/me', {
          unit_preference: system,
        })
        await refreshUser()
      } else {
        // Save to localStorage if not authenticated
        localStorage.setItem('unit_preference', system)
      }

      toast.success('Unit preference saved!')
      // Force a re-render to update displays
      window.dispatchEvent(new Event('storage'))
    } catch {
      toast.error('Failed to save unit preference')
      // Revert on error
      if (isAuthenticated) {
        setUnitPreference(currentUser?.unit_preference || 'imperial')
      } else {
        const stored = localStorage.getItem('unit_preference') as 'imperial' | 'metric' | null
        setUnitPreference(stored || 'imperial')
      }
    } finally {
      setUnitPreferenceSaving(false)
    }
  }

  const handleShowBothUnitsChange = async (showBoth: boolean) => {
    setUnitPreferenceSaving(true)
    setShowBothUnits(showBoth)

    try {
      if (isAuthenticated) {
        // Save to user profile if authenticated
        await api.put('/auth/me', {
          show_both_units: showBoth,
        })
        await refreshUser()
      } else {
        // Save to localStorage if not authenticated
        localStorage.setItem('show_both_units', showBoth.toString())
      }

      toast.success('Display preference saved!')
      // Force a re-render to update displays
      window.dispatchEvent(new Event('storage'))
    } catch {
      toast.error('Failed to save display preference')
      // Revert on error
      if (isAuthenticated) {
        setShowBothUnits(currentUser?.show_both_units || false)
      } else {
        const stored = localStorage.getItem('show_both_units') === 'true'
        setShowBothUnits(stored)
      }
    } finally {
      setUnitPreferenceSaving(false)
    }
  }

  const handleMobileQuickEntryChange = async (enabled: boolean) => {
    setMobileQuickEntrySaving(true)
    setMobileQuickEntry(enabled)

    try {
      await api.put('/auth/me', { mobile_quick_entry_enabled: enabled })
      await refreshUser()
      toast.success(t('preferences.mobileSaved'))
    } catch {
      toast.error(t('preferences.mobileError'))
      setMobileQuickEntry(currentUser?.mobile_quick_entry_enabled ?? true)
    } finally {
      setMobileQuickEntrySaving(false)
    }
  }

  // Handle language change
  const handleLanguageChange = async (lang: string) => {
    setLanguageSaving(true)
    const prevLang = selectedLanguage
    setSelectedLanguage(lang)

    try {
      // Change i18next language immediately for instant feedback
      await i18n.changeLanguage(lang)

      if (isAuthenticated) {
        await api.put('/auth/me', { language: lang })
        await refreshUser()
      } else {
        localStorage.setItem('i18nextLng', lang)
      }

      toast.success(t('language.saved'))
    } catch {
      toast.error(t('language.error'))
      setSelectedLanguage(prevLang)
      await i18n.changeLanguage(prevLang)
    } finally {
      setLanguageSaving(false)
    }
  }

  // Handle currency change — show confirmation first
  const handleCurrencyRequest = (code: string) => {
    if (code === selectedCurrency) return
    setPendingCurrency(code)
    setShowCurrencyConfirm(true)
  }

  const handleCurrencyConfirm = async () => {
    if (!pendingCurrency) return
    setShowCurrencyConfirm(false)
    setCurrencySaving(true)
    const prevCurrency = selectedCurrency
    setSelectedCurrency(pendingCurrency)

    try {
      if (isAuthenticated) {
        await api.put('/auth/me', { currency_code: pendingCurrency })
        await refreshUser()
      } else {
        localStorage.setItem('currency_code', pendingCurrency)
      }

      toast.success(t('currency.saved'))
    } catch {
      toast.error(t('currency.error'))
      setSelectedCurrency(prevCurrency)
    } finally {
      setCurrencySaving(false)
      setPendingCurrency(null)
    }
  }

  // Register save handler
  useEffect(() => {
    registerSaveHandler('system', handleSave)
    return () => unregisterSaveHandler('system')
  }, [handleSave, registerSaveHandler, unregisterSaveHandler])

  // Auto-save when form data changes (after initial load)
  useEffect(() => {
    if (!loadedFormData) return // Nothing loaded yet

    if (JSON.stringify(formData) !== JSON.stringify(loadedFormData)) {
      triggerSave()
    }
  }, [formData, loadedFormData, triggerSave])

  return (
    <div className="space-y-6">
      {/* Garage-wide Statistics */}
      {dashboardStats && dashboardStats.total_vehicles > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          <StatCard
            icon={<Wrench className="w-5 h-5" />}
            label="Service Records"
            value={dashboardStats.total_service_records}
            color="text-primary"
          />
          <StatCard
            icon={<Fuel className="w-5 h-5" />}
            label="Fuel Records"
            value={dashboardStats.total_fuel_records}
            color="text-primary"
          />
          <StatCard
            icon={<Bell className="w-5 h-5" />}
            label="Maintenance Items"
            value={dashboardStats.total_maintenance_items}
            color="text-warning"
          />
          <StatCard
            icon={<FileText className="w-5 h-5" />}
            label="Documents"
            value={dashboardStats.total_documents}
            color="text-primary"
          />
          <StatCard
            icon={<StickyNote className="w-5 h-5" />}
            label="Notes"
            value={dashboardStats.total_notes}
            color="text-primary"
          />
          <StatCard
            icon={<Camera className="w-5 h-5" />}
            label="Photos"
            value={dashboardStats.total_photos}
            color="text-primary"
          />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Left Column */}
      <div className="space-y-6">
      {/* System Configuration Section */}
      <div className="bg-garage-surface rounded-lg border border-garage-border p-6 space-y-6">
        {/* Header */}
        <div className="flex items-start gap-3">
          <Server className="w-6 h-6 text-primary mt-1" />
          <div className="flex-1">
            <h2 className="text-xl font-semibold text-garage-text mb-2">
              System Configuration
            </h2>
            <p className="text-sm text-garage-text-muted">
              Configure core system settings like timezone and debug mode.
            </p>
          </div>
        </div>

        {/* Timezone Setting */}
        <div>
          <label htmlFor="timezone" className="block text-sm font-medium text-garage-text mb-2">
            Timezone
          </label>
          <select
            id="timezone"
            value={formData.timezone}
            onChange={(e) => setFormData({ ...formData, timezone: e.target.value })}
            className="w-full md:w-96 px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
          >
            {timezones.map((tz) => (
              <option key={tz} value={tz}>{tz}</option>
            ))}
          </select>
          <p className="mt-2 text-sm text-garage-text-muted">
            Affects log timestamps, scheduled tasks, and date displays throughout the application.
          </p>
        </div>

        {/* Debug Mode Setting */}
        <div>
          <div className="flex items-center gap-3 mb-2">
            <label htmlFor="debug" className="text-sm font-medium text-garage-text">
              Debug Mode
            </label>
            <div className="relative group">
              <Info className="w-4 h-4 text-garage-text-muted cursor-help" />
              <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-2 bg-gray-900 text-white text-xs rounded-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-10">
                Requires application restart
              </div>
            </div>
          </div>
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              id="debug"
              type="checkbox"
              checked={formData.debug === 'true'}
              onChange={(e) => setFormData({ ...formData, debug: e.target.checked ? 'true' : 'false' })}
              className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2"
            />
            <span className="text-sm text-garage-text">
              Enable verbose logging and detailed error messages
            </span>
          </label>
          <p className="mt-2 ml-7 text-sm text-garage-text-muted">
            ⚠️ Requires application restart to take effect. Only enable for troubleshooting.
          </p>
        </div>

        {/* Theme Setting */}
        <div>
          <label className="block text-sm font-medium text-garage-text mb-3">
            Theme
          </label>
          <div className="flex gap-3">
            <button
              onClick={() => setTheme('dark')}
              className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-lg border-2 transition-all ${
                theme === 'dark'
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-garage-border bg-garage-bg text-garage-text hover:border-garage-border-light'
              }`}
            >
              <Moon className="w-5 h-5" />
              <span className="font-medium">Dark</span>
            </button>
            <button
              onClick={() => setTheme('light')}
              className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-lg border-2 transition-all ${
                theme === 'light'
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-garage-border bg-garage-bg text-garage-text hover:border-garage-border-light'
              }`}
            >
              <Sun className="w-5 h-5" />
              <span className="font-medium">Light</span>
            </button>
          </div>
          <p className="mt-2 text-sm text-garage-text-muted">
            Choose between light and dark theme. Your preference is saved automatically.
          </p>
        </div>

        {/* Unit System Setting */}
        <div>
          <label className="block text-sm font-medium text-garage-text mb-3">
            Unit System
          </label>
          <div className="flex gap-3">
            <button
              onClick={() => handleUnitPreferenceChange('imperial')}
              disabled={unitPreferenceSaving}
              className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-lg border-2 transition-all ${
                unitPreference === 'imperial'
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-garage-border bg-garage-bg text-garage-text hover:border-garage-border-light'
              } ${unitPreferenceSaving ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              <Ruler className="w-5 h-5" />
              <span className="font-medium">Imperial</span>
            </button>
            <button
              onClick={() => handleUnitPreferenceChange('metric')}
              disabled={unitPreferenceSaving}
              className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-lg border-2 transition-all ${
                unitPreference === 'metric'
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-garage-border bg-garage-bg text-garage-text hover:border-garage-border-light'
              } ${unitPreferenceSaving ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              <Ruler className="w-5 h-5" />
              <span className="font-medium">Metric</span>
            </button>
          </div>
          <p className="mt-2 text-sm text-garage-text-muted">
            {unitPreference === 'imperial'
              ? 'Using imperial units: gallons, miles, MPG, °F, PSI, lbs, lb-ft'
              : 'Using metric units: liters, kilometers, L/100km, °C, bar, kg, Nm'
            }
          </p>

          {/* Show Both Units Checkbox */}
          <div className="mt-4">
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={showBothUnits}
                onChange={(e) => handleShowBothUnitsChange(e.target.checked)}
                disabled={unitPreferenceSaving}
                className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2"
              />
              <span className="text-sm text-garage-text">
                Show both units
              </span>
            </label>
            <p className="mt-1 ml-7 text-sm text-garage-text-muted">
              Display values in both imperial and metric (e.g., "25 MPG (9.4 L/100km)")
            </p>
          </div>
        </div>

        {/* Language Setting */}
        <div>
          <label className="block text-sm font-medium text-garage-text mb-3">
            <div className="flex items-center gap-2">
              <Globe className="w-4 h-4" />
              {t('language.label')}
            </div>
          </label>
          <select
            value={selectedLanguage}
            onChange={(e) => handleLanguageChange(e.target.value)}
            disabled={languageSaving}
            className={`w-full md:w-96 px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary ${languageSaving ? 'opacity-50 cursor-not-allowed' : ''}`}
          >
            {SUPPORTED_LANGUAGES.map((lang) => (
              <option key={lang.code} value={lang.code}>
                {lang.nativeName} ({lang.name})
              </option>
            ))}
          </select>
          <p className="mt-2 text-sm text-garage-text-muted">
            {t('language.description')}
          </p>
        </div>

        {/* Currency Setting */}
        <div>
          <label className="block text-sm font-medium text-garage-text mb-3">
            <div className="flex items-center gap-2">
              <DollarSign className="w-4 h-4" />
              {t('currency.label')}
            </div>
          </label>
          <select
            value={selectedCurrency}
            onChange={(e) => handleCurrencyRequest(e.target.value)}
            disabled={currencySaving}
            className={`w-full md:w-96 px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary ${currencySaving ? 'opacity-50 cursor-not-allowed' : ''}`}
          >
            {SUPPORTED_CURRENCIES.map((curr) => (
              <option key={curr.code} value={curr.code}>
                {curr.code} — {curr.name}
              </option>
            ))}
          </select>
          <p className="mt-2 text-sm text-garage-text-muted">
            {t('currency.description')}
          </p>
          <p className="mt-1 text-sm text-garage-text-muted">
            {t('currency.preview', {
              amount: formatCurrency(1234.56, {
                currencyCode: selectedCurrency,
                locale: languageToLocale(selectedLanguage),
              }),
            })}
          </p>
        </div>

        {/* Currency Change Confirmation Dialog */}
        {showCurrencyConfirm && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
            <div className="bg-garage-surface border border-garage-border rounded-lg p-6 max-w-md mx-4 space-y-4">
              <h3 className="text-lg font-semibold text-garage-text">
                {t('currency.confirmTitle')}
              </h3>
              <p className="text-sm text-garage-text-muted">
                {t('currency.confirmMessage')}
              </p>
              <div className="flex gap-3 justify-end">
                <button
                  onClick={() => { setShowCurrencyConfirm(false); setPendingCurrency(null) }}
                  className="px-4 py-2 text-sm text-garage-text-muted hover:text-garage-text rounded-lg border border-garage-border hover:bg-garage-bg transition-colors"
                >
                  {t('common:cancel')}
                </button>
                <button
                  onClick={handleCurrencyConfirm}
                  className="px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors font-medium"
                >
                  {t('currency.confirmAction')}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Info Box - Secret Key */}
        <div className="p-4 bg-primary/10 border border-primary/30 rounded-lg">
          <div className="flex items-start gap-2">
            <Info className="w-5 h-5 text-primary mt-0.5 flex-shrink-0" />
            <div className="text-sm text-garage-text">
              <strong className="font-semibold">Secret Key:</strong> Automatically generated and stored securely at{' '}
              <code className="px-1 py-0.5 bg-garage-bg rounded text-xs font-mono">/data/secret.key</code>
              . No manual configuration needed. The key persists across application restarts.
            </div>
          </div>
        </div>

        {/* Message */}
        {message && (
          <div className={`p-4 rounded-lg border flex items-start gap-2 ${
            message.type === 'success'
              ? 'bg-success-500/10 border-success-500 text-success-500'
              : 'bg-danger-500/10 border-danger-500 text-danger-500'
          }`}>
            {message.type === 'success' ? (
              <CheckCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
            ) : (
              <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
            )}
            <div className="flex-1">{message.text}</div>
          </div>
        )}
      </div>

      {/* Mobile Experience Card */}
      {isAuthenticated && (
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6 space-y-4">
          <div className="flex items-start gap-3">
            <Smartphone className="w-6 h-6 text-primary mt-1" />
            <div className="flex-1">
              <h2 className="text-xl font-semibold text-garage-text mb-1">Mobile Experience</h2>
              <p className="text-sm text-garage-text-muted">
                Customize how the app behaves on mobile devices.
              </p>
            </div>
          </div>

          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={mobileQuickEntry}
              onChange={e => handleMobileQuickEntryChange(e.target.checked)}
              disabled={mobileQuickEntrySaving}
              className="w-4 h-4 mt-0.5 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2"
            />
            <div>
              <span className="text-sm font-medium text-garage-text">Quick Entry on Mobile</span>
              <p className="mt-0.5 text-sm text-garage-text-muted">
                After signing in on a mobile device, go directly to Quick Entry instead of the dashboard
              </p>
            </div>
          </label>
        </div>
      )}

      {/* Family Management Card */}
      {isAdmin && (formData.auth_mode === 'local' || formData.auth_mode === 'oidc') && (
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6 space-y-6">
          <div className="flex items-start gap-3">
            <Users className="w-6 h-6 text-primary mt-1" />
            <div className="flex-1">
              <h2 className="text-xl font-semibold text-garage-text mb-2">
                Family Management
              </h2>
              <p className="text-sm text-garage-text-muted">
                Manage family members, user accounts, and dashboard visibility.
              </p>
            </div>
          </div>
          <button
            onClick={() => setShowFamilyManagement(true)}
            className="w-full px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors font-medium"
          >
            Manage Family
          </button>
        </div>
      )}

      </div>

      {/* Right Column */}
      <div className="space-y-6">
      {/* Authentication Mode Card - Separate Section */}
      <div className="bg-garage-surface rounded-lg border border-garage-border overflow-hidden">
        {/* Header */}
        <div className="p-6 pb-0">
          <div className="flex items-start gap-3 mb-4">
            <Shield className="w-6 h-6 text-primary mt-1" />
            <div className="flex-1">
              <h2 className="text-xl font-semibold text-garage-text mb-2">
                Authentication Mode
              </h2>
              <p className="text-sm text-garage-text-muted">
                Configure how users access and authenticate with MyGarage.
              </p>
              <p className="text-xs text-warning-500 mt-2 flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
                <span>⚠️ Requires application restart to take effect.</span>
              </p>
            </div>
          </div>

          {/* Tab Switcher - Moved to top under header */}
          <div className="flex border-b border-garage-border -mx-6 px-6">
            <button
              onClick={() => setFormData({ ...formData, auth_mode: 'none', oidc_enabled: 'false' })}
              className={`px-6 py-4 font-medium transition-colors whitespace-nowrap border-b-2 ${
                formData.auth_mode === 'none'
                  ? 'border-primary text-primary'
                  : 'border-transparent text-garage-text-muted hover:text-garage-text hover:border-garage-border'
              }`}
            >
              None
            </button>
            <button
              onClick={() => setFormData({ ...formData, auth_mode: 'local', oidc_enabled: 'false' })}
              className={`px-6 py-4 font-medium transition-colors whitespace-nowrap border-b-2 ${
                formData.auth_mode === 'local'
                  ? 'border-primary text-primary'
                  : 'border-transparent text-garage-text-muted hover:text-garage-text hover:border-garage-border'
              }`}
            >
              Local
            </button>
            <button
              onClick={() => setFormData({ ...formData, auth_mode: 'oidc', oidc_enabled: 'true' })}
              className={`px-6 py-4 font-medium transition-colors whitespace-nowrap border-b-2 ${
                formData.auth_mode === 'oidc'
                  ? 'border-primary text-primary'
                  : 'border-transparent text-garage-text-muted hover:text-garage-text hover:border-garage-border'
              }`}
            >
              OIDC
            </button>
          </div>
        </div>

        {/* Tab Content */}
        <div className="p-6 min-h-[200px]">
          {/* None Mode Content */}
          {formData.auth_mode === 'none' && (
            <div className="space-y-4">
              {authenticatorDetected === true ? (
                <div className="p-4 bg-primary/10 border border-primary/30 rounded-lg">
                  <div className="flex items-start gap-3">
                    <Info className="w-5 h-5 text-primary flex-shrink-0 mt-0.5" />
                    <div className="text-sm text-garage-text">
                      <strong className="font-semibold">External Authenticator Detected</strong>
                      <p className="mt-1">
                        MyGarage is running behind a reverse proxy authenticator. Authentication modes are only needed if you require additional access control beyond your existing setup.
                      </p>
                    </div>
                  </div>
                </div>
              ) : authenticatorDetected === false ? (
                <div className="p-4 bg-warning-500/10 border border-warning-500/30 rounded-lg">
                  <div className="flex items-start gap-3">
                    <AlertTriangle className="w-5 h-5 text-warning-500 flex-shrink-0 mt-0.5" />
                    <div className="text-sm text-garage-text">
                      <strong className="font-semibold text-warning-500">No Authentication Enabled</strong>
                      <p className="mt-1">
                        Anyone with network access can view and modify data in MyGarage. Consider enabling Local Authentication or placing MyGarage behind an authenticator like Authelia or Authentik.
                      </p>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="p-4 bg-garage-bg border border-garage-border rounded-lg text-center">
                  <p className="text-sm text-garage-text-muted">Checking for authenticators...</p>
                </div>
              )}
            </div>
          )}

          {/* Local Mode Content */}
          {formData.auth_mode === 'local' && (
            <div className="space-y-4">
              <div className="p-4 bg-primary/10 border border-primary/30 rounded-lg">
                <div className="flex items-start gap-3">
                  <Key className="w-5 h-5 text-primary flex-shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <strong className="text-sm font-semibold text-garage-text">Local Authentication</strong>
                    <p className="mt-1 text-sm text-garage-text">
                      {authEverEnabled
                        ? 'Local authentication is configured.'
                        : 'Local authentication allows users to log in with a username and password stored locally.'}
                    </p>
                    <button
                      onClick={() => setShowFamilyManagement(true)}
                      className="mt-3 inline-flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors text-sm font-medium"
                    >
                      Manage Family & Auth →
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* OIDC Mode Content */}
          {formData.auth_mode === 'oidc' && (
            <div className="space-y-4">
              <div className="p-4 bg-primary/10 border border-primary/30 rounded-lg">
                <div className="flex items-start gap-3">
                  <Shield className="w-5 h-5 text-primary flex-shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <strong className="text-sm font-semibold text-garage-text">OpenID Connect (OIDC) Authentication</strong>
                    <p className="mt-1 text-sm text-garage-text">
                      {formData.oidc_issuer_url
                        ? `Configured with ${formData.oidc_provider_name || 'OIDC provider'}`
                        : 'Configure single sign-on with your identity provider (Authentik, Keycloak, Auth0, Okta, etc.)'}
                    </p>
                    <button
                      onClick={() => setShowOIDCModal(true)}
                      className="mt-3 inline-flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors text-sm font-medium"
                    >
                      Configure OIDC
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Archive Management Card */}
      <div className="bg-garage-surface rounded-lg border border-garage-border p-6 space-y-6">
        {/* Header */}
        <div className="flex items-start gap-3">
          <Archive className="w-6 h-6 text-primary mt-1" />
          <div className="flex-1">
            <h2 className="text-xl font-semibold text-garage-text mb-2">
              Archived Vehicles
            </h2>
            <p className="text-sm text-garage-text-muted">
              View and manage vehicles you've archived (sold, totaled, gifted, etc.).
              Archived vehicles remain in analytics but can be hidden from the main list.
            </p>
          </div>
        </div>

        {/* Archived Vehicles List */}
        <ArchivedVehiclesList />
      </div>
      </div>
      </div>

      {/* Family Management Modal */}
      <FamilyManagementModal
        isOpen={showFamilyManagement}
        onClose={() => setShowFamilyManagement(false)}
      />

      {/* OIDC Modal */}
      <OIDCModal
        isOpen={showOIDCModal}
        onClose={() => setShowOIDCModal(false)}
        formData={{
          oidc_provider_name: formData.oidc_provider_name,
          oidc_issuer_url: formData.oidc_issuer_url,
          oidc_client_id: formData.oidc_client_id,
          oidc_client_secret: formData.oidc_client_secret,
          oidc_scopes: formData.oidc_scopes,
          oidc_auto_create_users: formData.oidc_auto_create_users,
          oidc_admin_group: formData.oidc_admin_group,
          oidc_username_claim: formData.oidc_username_claim,
          oidc_email_claim: formData.oidc_email_claim,
          oidc_full_name_claim: formData.oidc_full_name_claim,
        }}
        onFormDataChange={(data) => setFormData({ ...formData, ...data })}
      />
    </div>
  )
}

interface StatCardProps {
  icon: React.ReactNode
  label: string
  value: number
  color: string
}

function StatCard({ icon, label, value, color }: StatCardProps) {
  return (
    <div className="bg-garage-surface border border-garage-border rounded-lg p-4">
      <div className="flex items-center justify-between mb-2">
        <div className={`${color}`}>{icon}</div>
      </div>
      <div className="text-2xl font-bold text-garage-text mb-1">{value}</div>
      <div className="text-sm text-garage-text-muted">{label}</div>
    </div>
  )
}
