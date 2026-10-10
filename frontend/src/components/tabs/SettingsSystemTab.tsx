import { useState, useCallback, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Server, AlertCircle, Info, Shield, Users, AlertTriangle, Key, Wrench, Fuel, Bell, FileText, StickyNote, Camera, Archive, Smartphone } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { useSettings } from '@/contexts/SettingsContext'
import { useCanManageInstance } from '@/hooks/useCanManageInstance'
import type { DashboardResponse } from '@/types/dashboard'
import api from '@/services/api'
import { toast } from 'sonner'
import OIDCModal from '@/components/modals/OIDCModal'
import FamilyManagementModal from '@/components/modals/FamilyManagementModal'
import ArchivedVehiclesList from '@/components/ArchivedVehiclesList'
import InstanceUnitDefaultsCard from '@/components/settings/InstanceUnitDefaultsCard'
import { Select, Toggle } from '../ui'

type RawSetting = {
  key: string
  value?: string | null
}

/**
 * Settings > System: what applies to the whole instance, for admins, plus the
 * few cards that are each person's own (mobile quick entry, fuel defaults,
 * archived vehicles). Units, time format, language and currency live in Quick
 * Settings (`components/shell/QuickSettingsDrawer.tsx`).
 *
 * Every instance setting is admin-only on the server, so a non-admin is shown
 * none of them and the tab asks for none of them: they used to get the whole
 * tab, with the timezone reading UTC and switches that looked saved and never
 * were. With auth off there is one user and no admin, so everything shows.
 */
export default function SettingsSystemTab() {
  const { t } = useTranslation('settings')
  const { isAuthenticated, isAdmin, user: currentUser, refreshUser, refreshPublicSettings } = useAuth()
  const canManageInstance = useCanManageInstance()
  const { triggerSave, registerSaveHandler, unregisterSaveHandler } = useSettings()
  const [formData, setFormData] = useState({
    timezone: 'UTC',
    family_friends_enabled: 'false',
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
  // The server's own default zone, known only when the page loaded with no zone
  // stored (the zone in effect then IS the default). With a stored zone it
  // stays null, so the option can't name the stored zone as the default.
  const [serverDefaultZone, setServerDefaultZone] = useState<string | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)
  const [authenticatorDetected, setAuthenticatorDetected] = useState<boolean | null>(null)
  const [authEverEnabled, setAuthEverEnabled] = useState(false)
  const [dashboardStats, setDashboardStats] = useState<DashboardResponse | null>(null)

  // Modal state
  const [showFamilyManagement, setShowFamilyManagement] = useState(false)
  const [showOIDCModal, setShowOIDCModal] = useState(false)

  const [autoArchiveDays, setAutoArchiveDays] = useState('0')
  const [autoArchiveSaving, setAutoArchiveSaving] = useState(false)

  // Mobile experience state
  const [mobileQuickEntry, setMobileQuickEntry] = useState(true)
  const [mobileQuickEntrySaving, setMobileQuickEntrySaving] = useState(false)

  // Fuel-tracking form defaults (issue #69)
  const [defaultPaymentMethod, setDefaultPaymentMethod] = useState<string>('')
  const [defaultTripType, setDefaultTripType] = useState<string>('')
  const [fuelDefaultsSaving, setFuelDefaultsSaving] = useState(false)

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
    'America/Sao_Paulo',
    'America/Bahia',
    'America/Fortaleza',
    'America/Recife',
    'America/Belem',
    'America/Manaus',
    'America/Cuiaba',
    'America/Campo_Grande',
    'America/Porto_Velho',
    'America/Boa_Vista',
    'America/Rio_Branco',
    'America/Noronha',
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

      // OIDC settings come from the dedicated admin endpoint so client_secret is
      // returned as the canonical "********" placeholder per plan §5.4(3).
      let oidcAdmin: {
        enabled: boolean
        provider_name: string
        issuer_url: string
        client_id: string
        client_secret: string
        redirect_uri: string
        scopes: string
        auto_create_users: boolean
        admin_group: string
        username_claim: string
        email_claim: string
        full_name_claim: string
      } | null = null
      try {
        const oidcResponse = await api.get('/auth/oidc/config/admin')
        oidcAdmin = oidcResponse.data
      } catch {
        // If the admin OIDC config cannot be read, fall back to the public minimal config.
        oidcAdmin = null
      }

      const newFormData = {
        // '' is "Server default". Seeding the zone in effect here saved it on
        // the next save and froze the env/container fallback into the setting.
        timezone: settingsMap.timezone || '',
        family_friends_enabled: settingsMap.family_friends_enabled || 'false',
        auth_mode: settingsMap.auth_mode || 'none',
        oidc_enabled: oidcAdmin ? (oidcAdmin.enabled ? 'true' : 'false') : settingsMap.oidc_enabled || 'false',
        oidc_provider_name: oidcAdmin?.provider_name ?? (settingsMap.oidc_provider_name || ''),
        oidc_issuer_url: oidcAdmin?.issuer_url ?? (settingsMap.oidc_issuer_url || ''),
        oidc_client_id: oidcAdmin?.client_id ?? (settingsMap.oidc_client_id || ''),
        oidc_client_secret: oidcAdmin?.client_secret ?? '',
        oidc_redirect_uri: oidcAdmin?.redirect_uri ?? (settingsMap.oidc_redirect_uri || ''),
        oidc_scopes: oidcAdmin?.scopes ?? (settingsMap.oidc_scopes || 'openid profile email'),
        oidc_auto_create_users: oidcAdmin
          ? (oidcAdmin.auto_create_users ? 'true' : 'false')
          : settingsMap.oidc_auto_create_users || 'true',
        oidc_admin_group: oidcAdmin?.admin_group ?? (settingsMap.oidc_admin_group || ''),
        oidc_username_claim: oidcAdmin?.username_claim ?? (settingsMap.oidc_username_claim || 'preferred_username'),
        oidc_email_claim: oidcAdmin?.email_claim ?? (settingsMap.oidc_email_claim || 'email'),
        oidc_full_name_claim: oidcAdmin?.full_name_claim ?? (settingsMap.oidc_full_name_claim || 'name'),
      }
      setFormData(newFormData)
      setLoadedFormData(newFormData)
      setServerDefaultZone(settingsMap.timezone ? null : settingsMap.effective_timezone || null)

      setAutoArchiveDays(settingsMap.auto_archive_inactive_days || '0')

      // Anyone registered means auth has been on at some point
      try {
        const countResponse = await api.get('/auth/users/count')
        const countData = countResponse.data
        setAuthEverEnabled(countData.has_users === true)
      } catch {
        setAuthEverEnabled(false)
      }
    } catch {
      setLoadFailed(true)
    }
  }, [])

  useEffect(() => {
    // Every key it reads is admin-only on the server.
    if (canManageInstance) void loadSettings()
  }, [loadSettings, canManageInstance])

  // Load user's preferences
  useEffect(() => {
    if (currentUser) {
      setMobileQuickEntry(currentUser.mobile_quick_entry_enabled ?? true)
      setDefaultPaymentMethod(currentUser.default_payment_method ?? '')
      setDefaultTripType(currentUser.default_trip_type ?? '')
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

  // Detect reverse proxy authenticators (shown on the admin-only auth card)
  useEffect(() => {
    if (!canManageInstance) return
    const detectAuthenticator = async () => {
      try {
        const response = await api.get('/health')
        setAuthenticatorDetected(response.data.authenticator_detected || false)
      } catch {
        setAuthenticatorDetected(false)
      }
    }

    detectAuthenticator()
  }, [canManageInstance])

  // Save settings.
  // OIDC settings go to the dedicated admin endpoint (enforces §5.4 contract:
  // empty secret = preserve, issuer rstrip); everything else goes to /settings/batch.
  const handleSave = useCallback(async () => {
    // Nothing loaded (or the load failed): the form holds hard-coded defaults,
    // and saving them would overwrite the real settings.
    if (loadedFormData === null) return

    // Only the keys the user changed. Posting every key rewrote auth_mode and
    // the rest on each save, and froze whatever the form had seeded.
    const nonOidcSettings: Record<string, string> = {}
    for (const [key, value] of Object.entries(formData) as Array<[keyof typeof formData, string]>) {
      if (!key.startsWith('oidc_') && value !== loadedFormData[key]) {
        nonOidcSettings[key] = value
      }
    }

    // Only touch the OIDC admin endpoint when an OIDC field actually changed.
    // Saving is auto-triggered by any edit on this tab, so without this guard an
    // unrelated change (timezone, say) is blocked whenever the OIDC PUT fails
    // — and auth_mode rides in the batch below, so a failure there strands the
    // mode. The PUT still goes FIRST when OIDC is dirty: the provider config
    // must land before auth_mode flips to 'oidc', or the mode is enabled against
    // config that never saved.
    const oidcDirty = (Object.keys(formData) as Array<keyof typeof formData>).some(
      (key) => key.startsWith('oidc_') && formData[key] !== loadedFormData[key],
    )

    if (oidcDirty) {
      await api.put('/auth/oidc/config/admin', {
        enabled: formData.oidc_enabled === 'true',
        provider_name: formData.oidc_provider_name,
        issuer_url: formData.oidc_issuer_url,
        client_id: formData.oidc_client_id,
        client_secret: formData.oidc_client_secret,
        redirect_uri: formData.oidc_redirect_uri,
        scopes: formData.oidc_scopes,
        auto_create_users: formData.oidc_auto_create_users === 'true',
        admin_group: formData.oidc_admin_group,
        username_claim: formData.oidc_username_claim,
        email_claim: formData.oidc_email_claim,
        full_name_claim: formData.oidc_full_name_claim,
      })
    }

    if (Object.keys(nonOidcSettings).length > 0) {
      await api.post('/settings/batch', { settings: nonOidcSettings })
    }
    // What's saved is the new baseline for the next diff.
    setLoadedFormData(formData)

    if ('timezone' in nonOidcSettings) {
      // The saved zone changes what "today" means for every open form;
      // update the browser store before leaving the saving state.
      await refreshPublicSettings()
    }
  }, [formData, loadedFormData, refreshPublicSettings])

  const handleAutoArchiveDaysChange = (raw: string) => {
    setAutoArchiveDays(raw.replace(/[^\d]/g, ''))
  }

  const saveAutoArchiveDays = async () => {
    setAutoArchiveSaving(true)
    try {
      const value = String(Math.max(0, parseInt(autoArchiveDays || '0', 10) || 0))
      setAutoArchiveDays(value)
      await api.post('/settings/batch', {
        settings: { auto_archive_inactive_days: value },
      })
      toast.success(t('archive.autoArchiveSaved'))
    } catch {
      toast.error(t('archive.autoArchiveError'))
    } finally {
      setAutoArchiveSaving(false)
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
            label={t('stats.serviceRecords')}
            value={dashboardStats.total_service_records}
            color="text-primary"
          />
          <StatCard
            icon={<Fuel className="w-5 h-5" />}
            label={t('stats.fuelRecords')}
            value={dashboardStats.total_fuel_records}
            color="text-primary"
          />
          <StatCard
            icon={<Bell className="w-5 h-5" />}
            label={t('stats.maintenanceItems')}
            value={dashboardStats.total_maintenance_items}
            color="text-warning"
          />
          <StatCard
            icon={<FileText className="w-5 h-5" />}
            label={t('stats.documents')}
            value={dashboardStats.total_documents}
            color="text-primary"
          />
          <StatCard
            icon={<StickyNote className="w-5 h-5" />}
            label={t('stats.notes')}
            value={dashboardStats.total_notes}
            color="text-primary"
          />
          <StatCard
            icon={<Camera className="w-5 h-5" />}
            label={t('stats.photos')}
            value={dashboardStats.total_photos}
            color="text-primary"
          />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Left Column */}
      <div className="space-y-6">
      {/* System Configuration Section */}
      {canManageInstance && (
      <div className="bg-garage-surface rounded-lg border border-garage-border p-6 space-y-6">
        {/* Header */}
        <div className="flex items-start gap-3">
          <Server className="w-6 h-6 text-primary mt-1" />
          <div className="flex-1">
            <h2 className="text-xl font-semibold text-garage-text mb-2">
              {t('systemConfig.title')}
            </h2>
            <p className="text-sm text-garage-text-muted">
              {t('systemConfig.description')}
            </p>
          </div>
        </div>

        {/* Timezone Setting */}
        <div>
          <label htmlFor="timezone" className="block text-sm font-medium text-garage-text mb-2">
            {t('timezone.label')}
          </label>
          <Select
            id="timezone"
            value={formData.timezone}
            onChange={(e) => setFormData({ ...formData, timezone: e.target.value })}
            className="md:w-96"
            options={[
              {
                value: '',
                label: serverDefaultZone
                  ? t('timezone.serverDefaultZone', { zone: serverDefaultZone })
                  : t('timezone.serverDefault'),
              },
              ...(formData.timezone === '' || timezones.includes(formData.timezone)
                ? timezones
                : [formData.timezone, ...timezones]
              ).map((tz) => ({ value: tz, label: tz })),
            ]}
          />
          <p className="mt-2 text-sm text-garage-text-muted">
            {t('timezone.description')}
          </p>
        </div>

        {/* Garage sections */}
        <div>
          <h3 className="text-sm font-medium text-garage-text mb-1">
            {t('garageSections.title')}
          </h3>
          <p className="mb-3 text-sm text-garage-text-muted">
            {t('garageSections.description')}
          </p>
          <div className="space-y-4">
            <div>
              <Toggle
                id="family_friends_enabled"
                label={t('garageSections.familyFriends')}
                checked={formData.family_friends_enabled === 'true'}
                onChange={(next) =>
                  setFormData({
                    ...formData,
                    family_friends_enabled: next ? 'true' : 'false',
                  })
                }
              />
              <p className="mt-1 text-sm text-garage-text-muted">
                {t('garageSections.familyFriendsDesc')}
              </p>
            </div>
          </div>
        </div>

        {/* The instance default an admin sets for everyone who has not
            chosen. Each person's own units are in Quick Settings. */}
        <InstanceUnitDefaultsCard />

        <div>
          <label className="block text-sm font-medium text-garage-text mb-2">
            {t('archive.autoArchiveLabel')}
          </label>
          <div className="flex gap-3 items-end">
            <div className="flex-1">
              <label className="block text-xs text-garage-text-muted mb-1">
                {t('archive.autoArchiveDays')}
              </label>
              <input
                type="number"
                min={0}
                value={autoArchiveDays}
                onChange={(e) => handleAutoArchiveDaysChange(e.target.value)}
                onBlur={() => void saveAutoArchiveDays()}
                disabled={autoArchiveSaving}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text"
              />
            </div>
          </div>
          <p className="mt-2 text-sm text-garage-text-muted">
            {t('archive.autoArchiveDescription')}
          </p>
        </div>

        {/* Info Box - Secret Key */}
        <div className="p-4 bg-primary/10 border border-primary/30 rounded-lg">
          <div className="flex items-start gap-2">
            <Info className="w-5 h-5 text-primary mt-0.5 flex-shrink-0" />
            <div className="text-sm text-garage-text">
              <strong className="font-semibold">{t('secretKey.label')}</strong>{' '}
              {t('secretKey.description', { path: '/data/secret.key' })}
            </div>
          </div>
        </div>

        {loadFailed && (
          <div className="p-4 rounded-lg border flex items-start gap-2 bg-danger-500/10 border-danger-500 text-danger-500">
            <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
            <div className="flex-1">{t('common:errors.generic')}</div>
          </div>
        )}
      </div>
      )}

      {/* Mobile Experience Card */}
      {isAuthenticated && (
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6 space-y-4">
          <div className="flex items-start gap-3">
            <Smartphone className="w-6 h-6 text-primary mt-1" />
            <div className="flex-1">
              <h2 className="text-xl font-semibold text-garage-text mb-1">{t('mobile.title')}</h2>
              <p className="text-sm text-garage-text-muted">
                {t('mobile.description')}
              </p>
            </div>
          </div>

          <div>
            <Toggle
              label={t('mobile.quickEntry')}
              checked={mobileQuickEntry}
              onChange={handleMobileQuickEntryChange}
              disabled={mobileQuickEntrySaving}
            />
            <p className="mt-1 text-sm text-garage-text-muted">
              {t('mobile.quickEntryDescription')}
            </p>
          </div>
        </div>
      )}

      {/* Fuel Tracking Defaults Card (issue #69) */}
      {isAuthenticated && (
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6 space-y-4">
          <div className="flex items-start gap-3">
            <Fuel className="w-6 h-6 text-primary mt-1" />
            <div className="flex-1">
              <h2 className="text-xl font-semibold text-garage-text mb-1">
                {t('fuel.title')}
              </h2>
              <p className="text-sm text-garage-text-muted">
                {t('fuel.description')}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="default_payment_method" className="block text-sm font-medium text-garage-text mb-1">
                {t('fuel.defaultPaymentMethod')}
              </label>
              <Select
                id="default_payment_method"
                value={defaultPaymentMethod}
                onChange={async (e) => {
                  const value = e.target.value
                  setDefaultPaymentMethod(value)
                  setFuelDefaultsSaving(true)
                  try {
                    await api.put('/auth/me', {
                      default_payment_method: value === '' ? null : value,
                    })
                    await refreshUser()
                    toast.success(t('fuel.defaultsSaved'))
                  } catch {
                    toast.error(t('fuel.defaultsError'))
                    setDefaultPaymentMethod(currentUser?.default_payment_method ?? '')
                  } finally {
                    setFuelDefaultsSaving(false)
                  }
                }}
                disabled={fuelDefaultsSaving}
                placeholder="—"
                options={[
                  { value: 'cash', label: t('forms:fuel.paymentMethods.cash') },
                  { value: 'credit', label: t('forms:fuel.paymentMethods.credit') },
                  { value: 'debit', label: t('forms:fuel.paymentMethods.debit') },
                  { value: 'fleet_card', label: t('forms:fuel.paymentMethods.fleet_card') },
                  { value: 'app', label: t('forms:fuel.paymentMethods.app') },
                  { value: 'other', label: t('forms:fuel.paymentMethods.other') },
                ]}
              />
            </div>

            <div>
              <label htmlFor="default_trip_type" className="block text-sm font-medium text-garage-text mb-1">
                {t('fuel.defaultTripType')}
              </label>
              <Select
                id="default_trip_type"
                value={defaultTripType}
                onChange={async (e) => {
                  const value = e.target.value
                  setDefaultTripType(value)
                  setFuelDefaultsSaving(true)
                  try {
                    await api.put('/auth/me', {
                      default_trip_type: value === '' ? null : value,
                    })
                    await refreshUser()
                    toast.success(t('fuel.defaultsSaved'))
                  } catch {
                    toast.error(t('fuel.defaultsError'))
                    setDefaultTripType(currentUser?.default_trip_type ?? '')
                  } finally {
                    setFuelDefaultsSaving(false)
                  }
                }}
                disabled={fuelDefaultsSaving}
                placeholder="—"
                options={[
                  { value: 'private', label: t('forms:fuel.tripTypes.private') },
                  { value: 'business', label: t('forms:fuel.tripTypes.business') },
                  { value: 'commute', label: t('forms:fuel.tripTypes.commute') },
                  { value: 'other', label: t('forms:fuel.tripTypes.other') },
                ]}
              />
            </div>
          </div>
        </div>
      )}

      {/* Family Management Card */}
      {isAdmin && (formData.auth_mode === 'local' || formData.auth_mode === 'oidc') && (
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6 space-y-6">
          <div className="flex items-start gap-3">
            <Users className="w-6 h-6 text-primary mt-1" />
            <div className="flex-1">
              <h2 className="text-xl font-semibold text-garage-text mb-2">
                {t('family.title')}
              </h2>
              <p className="text-sm text-garage-text-muted">
                {t('family.description')}
              </p>
            </div>
          </div>
          <button
            onClick={() => setShowFamilyManagement(true)}
            className="w-full px-4 py-2 bg-primary text-(--accent-on-solid) rounded-lg hover:bg-primary/90 transition-colors font-medium"
          >
            {t('family.manage')}
          </button>
        </div>
      )}

      </div>

      {/* Right Column */}
      <div className="space-y-6">
      {/* Authentication Mode Card - Separate Section */}
      {canManageInstance && (
      <div className="bg-garage-surface rounded-lg border border-garage-border overflow-hidden">
        {/* Header */}
        <div className="p-6 pb-0">
          <div className="flex items-start gap-3 mb-4">
            <Shield className="w-6 h-6 text-primary mt-1" />
            <div className="flex-1">
              <h2 className="text-xl font-semibold text-garage-text mb-2">
                {t('auth.title')}
              </h2>
              <p className="text-sm text-garage-text-muted">
                {t('auth.description')}
              </p>
              <p className="text-xs text-warning-500 mt-2 flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
                <span>{t('auth.restartWarning')}</span>
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
              {t('auth.none')}
            </button>
            <button
              onClick={() => setFormData({ ...formData, auth_mode: 'local', oidc_enabled: 'false' })}
              className={`px-6 py-4 font-medium transition-colors whitespace-nowrap border-b-2 ${
                formData.auth_mode === 'local'
                  ? 'border-primary text-primary'
                  : 'border-transparent text-garage-text-muted hover:text-garage-text hover:border-garage-border'
              }`}
            >
              {t('auth.local')}
            </button>
            <button
              onClick={() => setFormData({ ...formData, auth_mode: 'oidc', oidc_enabled: 'true' })}
              className={`px-6 py-4 font-medium transition-colors whitespace-nowrap border-b-2 ${
                formData.auth_mode === 'oidc'
                  ? 'border-primary text-primary'
                  : 'border-transparent text-garage-text-muted hover:text-garage-text hover:border-garage-border'
              }`}
            >
              {t('auth.oidc')}
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
                      <strong className="font-semibold">{t('auth.noneDetected')}</strong>
                      <p className="mt-1">
                        {t('auth.noneDetectedDescription')}
                      </p>
                    </div>
                  </div>
                </div>
              ) : authenticatorDetected === false ? (
                <div className="p-4 bg-warning-500/10 border border-warning-500/30 rounded-lg">
                  <div className="flex items-start gap-3">
                    <AlertTriangle className="w-5 h-5 text-warning-500 flex-shrink-0 mt-0.5" />
                    <div className="text-sm text-garage-text">
                      <strong className="font-semibold text-warning-500">{t('auth.noneWarning')}</strong>
                      <p className="mt-1">
                        {t('auth.noneWarningDescription')}
                      </p>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="p-4 bg-garage-bg border border-garage-border rounded-lg text-center">
                  <p className="text-sm text-garage-text-muted">{t('auth.checking')}</p>
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
                    <strong className="text-sm font-semibold text-garage-text">{t('auth.localTitle')}</strong>
                    <p className="mt-1 text-sm text-garage-text">
                      {authEverEnabled
                        ? t('auth.localConfigured')
                        : t('auth.localDescription')}
                    </p>
                    <button
                      onClick={() => setShowFamilyManagement(true)}
                      className="mt-3 inline-flex items-center gap-2 px-4 py-2 bg-primary text-(--accent-on-solid) rounded-lg hover:bg-primary/90 transition-colors text-sm font-medium"
                    >
                      {t('auth.manageAuth')}
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
                    <strong className="text-sm font-semibold text-garage-text">{t('auth.oidcTitle')}</strong>
                    <p className="mt-1 text-sm text-garage-text">
                      {formData.oidc_issuer_url
                        ? t('auth.oidcConfigured', { provider: formData.oidc_provider_name || 'OIDC provider' })
                        : t('auth.oidcDescription')}
                    </p>
                    <button
                      onClick={() => setShowOIDCModal(true)}
                      className="mt-3 inline-flex items-center gap-2 px-4 py-2 bg-primary text-(--accent-on-solid) rounded-lg hover:bg-primary/90 transition-colors text-sm font-medium"
                    >
                      {t('auth.configureOIDC')}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
      )}

      {/* Archive Management Card */}
      <div className="bg-garage-surface rounded-lg border border-garage-border p-6 space-y-6">
        {/* Header */}
        <div className="flex items-start gap-3">
          <Archive className="w-6 h-6 text-primary mt-1" />
          <div className="flex-1">
            <h2 className="text-xl font-semibold text-garage-text mb-2">
              {t('archive.title')}
            </h2>
            <p className="text-sm text-garage-text-muted">
              {t('archive.description')}
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
          oidc_redirect_uri: formData.oidc_redirect_uri,
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
