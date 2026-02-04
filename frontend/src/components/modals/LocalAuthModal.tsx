import { useState } from 'react'
import { X, Shield, Info, AlertTriangle, Users, Key, CheckCircle, AlertCircle, Eye, EyeOff, Loader } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import api from '@/services/api'
import { passwordSchema, getPasswordStrength } from '@/schemas/auth'

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

interface LocalAuthModalProps {
  isOpen: boolean
  onClose: () => void
  authEverEnabled: boolean
  userCount: number
  users: User[]
  onShowUserManagement: () => void
  onShowAddUser: () => void
}

export default function LocalAuthModal({
  isOpen,
  onClose,
  authEverEnabled,
  userCount,
  users,
  onShowUserManagement,
  onShowAddUser,
}: LocalAuthModalProps) {
  const { isAuthenticated, isAdmin } = useAuth()

  // Password change state
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmNewPassword, setConfirmNewPassword] = useState('')
  const [showCurrentPassword, setShowCurrentPassword] = useState(false)
  const [showNewPassword, setShowNewPassword] = useState(false)
  const [showConfirmNewPassword, setShowConfirmNewPassword] = useState(false)
  const [passwordChangeLoading, setPasswordChangeLoading] = useState(false)
  const [passwordChangeMessage, setPasswordChangeMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null)

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

  // Reset form when modal closes
  const handleClose = () => {
    setCurrentPassword('')
    setNewPassword('')
    setConfirmNewPassword('')
    setPasswordChangeMessage(null)
    onClose()
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-garage-surface border border-garage-border rounded-lg max-w-lg w-full max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="p-6 border-b border-garage-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Shield className="w-6 h-6 text-primary" />
            <h2 className="text-xl font-bold text-garage-text">Local Authentication</h2>
          </div>
          <button onClick={handleClose} className="p-2 hover:bg-garage-muted rounded-lg transition-colors">
            <X className="w-5 h-5 text-garage-text-muted" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
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
                      onClick={() => {
                        handleClose()
                        onShowUserManagement()
                      }}
                      className="px-3 py-1.5 text-sm bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
                    >
                      Manage Users
                    </button>
                  </div>
                </div>
              )}

              {/* Quick user preview */}
              {users.length > 0 && (
                <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
                  <div className="flex items-center justify-between mb-3">
                    <div className="text-sm font-medium text-garage-text">
                      {userCount} {userCount === 1 ? 'User' : 'Users'}
                    </div>
                    <button
                      onClick={() => {
                        handleClose()
                        onShowAddUser()
                      }}
                      className="px-3 py-1.5 text-sm bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
                    >
                      Add User
                    </button>
                  </div>

                  {/* First 3 users preview */}
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
                        <label htmlFor="current-password-modal" className="block text-xs font-medium text-garage-text mb-1.5">
                          Current Password
                        </label>
                        <div className="relative">
                          <input
                            id="current-password-modal"
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
                        <label htmlFor="new-password-modal" className="block text-xs font-medium text-garage-text mb-1.5">
                          New Password
                        </label>
                        <div className="relative">
                          <input
                            id="new-password-modal"
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
                        <label htmlFor="confirm-new-password-modal" className="block text-xs font-medium text-garage-text mb-1.5">
                          Confirm New Password
                        </label>
                        <div className="relative">
                          <input
                            id="confirm-new-password-modal"
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
                        <label htmlFor="current-password-user-modal" className="block text-xs font-medium text-garage-text mb-1.5">
                          Current Password
                        </label>
                        <div className="relative">
                          <input
                            id="current-password-user-modal"
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
                        <label htmlFor="new-password-user-modal" className="block text-xs font-medium text-garage-text mb-1.5">
                          New Password
                        </label>
                        <div className="relative">
                          <input
                            id="new-password-user-modal"
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
                        <label htmlFor="confirm-new-password-user-modal" className="block text-xs font-medium text-garage-text mb-1.5">
                          Confirm New Password
                        </label>
                        <div className="relative">
                          <input
                            id="confirm-new-password-user-modal"
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

        {/* Footer */}
        <div className="p-4 border-t border-garage-border flex justify-end">
          <button
            onClick={handleClose}
            className="px-4 py-2 text-sm font-medium text-garage-text bg-garage-bg border border-garage-border rounded-lg hover:bg-garage-muted transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
