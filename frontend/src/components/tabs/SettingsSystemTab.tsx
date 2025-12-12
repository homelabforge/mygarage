import { useState, useCallback, useEffect } from 'react'
import { Server, CheckCircle, AlertCircle, Info, Shield, Users, AlertTriangle, Key, Wrench, Fuel, Bell, FileText, StickyNote, Camera, Sun, Moon, Eye, EyeOff, Loader, Ruler, Archive } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { useSettings } from '@/contexts/SettingsContext'
import { useTheme } from '@/contexts/ThemeContext'
import type { DashboardResponse } from '@/types/dashboard'
import api from '@/services/api'
import { passwordSchema, getPasswordStrength } from '@/schemas/auth'
import { toast } from 'sonner'
import UserManagementModal from '@/components/modals/UserManagementModal'
import AddEditUserModal from '@/components/modals/AddEditUserModal'
import DeleteUserModal from '@/components/modals/DeleteUserModal'
import ArchivedVehiclesList from '@/components/ArchivedVehiclesList'

type RawSetting = {
  key: string
  value?: string | null
}

interface User {
  id: number
  username: string
  email: string
  full_name: string | null
  is_active: boolean
  is_admin: boolean
  auth_method: 'local' | 'oidc'
  oidc_subject: string | null
  oidc_provider: string | null
  created_at: string
  updated_at: string
  last_login: string | null
}

export default function SettingsSystemTab() {
  const { isAuthenticated, isAdmin, user: currentUser } = useAuth()
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
    multi_user_enabled: 'false',
  })
  const [loadedFormData, setLoadedFormData] = useState<typeof formData | null>(null)
  const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null)
  const [showUserManagement, setShowUserManagement] = useState(false)
  const [userCount, setUserCount] = useState(0)
  const [authenticatorDetected, setAuthenticatorDetected] = useState<boolean | null>(null)
  const [authEverEnabled, setAuthEverEnabled] = useState(false)
  const [dashboardStats, setDashboardStats] = useState<DashboardResponse | null>(null)

  // Multi-user management state
  const [users, setUsers] = useState<User[]>([])
  const [showAddUserModal, setShowAddUserModal] = useState(false)
  const [showEditUserModal, setShowEditUserModal] = useState(false)
  const [showDeleteUserModal, setShowDeleteUserModal] = useState(false)
  const [selectedUser, setSelectedUser] = useState<User | null>(null)

  // Password change state
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmNewPassword, setConfirmNewPassword] = useState('')
  const [showCurrentPassword, setShowCurrentPassword] = useState(false)
  const [showNewPassword, setShowNewPassword] = useState(false)
  const [showConfirmNewPassword, setShowConfirmNewPassword] = useState(false)
  const [passwordChangeLoading, setPasswordChangeLoading] = useState(false)
  const [passwordChangeMessage, setPasswordChangeMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null)

  // OIDC configuration state
  const [oidcTestLoading, setOidcTestLoading] = useState(false)
  const [oidcTestResult, setOidcTestResult] = useState<{ success: boolean, message?: string, metadata?: object, errors?: string[] } | null>(null)
  const [showClientSecret, setShowClientSecret] = useState(false)

  // Unit preference state
  const [unitPreference, setUnitPreference] = useState<'imperial' | 'metric'>('imperial')
  const [showBothUnits, setShowBothUnits] = useState(false)
  const [unitPreferenceSaving, setUnitPreferenceSaving] = useState(false)

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
        multi_user_enabled: settingsMap.multi_user_enabled || 'false',
      }
      setFormData(newFormData)
      setLoadedFormData(newFormData)

      // Check user count to determine if auth has ever been enabled
      try {
        const countResponse = await api.get('/auth/users/count')
        const countData = countResponse.data
        setUserCount(countData.count || 0)
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

  // Load user's unit preferences
  useEffect(() => {
    if (currentUser) {
      // If authenticated, load from user profile
      setUnitPreference(currentUser.unit_preference || 'imperial')
      setShowBothUnits(currentUser.show_both_units || false)
    } else {
      // If not authenticated, load from localStorage
      const storedSystem = localStorage.getItem('unit_preference') as 'imperial' | 'metric' | null
      const storedShowBoth = localStorage.getItem('show_both_units') === 'true'
      setUnitPreference(storedSystem || 'imperial')
      setShowBothUnits(storedShowBoth)
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

  // Load users when multi-user is enabled
  const loadUsers = useCallback(async () => {
    if (formData.multi_user_enabled !== 'true') return

    try {
      const response = await api.get('/auth/users')
      setUsers(response.data)
      setUserCount(response.data.length)
    } catch (error) {
      console.error('Failed to load users:', error)
    }
  }, [formData.multi_user_enabled])

  useEffect(() => {
    if (formData.multi_user_enabled === 'true') {
      void loadUsers()
    }
  }, [formData.multi_user_enabled, loadUsers])

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

  // Handle password change
  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault()
    setPasswordChangeMessage(null)

    // Validation
    if (!currentPassword || !newPassword || !confirmNewPassword) {
      setPasswordChangeMessage({ type: 'error', text: 'All fields are required' })
      return
    }

    if (newPassword !== confirmNewPassword) {
      setPasswordChangeMessage({ type: 'error', text: 'New passwords do not match' })
      return
    }

    // Validate password strength using Zod schema
    try {
      passwordSchema.parse(newPassword)
    } catch (err) {
      if (err instanceof Error) {
        const zodError = err as { errors?: Array<{ message: string }> }
        const errorMessage = zodError.errors?.[0]?.message || 'Password does not meet requirements'
        setPasswordChangeMessage({ type: 'error', text: errorMessage })
      } else {
        setPasswordChangeMessage({ type: 'error', text: 'Password does not meet requirements' })
      }
      return
    }

    setPasswordChangeLoading(true)

    try {
      await api.put('/auth/me/password', {
        current_password: currentPassword,
        new_password: newPassword,
      })

      setPasswordChangeMessage({ type: 'success', text: 'Password changed successfully!' })

      // Clear form
      setCurrentPassword('')
      setNewPassword('')
      setConfirmNewPassword('')

      // Clear message after 5 seconds
      setTimeout(() => setPasswordChangeMessage(null), 5000)
    } catch (error) {
      if (error instanceof Error) {
        const apiError = error as { response?: { data?: { detail?: string } } }
        setPasswordChangeMessage({
          type: 'error',
          text: apiError.response?.data?.detail || 'Failed to change password. Please try again.'
        })
      } else {
        setPasswordChangeMessage({ type: 'error', text: 'Failed to change password. Please try again.' })
      }
    } finally {
      setPasswordChangeLoading(false)
    }
  }

  // Handle OIDC test connection
  const handleOIDCTest = async () => {
    setOidcTestLoading(true)
    setOidcTestResult(null)

    try {
      const response = await api.post('/auth/oidc/test', {
        issuer_url: formData.oidc_issuer_url,
        client_id: formData.oidc_client_id,
        client_secret: formData.oidc_client_secret,
      })

      setOidcTestResult({
        success: true,
        message: 'Connection successful! Provider metadata retrieved.',
        metadata: response.data.metadata || {},
      })
    } catch (error) {
      const apiError = error as { response?: { data?: { errors?: string[], detail?: string } } }
      setOidcTestResult({
        success: false,
        errors: apiError.response?.data?.errors || [apiError.response?.data?.detail || 'Failed to connect to OIDC provider'],
      })
    } finally {
      setOidcTestLoading(false)
    }
  }

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

        // Refresh user to update AuthContext
        await api.get('/auth/me')
      } else {
        // Save to localStorage if not authenticated
        localStorage.setItem('unit_preference', system)
      }

      toast.success('Unit preference saved!')
      // Force a re-render to update displays
      window.dispatchEvent(new Event('storage'))
    } catch (error) {
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

        // Refresh user to update AuthContext
        await api.get('/auth/me')
      } else {
        // Save to localStorage if not authenticated
        localStorage.setItem('show_both_units', showBoth.toString())
      }

      toast.success('Display preference saved!')
      // Force a re-render to update displays
      window.dispatchEvent(new Event('storage'))
    } catch (error) {
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

  // User management handlers
  const handleEditUser = (user: User) => {
    setSelectedUser(user)
    setShowEditUserModal(true)
  }

  const handleDeleteUser = (user: User) => {
    if (user.id === currentUser?.id) {
      toast.error('You cannot delete your own account')
      return
    }
    setSelectedUser(user)
    setShowDeleteUserModal(true)
  }

  const handleResetPassword = (user: User) => {
    if (user.auth_method === 'oidc') {
      toast.error('Cannot reset password for OIDC users')
      return
    }
    setSelectedUser(user)
    setShowEditUserModal(true)
  }

  const handleToggleActive = async (user: User) => {
    try {
      await api.put(`/auth/users/${user.id}`, {
        is_active: !user.is_active
      })
      toast.success(`User ${user.is_active ? 'disabled' : 'enabled'} successfully`)
      await loadUsers()
    } catch (err) {
      const error = err as { response?: { data?: { detail?: string } } }
      const detail = error.response?.data?.detail
      if (typeof detail === 'string') {
        toast.error(detail)
      } else {
        toast.error('Failed to update user status')
      }
    }
  }

  const handleUserSaved = () => {
    void loadUsers()
    setShowAddUserModal(false)
    setShowEditUserModal(false)
    setSelectedUser(null)
  }

  const handleUserDeleted = () => {
    void loadUsers()
    setShowDeleteUserModal(false)
    setSelectedUser(null)
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

  // Calculate active admin count for last admin protection
  const activeAdminCount = users.filter(u => u.is_admin && u.is_active).length

  return (
    <div className="space-y-6">
      {/* Fleet-wide Statistics */}
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
            label="Reminders"
            value={dashboardStats.total_reminders}
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

      {/* Multi-User Management Card */}
      {isAdmin && formData.auth_mode === 'local' && (
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6 space-y-6">
          {/* Header */}
          <div className="flex items-start gap-3">
            <Users className="w-6 h-6 text-primary mt-1" />
            <div className="flex-1">
              <h2 className="text-xl font-semibold text-garage-text mb-2">
                Multi-User Management
              </h2>
              <p className="text-sm text-garage-text-muted">
                Enable multi-user mode to create and manage additional user accounts.
              </p>
            </div>
          </div>

          {/* Toggle */}
          <div>
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={formData.multi_user_enabled === 'true'}
                onChange={(e) => setFormData({ ...formData, multi_user_enabled: e.target.checked ? 'true' : 'false' })}
                className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2"
              />
              <span className="text-sm font-medium text-garage-text">
                Enable multi-user mode
              </span>
            </label>
            <p className="mt-2 ml-7 text-sm text-garage-text-muted">
              {formData.multi_user_enabled === 'true'
                ? 'Multiple users can access MyGarage with separate accounts.'
                : 'Only the first admin account can access MyGarage.'
              }
            </p>
          </div>

          {/* User Management UI (only show when enabled) */}
          {formData.multi_user_enabled === 'true' && (
            <div className="border-t border-garage-border pt-4 space-y-4">
              {/* User count and quick preview */}
              <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
                <div className="flex items-center justify-between mb-3">
                  <div className="text-sm font-medium text-garage-text">
                    {userCount} {userCount === 1 ? 'User' : 'Users'}
                  </div>
                  <button
                    onClick={() => setShowAddUserModal(true)}
                    className="px-3 py-1.5 text-sm bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
                  >
                    Add User
                  </button>
                </div>

                {/* First 3 users preview */}
                {users.length > 0 && (
                  <div className="space-y-2">
                    {users.slice(0, 3).map((user) => (
                      <div key={user.id} className="flex items-center justify-between text-sm py-2 border-b border-garage-border last:border-0">
                        <div className="flex items-center gap-2">
                          <span className="text-garage-text">{user.username}</span>
                          {user.is_admin && (
                            <span className="px-1.5 py-0.5 text-xs bg-primary/20 text-primary rounded">Admin</span>
                          )}
                          {user.auth_method === 'oidc' && (
                            <span className="px-1.5 py-0.5 text-xs bg-warning/20 text-warning rounded">OIDC</span>
                          )}
                          {!user.is_active && (
                            <span className="px-1.5 py-0.5 text-xs bg-danger/20 text-danger rounded">Inactive</span>
                          )}
                        </div>
                        <span className="text-garage-text-muted text-xs">{user.email}</span>
                      </div>
                    ))}
                    {userCount > 3 && (
                      <div className="text-xs text-garage-text-muted text-center pt-2">
                        + {userCount - 3} more users
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Manage All Users button */}
              <button
                onClick={() => setShowUserManagement(true)}
                className="w-full px-4 py-2 bg-garage-surface border border-garage-border text-garage-text rounded-lg hover:bg-garage-bg transition-colors"
              >
                Manage All Users
              </button>
            </div>
          )}
        </div>
      )}

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
              Local JWT
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

          {/* Local JWT Mode Content */}
          {formData.auth_mode === 'local' && (
            <div className="space-y-4">
              {/* Case 1: Auth never enabled - show registration option */}
              {!authEverEnabled && (
                <div className="p-4 bg-primary/10 border border-primary/30 rounded-lg">
                  <div className="flex items-start gap-3">
                    <Info className="w-5 h-5 text-primary flex-shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <strong className="font-semibold text-garage-text">Enable Local Authentication</strong>
                      <p className="mt-1 text-sm text-garage-text">
                        Local authentication is currently not set up. Register the first user to enable authentication.
                      </p>
                      <p className="mt-2 text-xs text-garage-text-muted">
                        The first registered user will automatically become an administrator.
                      </p>
                      <a
                        href="/register"
                        className="mt-3 inline-flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors text-sm font-medium"
                      >
                        Register First User
                      </a>
                    </div>
                  </div>
                </div>
              )}

              {/* Case 2: Auth enabled, user is admin */}
              {authEverEnabled && isAdmin && isAuthenticated && (
                <>
                  {/* User Management Section - Only show if multiple users */}
                  {userCount > 1 && (
                    <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          <Users className="w-5 h-5 text-primary" />
                          <div>
                            <div className="text-sm font-medium text-garage-text">User Management</div>
                            <div className="text-xs text-garage-text-muted mt-0.5">
                              {userCount} registered users
                            </div>
                          </div>
                        </div>
                        <button
                          onClick={() => setShowUserManagement(true)}
                          className="px-3 py-1.5 text-sm bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
                        >
                          Manage Users
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Change Password Section */}
                  <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
                    <div className="flex items-start gap-3">
                      <Key className="w-5 h-5 text-primary flex-shrink-0 mt-0.5" />
                      <div className="flex-1">
                        <div className="text-sm font-medium text-garage-text mb-4">Change Password</div>

                        <form onSubmit={handlePasswordChange} className="space-y-4">
                          {/* Password Change Message */}
                          {passwordChangeMessage && (
                            <div className={`p-3 rounded-lg border flex items-start gap-2 text-sm ${
                              passwordChangeMessage.type === 'success'
                                ? 'bg-success-500/10 border-success-500 text-success-500'
                                : 'bg-danger-500/10 border-danger-500 text-danger-500'
                            }`}>
                              {passwordChangeMessage.type === 'success' ? (
                                <CheckCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                              ) : (
                                <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                              )}
                              <div className="flex-1">{passwordChangeMessage.text}</div>
                            </div>
                          )}

                          {/* Current Password */}
                          <div>
                            <label htmlFor="current-password" className="block text-xs font-medium text-garage-text mb-1.5">
                              Current Password
                            </label>
                            <div className="relative">
                              <input
                                id="current-password"
                                type={showCurrentPassword ? 'text' : 'password'}
                                value={currentPassword}
                                onChange={(e) => setCurrentPassword(e.target.value)}
                                className="w-full px-3 py-2 pr-10 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                                placeholder="Enter current password"
                                autoComplete="current-password"
                                disabled={passwordChangeLoading}
                              />
                              <button
                                type="button"
                                onClick={() => setShowCurrentPassword(!showCurrentPassword)}
                                className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-garage-text-muted hover:text-garage-text transition-colors"
                                aria-label={showCurrentPassword ? 'Hide password' : 'Show password'}
                                tabIndex={-1}
                              >
                                {showCurrentPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                              </button>
                            </div>
                          </div>

                          {/* New Password */}
                          <div>
                            <label htmlFor="new-password" className="block text-xs font-medium text-garage-text mb-1.5">
                              New Password
                            </label>
                            <div className="relative">
                              <input
                                id="new-password"
                                type={showNewPassword ? 'text' : 'password'}
                                value={newPassword}
                                onChange={(e) => setNewPassword(e.target.value)}
                                className="w-full px-3 py-2 pr-10 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                                placeholder="Enter new password"
                                autoComplete="new-password"
                                disabled={passwordChangeLoading}
                              />
                              <button
                                type="button"
                                onClick={() => setShowNewPassword(!showNewPassword)}
                                className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-garage-text-muted hover:text-garage-text transition-colors"
                                aria-label={showNewPassword ? 'Hide password' : 'Show password'}
                                tabIndex={-1}
                              >
                                {showNewPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                              </button>
                            </div>

                            {/* Password Strength Indicator */}
                            {newPassword && (
                              <div className="mt-2">
                                <div className="flex items-center gap-2 mb-1">
                                  <div className="flex-1 h-1 bg-garage-surface rounded-full overflow-hidden">
                                    <div
                                      className={`h-full transition-all duration-300 ${
                                        getPasswordStrength(newPassword).color.replace('text-', 'bg-')
                                      }`}
                                      style={{ width: `${(getPasswordStrength(newPassword).score / 6) * 100}%` }}
                                    />
                                  </div>
                                  <span className={`text-xs font-medium ${getPasswordStrength(newPassword).color}`}>
                                    {getPasswordStrength(newPassword).label}
                                  </span>
                                </div>
                                <p className="text-xs text-garage-text-muted">
                                  Must have: 8+ chars, uppercase, lowercase, number, special char (!@#$...)
                                </p>
                              </div>
                            )}
                          </div>

                          {/* Confirm New Password */}
                          <div>
                            <label htmlFor="confirm-new-password" className="block text-xs font-medium text-garage-text mb-1.5">
                              Confirm New Password
                            </label>
                            <div className="relative">
                              <input
                                id="confirm-new-password"
                                type={showConfirmNewPassword ? 'text' : 'password'}
                                value={confirmNewPassword}
                                onChange={(e) => setConfirmNewPassword(e.target.value)}
                                className="w-full px-3 py-2 pr-10 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                                placeholder="Confirm new password"
                                autoComplete="new-password"
                                disabled={passwordChangeLoading}
                              />
                              <button
                                type="button"
                                onClick={() => setShowConfirmNewPassword(!showConfirmNewPassword)}
                                className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-garage-text-muted hover:text-garage-text transition-colors"
                                aria-label={showConfirmNewPassword ? 'Hide password' : 'Show password'}
                                tabIndex={-1}
                              >
                                {showConfirmNewPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                              </button>
                            </div>
                          </div>

                          {/* Submit Button */}
                          <button
                            type="submit"
                            disabled={passwordChangeLoading}
                            className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-gray-700 border border-gray-600 hover:bg-gray-800 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            {passwordChangeLoading ? (
                              <>
                                <Loader className="w-4 h-4 animate-spin" />
                                Changing Password...
                              </>
                            ) : (
                              <>
                                <Key className="w-4 h-4" />
                                Change Password
                              </>
                            )}
                          </button>
                        </form>
                      </div>
                    </div>
                  </div>
                </>
              )}

              {/* Case 3: Auth enabled, user is regular user (logged in) */}
              {authEverEnabled && !isAdmin && isAuthenticated && (
                <>
                  <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
                    <div className="flex items-start gap-3">
                      <AlertCircle className="w-5 h-5 text-garage-text-muted flex-shrink-0 mt-0.5" />
                      <div className="text-sm text-garage-text-muted">
                        <strong>Authentication Mode - Admin Function Only</strong>
                        <p className="mt-1">
                          Changing authentication settings requires administrator privileges. Contact your administrator for account management or authentication changes.
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* Change Password Section for Regular Users */}
                  <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
                    <div className="flex items-start gap-3">
                      <Key className="w-5 h-5 text-primary flex-shrink-0 mt-0.5" />
                      <div className="flex-1">
                        <div className="text-sm font-medium text-garage-text mb-4">Change Password</div>

                        <form onSubmit={handlePasswordChange} className="space-y-4">
                          {/* Password Change Message */}
                          {passwordChangeMessage && (
                            <div className={`p-3 rounded-lg border flex items-start gap-2 text-sm ${
                              passwordChangeMessage.type === 'success'
                                ? 'bg-success-500/10 border-success-500 text-success-500'
                                : 'bg-danger-500/10 border-danger-500 text-danger-500'
                            }`}>
                              {passwordChangeMessage.type === 'success' ? (
                                <CheckCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                              ) : (
                                <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                              )}
                              <div className="flex-1">{passwordChangeMessage.text}</div>
                            </div>
                          )}

                          {/* Current Password */}
                          <div>
                            <label htmlFor="current-password-user" className="block text-xs font-medium text-garage-text mb-1.5">
                              Current Password
                            </label>
                            <div className="relative">
                              <input
                                id="current-password-user"
                                type={showCurrentPassword ? 'text' : 'password'}
                                value={currentPassword}
                                onChange={(e) => setCurrentPassword(e.target.value)}
                                className="w-full px-3 py-2 pr-10 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                                placeholder="Enter current password"
                                autoComplete="current-password"
                                disabled={passwordChangeLoading}
                              />
                              <button
                                type="button"
                                onClick={() => setShowCurrentPassword(!showCurrentPassword)}
                                className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-garage-text-muted hover:text-garage-text transition-colors"
                                aria-label={showCurrentPassword ? 'Hide password' : 'Show password'}
                                tabIndex={-1}
                              >
                                {showCurrentPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                              </button>
                            </div>
                          </div>

                          {/* New Password */}
                          <div>
                            <label htmlFor="new-password-user" className="block text-xs font-medium text-garage-text mb-1.5">
                              New Password
                            </label>
                            <div className="relative">
                              <input
                                id="new-password-user"
                                type={showNewPassword ? 'text' : 'password'}
                                value={newPassword}
                                onChange={(e) => setNewPassword(e.target.value)}
                                className="w-full px-3 py-2 pr-10 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                                placeholder="Enter new password"
                                autoComplete="new-password"
                                disabled={passwordChangeLoading}
                              />
                              <button
                                type="button"
                                onClick={() => setShowNewPassword(!showNewPassword)}
                                className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-garage-text-muted hover:text-garage-text transition-colors"
                                aria-label={showNewPassword ? 'Hide password' : 'Show password'}
                                tabIndex={-1}
                              >
                                {showNewPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                              </button>
                            </div>

                            {/* Password Strength Indicator */}
                            {newPassword && (
                              <div className="mt-2">
                                <div className="flex items-center gap-2 mb-1">
                                  <div className="flex-1 h-1 bg-garage-surface rounded-full overflow-hidden">
                                    <div
                                      className={`h-full transition-all duration-300 ${
                                        getPasswordStrength(newPassword).color.replace('text-', 'bg-')
                                      }`}
                                      style={{ width: `${(getPasswordStrength(newPassword).score / 6) * 100}%` }}
                                    />
                                  </div>
                                  <span className={`text-xs font-medium ${getPasswordStrength(newPassword).color}`}>
                                    {getPasswordStrength(newPassword).label}
                                  </span>
                                </div>
                                <p className="text-xs text-garage-text-muted">
                                  Must have: 8+ chars, uppercase, lowercase, number, special char (!@#$...)
                                </p>
                              </div>
                            )}
                          </div>

                          {/* Confirm New Password */}
                          <div>
                            <label htmlFor="confirm-new-password-user" className="block text-xs font-medium text-garage-text mb-1.5">
                              Confirm New Password
                            </label>
                            <div className="relative">
                              <input
                                id="confirm-new-password-user"
                                type={showConfirmNewPassword ? 'text' : 'password'}
                                value={confirmNewPassword}
                                onChange={(e) => setConfirmNewPassword(e.target.value)}
                                className="w-full px-3 py-2 pr-10 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                                placeholder="Confirm new password"
                                autoComplete="new-password"
                                disabled={passwordChangeLoading}
                              />
                              <button
                                type="button"
                                onClick={() => setShowConfirmNewPassword(!showConfirmNewPassword)}
                                className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-garage-text-muted hover:text-garage-text transition-colors"
                                aria-label={showConfirmNewPassword ? 'Hide password' : 'Show password'}
                                tabIndex={-1}
                              >
                                {showConfirmNewPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                              </button>
                            </div>
                          </div>

                          {/* Submit Button */}
                          <button
                            type="submit"
                            disabled={passwordChangeLoading}
                            className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-gray-700 border border-gray-600 hover:bg-gray-800 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            {passwordChangeLoading ? (
                              <>
                                <Loader className="w-4 h-4 animate-spin" />
                                Changing Password...
                              </>
                            ) : (
                              <>
                                <Key className="w-4 h-4" />
                                Change Password
                              </>
                            )}
                          </button>
                        </form>
                      </div>
                    </div>
                  </div>
                </>
              )}

              {/* Case 4: Auth enabled, user not logged in */}
              {authEverEnabled && !isAuthenticated && (
                <div className="p-4 bg-warning-500/10 border border-warning-500/30 rounded-lg">
                  <div className="flex items-start gap-3">
                    <AlertTriangle className="w-5 h-5 text-warning-500 flex-shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <strong className="font-semibold text-warning-500">Authentication Required</strong>
                      <p className="mt-1 text-sm text-garage-text">
                        Local authentication is enabled. You must be logged in as an administrator to manage authentication settings.
                      </p>
                      <a
                        href="/login"
                        className="mt-3 inline-flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors text-sm font-medium"
                      >
                        Login
                      </a>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* OIDC Mode Content */}
          {formData.auth_mode === 'oidc' && (
            <div className="space-y-4">
              {/* OIDC Info Box */}
              <div className="p-4 bg-primary/10 border border-primary/30 rounded-lg">
                <div className="flex items-start gap-3">
                  <Info className="w-5 h-5 text-primary flex-shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <strong className="text-sm font-semibold text-garage-text">OpenID Connect (OIDC) Authentication</strong>
                    <div className="text-sm text-garage-text space-y-2 mt-2">
                      <p>
                        Configure single sign-on with your identity provider. Supported providers include:
                      </p>
                      <ul className="list-disc list-inside ml-2 text-xs space-y-1 text-garage-text-muted">
                        <li>Authentik</li>
                        <li>Keycloak</li>
                        <li>Auth0</li>
                        <li>Okta</li>
                        <li>Azure AD / Entra ID</li>
                        <li>Google Workspace</li>
                      </ul>
                    </div>
                  </div>
                </div>
              </div>

              {/* OIDC Configuration Form */}
              <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
                <div className="space-y-4">
                  <h3 className="text-sm font-semibold text-garage-text">OIDC Configuration</h3>

                  {/* Provider Name */}
                  <div>
                    <label htmlFor="oidc-provider-name" className="block text-xs font-medium text-garage-text mb-1.5">
                      Provider Name
                    </label>
                    <input
                      id="oidc-provider-name"
                      type="text"
                      value={formData.oidc_provider_name}
                      onChange={(e) => setFormData({ ...formData, oidc_provider_name: e.target.value })}
                      className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                      placeholder="e.g., Authentik, Keycloak"
                    />
                    <p className="text-xs text-garage-text-muted mt-1">Display name for the SSO provider</p>
                  </div>

                  {/* Issuer URL */}
                  <div>
                    <label htmlFor="oidc-issuer-url" className="block text-xs font-medium text-garage-text mb-1.5">
                      Issuer URL <span className="text-danger-500">*</span>
                    </label>
                    <input
                      id="oidc-issuer-url"
                      type="url"
                      value={formData.oidc_issuer_url}
                      onChange={(e) => setFormData({ ...formData, oidc_issuer_url: e.target.value })}
                      className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                      placeholder="https://auth.example.com/application/o/mygarage/"
                    />
                    <p className="text-xs text-garage-text-muted mt-1">
                      OIDC provider's issuer URL (must end with /.well-known/openid-configuration)
                    </p>
                  </div>

                  {/* Client ID */}
                  <div>
                    <label htmlFor="oidc-client-id" className="block text-xs font-medium text-garage-text mb-1.5">
                      Client ID <span className="text-danger-500">*</span>
                    </label>
                    <input
                      id="oidc-client-id"
                      type="text"
                      value={formData.oidc_client_id}
                      onChange={(e) => setFormData({ ...formData, oidc_client_id: e.target.value })}
                      className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                      placeholder="client-id-from-provider"
                    />
                  </div>

                  {/* Client Secret */}
                  <div>
                    <label htmlFor="oidc-client-secret" className="block text-xs font-medium text-garage-text mb-1.5">
                      Client Secret <span className="text-danger-500">*</span>
                    </label>
                    <div className="relative">
                      <input
                        id="oidc-client-secret"
                        type={showClientSecret ? 'text' : 'password'}
                        value={formData.oidc_client_secret}
                        onChange={(e) => setFormData({ ...formData, oidc_client_secret: e.target.value })}
                        className="w-full px-3 py-2 pr-10 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                        placeholder="client-secret-from-provider"
                      />
                      <button
                        type="button"
                        onClick={() => setShowClientSecret(!showClientSecret)}
                        className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-garage-text-muted hover:text-garage-text transition-colors"
                        aria-label={showClientSecret ? 'Hide secret' : 'Show secret'}
                      >
                        {showClientSecret ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                    </div>
                    <p className="text-xs text-garage-text-muted mt-1">Encrypted and stored securely</p>
                  </div>

                  {/* Redirect URI (Read-only) */}
                  <div>
                    <label htmlFor="oidc-redirect-uri" className="block text-xs font-medium text-garage-text mb-1.5">
                      Redirect URI (Configure in provider)
                    </label>
                    <div className="relative">
                      <input
                        id="oidc-redirect-uri"
                        type="text"
                        value={`${window.location.origin}/api/auth/oidc/callback`}
                        readOnly
                        className="w-full px-3 py-2 bg-garage-surface/50 border border-garage-border rounded-lg text-sm text-garage-text-muted font-mono cursor-default"
                      />
                    </div>
                    <p className="text-xs text-garage-text-muted mt-1">
                      Copy this URL to your OIDC provider's redirect URI configuration
                    </p>
                  </div>

                  {/* Scopes */}
                  <div>
                    <label htmlFor="oidc-scopes" className="block text-xs font-medium text-garage-text mb-1.5">
                      Scopes
                    </label>
                    <input
                      id="oidc-scopes"
                      type="text"
                      value={formData.oidc_scopes}
                      onChange={(e) => setFormData({ ...formData, oidc_scopes: e.target.value })}
                      className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                      placeholder="openid profile email"
                    />
                    <p className="text-xs text-garage-text-muted mt-1">Space-separated list of OIDC scopes</p>
                  </div>

                  {/* Auto-create Users */}
                  <div className="flex items-start gap-3">
                    <input
                      id="oidc-auto-create"
                      type="checkbox"
                      checked={formData.oidc_auto_create_users === 'true'}
                      onChange={(e) => setFormData({ ...formData, oidc_auto_create_users: e.target.checked ? 'true' : 'false' })}
                      className="mt-1 w-4 h-4 text-primary bg-garage-surface border-garage-border rounded focus:ring-2 focus:ring-primary"
                    />
                    <div className="flex-1">
                      <label htmlFor="oidc-auto-create" className="text-xs font-medium text-garage-text cursor-pointer">
                        Auto-create users on first login
                      </label>
                      <p className="text-xs text-garage-text-muted mt-0.5">
                        Automatically create new users when they login via SSO for the first time
                      </p>
                    </div>
                  </div>

                  {/* Admin Group */}
                  <div>
                    <label htmlFor="oidc-admin-group" className="block text-xs font-medium text-garage-text mb-1.5">
                      Admin Group (Optional)
                    </label>
                    <input
                      id="oidc-admin-group"
                      type="text"
                      value={formData.oidc_admin_group}
                      onChange={(e) => setFormData({ ...formData, oidc_admin_group: e.target.value })}
                      className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text placeholder-garage-text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                      placeholder="mygarage-admins"
                    />
                    <p className="text-xs text-garage-text-muted mt-1">
                      Users in this group will be granted admin privileges
                    </p>
                  </div>

                  {/* Claim Mappings */}
                  <div className="space-y-3 pt-2 border-t border-garage-border">
                    <h4 className="text-xs font-semibold text-garage-text">Claim Mappings</h4>

                    {/* Username Claim */}
                    <div>
                      <label htmlFor="oidc-username-claim" className="block text-xs font-medium text-garage-text mb-1.5">
                        Username Claim
                      </label>
                      <select
                        id="oidc-username-claim"
                        value={formData.oidc_username_claim}
                        onChange={(e) => setFormData({ ...formData, oidc_username_claim: e.target.value })}
                        className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                      >
                        <option value="preferred_username">preferred_username</option>
                        <option value="email">email</option>
                        <option value="sub">sub</option>
                      </select>
                    </div>

                    {/* Email Claim */}
                    <div>
                      <label htmlFor="oidc-email-claim" className="block text-xs font-medium text-garage-text mb-1.5">
                        Email Claim
                      </label>
                      <select
                        id="oidc-email-claim"
                        value={formData.oidc_email_claim}
                        onChange={(e) => setFormData({ ...formData, oidc_email_claim: e.target.value })}
                        className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                      >
                        <option value="email">email</option>
                        <option value="mail">mail</option>
                      </select>
                    </div>

                    {/* Full Name Claim */}
                    <div>
                      <label htmlFor="oidc-full-name-claim" className="block text-xs font-medium text-garage-text mb-1.5">
                        Full Name Claim
                      </label>
                      <select
                        id="oidc-full-name-claim"
                        value={formData.oidc_full_name_claim}
                        onChange={(e) => setFormData({ ...formData, oidc_full_name_claim: e.target.value })}
                        className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded-lg text-sm text-garage-text focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                      >
                        <option value="name">name</option>
                        <option value="given_name">given_name + family_name</option>
                      </select>
                    </div>
                  </div>

                  {/* Test Connection Result */}
                  {oidcTestResult && (
                    <div className={`p-3 rounded-lg border text-sm ${
                      oidcTestResult.success
                        ? 'bg-success-500/10 border-success-500'
                        : 'bg-danger-500/10 border-danger-500'
                    }`}>
                      <div className="flex items-start gap-2">
                        {oidcTestResult.success ? (
                          <CheckCircle className="w-4 h-4 text-success-500 flex-shrink-0 mt-0.5" />
                        ) : (
                          <AlertCircle className="w-4 h-4 text-danger-500 flex-shrink-0 mt-0.5" />
                        )}
                        <div className="flex-1">
                          {oidcTestResult.success ? (
                            <>
                              <div className="font-medium text-success-500">{oidcTestResult.message}</div>
                              {oidcTestResult.metadata && (
                                <pre className="mt-2 text-xs bg-garage-bg p-2 rounded overflow-x-auto text-garage-text">
                                  {JSON.stringify(oidcTestResult.metadata, null, 2)}
                                </pre>
                              )}
                            </>
                          ) : (
                            <>
                              <div className="font-medium text-danger-500 mb-1">Connection Failed</div>
                              <ul className="text-xs text-danger-500 space-y-1">
                                {oidcTestResult.errors?.map((err, idx) => (
                                  <li key={idx}>• {err}</li>
                                ))}
                              </ul>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Action Buttons */}
                  <div className="flex gap-2 pt-2">
                    <button
                      type="button"
                      onClick={handleOIDCTest}
                      disabled={oidcTestLoading || !formData.oidc_issuer_url || !formData.oidc_client_id || !formData.oidc_client_secret}
                      className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-garage-surface border border-garage-border text-garage-text text-sm font-medium rounded-lg hover:bg-garage-bg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {oidcTestLoading ? (
                        <>
                          <Loader className="w-4 h-4 animate-spin" />
                          Testing...
                        </>
                      ) : (
                        <>
                          <CheckCircle className="w-4 h-4" />
                          Test Connection
                        </>
                      )}
                    </button>
                  </div>
                </div>
              </div>

              {/* Authentik Setup Instructions */}
              <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
                <div className="flex items-start gap-3">
                  <Info className="w-5 h-5 text-primary flex-shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <h4 className="text-sm font-semibold text-garage-text mb-2">Authentik Setup Guide</h4>
                    <ol className="list-decimal list-inside space-y-1.5 text-xs text-garage-text-muted">
                      <li>In Authentik, create a new OAuth2/OIDC Provider</li>
                      <li>Set Client Type to "Confidential"</li>
                      <li>Copy the Redirect URI shown above to the provider's configuration</li>
                      <li>Configure Scopes: openid, profile, email</li>
                      <li>Copy the Client ID and Client Secret to the fields above</li>
                      <li>Click "Test Connection" to verify configuration</li>
                      <li>Save the settings to enable OIDC authentication</li>
                    </ol>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
      </div>
      </div>

      {/* User Management Modal */}
      <UserManagementModal
        isOpen={showUserManagement}
        onClose={() => setShowUserManagement(false)}
        currentUserId={currentUser?.id || 0}
        onEditUser={handleEditUser}
        onDeleteUser={handleDeleteUser}
        onResetPassword={handleResetPassword}
        onToggleActive={handleToggleActive}
      />

      {/* Add User Modal */}
      <AddEditUserModal
        isOpen={showAddUserModal}
        onClose={() => setShowAddUserModal(false)}
        user={null}
        onSave={handleUserSaved}
        currentUserId={currentUser?.id || 0}
        activeAdminCount={activeAdminCount}
      />

      {/* Edit User Modal */}
      <AddEditUserModal
        isOpen={showEditUserModal}
        onClose={() => setShowEditUserModal(false)}
        user={selectedUser}
        onSave={handleUserSaved}
        currentUserId={currentUser?.id || 0}
        activeAdminCount={activeAdminCount}
      />

      {/* Delete User Modal */}
      <DeleteUserModal
        isOpen={showDeleteUserModal}
        onClose={() => setShowDeleteUserModal(false)}
        user={selectedUser}
        onConfirm={handleUserDeleted}
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
