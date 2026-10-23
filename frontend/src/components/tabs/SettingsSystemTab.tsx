import { useState, useCallback, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Server, AlertCircle, Info, Shield, Users, AlertTriangle, Key, Wrench, Fuel, Bell, FileText, StickyNote, Camera, Archive, Smartphone } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { useSettings } from '@/contexts/SettingsContext'
import { useCanManageInstance } from '@/hooks/useCanManageInstance'
import type { DashboardResponse } from '@/types/dashboard'
import type { components } from '@/types/api.generated'
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

type AuthMode = 'none' | 'local' | 'oidc'
type OIDCAdminConfig = components['schemas']['OIDCAdminConfig']
// What the admin GET returns: the PUT body plus the read-only client_secret_unreadable flag.
type OIDCAdminConfigResponse = components['schemas']['OIDCAdminConfigResponse']

const AUTH_MODES: AuthMode[] = ['none', 'local', 'oidc']

// Left out, the stored Callback URL stays as it is. Re-sending it would put an
// old pin through today's rule and fail a switch over an unrelated field. The
// GET-only client_secret_unreadable flag isn't part of the PUT body either.
function ssoPayload(config: OIDCAdminConfigResponse, enabled: boolean): Omit<OIDCAdminConfig, 'redirect_uri'> {
  const { redirect_uri: _pin, client_secret_unreadable: _unreadable, ...sso } = config
  return { ...sso, enabled }
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
  })
  // Saved on their own, never by the auto-save: switching modes and the SSO
  // modal each have a button, because a stray click here can lock people out.
  const [savedAuthMode, setSavedAuthMode] = useState<AuthMode>('none')
  const [viewedMode, setViewedMode] = useState<AuthMode | null>(null)
  const [switchingMode, setSwitchingMode] = useState(false)
  const [oidcConfig, setOidcConfig] = useState<OIDCAdminConfigResponse | null>(null)
  const shownMode: AuthMode = viewedMode ?? savedAuthMode
  const [loadedFormData, setLoadedFormData] = useState<typeof formData | null>(null)
  // The server's own default zone, known only when the page loaded with no zone
  // stored (the zone in effect then IS the default). With a stored zone it
  // stays null, so the option can't name the stored zone as the default.
  const [serverDefaultZone, setServerDefaultZone] = useState<string | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)
  const [authenticatorDetected, setAuthenticatorDetected] = useState<boolean | null>(null)
  // null until /auth/users/count answers, and if it never does. The confirms read
  // unknown as "accounts exist", so nobody gets told to register on a full instance.
  const [authEverEnabled, setAuthEverEnabled] = useState<boolean | null>(null)
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

  // The SSO config, from its admin endpoint (the secret comes back as "********").
  // Its own callback so the modal's onSaved can re-read just this.
  const loadOidcConfig = useCallback(async (): Promise<OIDCAdminConfigResponse | null> => {
    try {
      const response = await api.get('/auth/oidc/config/admin')
      const config = response.data as OIDCAdminConfigResponse
      setOidcConfig(config)
      return config
    } catch {
      setOidcConfig(null)
      return null
    }
  }, [])

  // Load settings. Returns what it read, so a mode switch can tell what landed.
  const loadSettings = useCallback(async (): Promise<{ mode: AuthMode; oidc: OIDCAdminConfigResponse | null } | null> => {
    try {
      const response = await api.get('/settings')
      const data = response.data

      const settingsMap: Record<string, string> = {}
      data.settings.forEach((s: RawSetting) => {
        settingsMap[s.key] = s.value || ''
      })

      const newFormData = {
        // '' is "Server default". Seeding the zone in effect here saved it on
        // the next save and froze the env/container fallback into the setting.
        timezone: settingsMap.timezone || '',
        family_friends_enabled: settingsMap.family_friends_enabled || 'false',
      }
      setFormData(newFormData)
      setLoadedFormData(newFormData)
      setServerDefaultZone(settingsMap.timezone ? null : settingsMap.effective_timezone || null)

      const mode: AuthMode = AUTH_MODES.includes(settingsMap.auth_mode as AuthMode)
        ? (settingsMap.auth_mode as AuthMode)
        : 'none'
      setSavedAuthMode(mode)
      const oidc = await loadOidcConfig()

      setAutoArchiveDays(settingsMap.auto_archive_inactive_days || '0')

      // Anyone registered means auth has been on at some point
      try {
        const countResponse = await api.get('/auth/users/count')
        const countData = countResponse.data
        setAuthEverEnabled(countData.has_users === true)
      } catch {
        setAuthEverEnabled(null)
      }
      return { mode, oidc }
    } catch {
      setLoadFailed(true)
      return null
    }
  }, [loadOidcConfig])

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

  // The auto-save: the timezone and the Family & Friends switch. The sign-in
  // mode and the SSO config each save from their own button.
  const handleSave = useCallback(async () => {
    // Nothing loaded (or the load failed): the form holds hard-coded defaults,
    // and saving them would overwrite the real settings.
    if (loadedFormData === null) return

    // Only the keys the user changed. Posting every key rewrote auth_mode and
    // the rest on each save, and froze whatever the form had seeded.
    const changed: Record<string, string> = {}
    for (const [key, value] of Object.entries(formData) as Array<[keyof typeof formData, string]>) {
      if (value !== loadedFormData[key]) {
        changed[key] = value
      }
    }

    if (Object.keys(changed).length > 0) {
      await api.post('/settings/batch', { settings: changed })
    }
    // What's saved is the new baseline for the next diff.
    setLoadedFormData(formData)

    if ('timezone' in changed) {
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

  const switchAuthMode = async (target: AuthMode): Promise<void> => {
    const from = savedAuthMode
    // Only a switch into or out of SSO touches the SSO config, so only those need it.
    if ((target === 'oidc' || from === 'oidc') && !oidcConfig) return
    const provider = oidcConfig?.provider_name || 'SSO'
    const message =
      target === 'none'
        ? t('auth.confirmNone')
        : target === 'local'
          ? authEverEnabled === false
            ? t('auth.confirmLocalFirstUser')
            : t('auth.confirmLocal')
          : authEverEnabled === false
            ? t('auth.confirmOidcFirstUser', { provider })
            : t('auth.confirmOidc', { provider })
    if (!confirm(message)) return

    // Whether this switch is the one turning SSO on, so a failed mode write can undo it.
    // Set before the PUT, since a lost reply can still have committed. The re-read decides.
    let turningSsoOn = false
    setSwitchingMode(true)
    try {
      // Into SSO: turn OIDC on before the mode, or the mode points at nothing.
      // Out of SSO: the mode goes first, so a failure can't leave SSO mode with SSO off.
      if (target === 'oidc' && oidcConfig) {
        turningSsoOn = !oidcConfig.enabled
        await api.put('/auth/oidc/config/admin', ssoPayload(oidcConfig, true))
      }
      await api.post('/settings/batch', { settings: { auth_mode: target } })
      if (target !== 'oidc' && oidcConfig?.enabled) {
        await api.put('/auth/oidc/config/admin', ssoPayload(oidcConfig, false))
      }
    } catch {
      // The re-read below says what actually landed.
    }
    // The server is the truth now, success or not: a write can commit and its
    // reply still get lost. AuthContext first, so a 401 redirects before the card re-reads.
    setViewedMode(null)
    await refreshUser()
    const now = await loadSettings()
    // SSO went on but the mode didn't, so the sign-in page would offer SSO anyway.
    // Turn it back off from the fresh config, not the one this click started with.
    // A mode write that dropped but commits after this re-read would still end in SSO
    // mode with SSO off. Only a server-side rule can close that, so it's left for later.
    let ssoLeftOn = false
    if (turningSsoOn && now !== null && now.mode !== 'oidc' && now.oidc?.enabled) {
      try {
        await api.put('/auth/oidc/config/admin', ssoPayload(now.oidc, false))
      } catch {
        ssoLeftOn = true
      }
      await loadOidcConfig()
    }
    setSwitchingMode(false)
    // Turning sign-in on from none: this browser has no session in the new mode, so
    // /settings 401s and the page is off to /login. A real failure still shows the error box.
    if (now === null && from === 'none' && target !== 'none') return
    if (ssoLeftOn) toast.error(t('auth.ssoLeftOn'))
    else if (now?.mode !== target) toast.error(t('auth.switchFailed'))
    else if (target !== 'oidc' && now.oidc?.enabled) toast.warning(t('auth.ssoStillOn'))
    else toast.success(t('auth.switched'))
  }

  const oidcReady = Boolean(oidcConfig?.issuer_url && oidcConfig?.client_id)
  // Going into or out of SSO writes the SSO config, so those switches wait for it.
  // None to local and back doesn't, so a failed config read can't block turning sign-in off.
  const needsOidcConfig = shownMode === 'oidc' || savedAuthMode === 'oidc'

  const modeLabel = (mode: AuthMode): string =>
    mode === 'none' ? t('auth.none') : mode === 'local' ? t('auth.local') : t('auth.oidc')

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
      {isAdmin && (savedAuthMode === 'local' || savedAuthMode === 'oidc') && (
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
              <p className="text-xs text-garage-text-muted mt-2">{t('auth.appliesImmediately')}</p>
            </div>
          </div>

          {/* The tabs only pick a panel. Switching is the button inside it. */}
          <div className="flex border-b border-garage-border -mx-6 px-6">
            {AUTH_MODES.map((mode) => (
              <button
                key={mode}
                onClick={() => setViewedMode(mode)}
                className={`px-6 py-4 font-medium transition-colors whitespace-nowrap border-b-2 ${
                  shownMode === mode
                    ? 'border-primary text-primary'
                    : 'border-transparent text-garage-text-muted hover:text-garage-text hover:border-garage-border'
                }`}
              >
                {modeLabel(mode)}
                {savedAuthMode === mode && (
                  <span className="ml-2 text-xs font-normal text-garage-text-muted">{t('auth.current')}</span>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Tab Content */}
        <div className="p-6 min-h-[200px]">
          {/* None Mode Content */}
          {shownMode === 'none' && (
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
          {shownMode === 'local' && (
            <div className="space-y-4">
              <div className="p-4 bg-primary/10 border border-primary/30 rounded-lg">
                <div className="flex items-start gap-3">
                  <Key className="w-5 h-5 text-primary flex-shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <strong className="text-sm font-semibold text-garage-text">{t('auth.localTitle')}</strong>
                    <p className="mt-1 text-sm text-garage-text">
                      {/* Unknown gets the plain description: it claims nothing either way. */}
                      {authEverEnabled === true
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
          {shownMode === 'oidc' && (
            <div className="space-y-4">
              <div className="p-4 bg-primary/10 border border-primary/30 rounded-lg">
                <div className="flex items-start gap-3">
                  <Shield className="w-5 h-5 text-primary flex-shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <strong className="text-sm font-semibold text-garage-text">{t('auth.oidcTitle')}</strong>
                    <p className="mt-1 text-sm text-garage-text">
                      {oidcConfig?.issuer_url
                        ? t('auth.oidcConfigured', { provider: oidcConfig.provider_name || 'OIDC provider' })
                        : t('auth.oidcDescription')}
                    </p>
                    <button
                      onClick={() => setShowOIDCModal(true)}
                      disabled={oidcConfig === null}
                      className="mt-3 inline-flex items-center gap-2 px-4 py-2 bg-primary text-(--accent-on-solid) rounded-lg hover:bg-primary/90 transition-colors text-sm font-medium disabled:opacity-50"
                    >
                      {t('auth.configureOIDC')}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {shownMode !== savedAuthMode && (
            <div className="mt-4 space-y-2">
              {shownMode === 'oidc' && oidcConfig !== null && !oidcReady && (
                <p className="text-xs text-garage-text-muted">{t('auth.oidcNotReady')}</p>
              )}
              {/* Until /settings loads, the saved mode is only a placeholder. */}
              <button
                onClick={() => void switchAuthMode(shownMode)}
                disabled={
                  switchingMode ||
                  loadedFormData === null ||
                  (needsOidcConfig && oidcConfig === null) ||
                  (shownMode === 'oidc' && !oidcReady)
                }
                className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-(--accent-on-solid) rounded-lg hover:bg-primary/90 transition-colors text-sm font-medium disabled:opacity-50"
              >
                {shownMode === 'none'
                  ? t('auth.switchToNone')
                  : shownMode === 'local'
                    ? t('auth.switchToLocal')
                    : t('auth.switchToOidc')}
              </button>
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
      {oidcConfig && (
        <OIDCModal
          isOpen={showOIDCModal}
          onClose={() => setShowOIDCModal(false)}
          config={oidcConfig}
          onSaved={loadOidcConfig}
        />
      )}
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
