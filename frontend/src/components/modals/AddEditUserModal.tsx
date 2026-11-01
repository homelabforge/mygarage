import { useTranslation } from 'react-i18next'
import { useState, useEffect, useMemo, type SyntheticEvent } from 'react'
import { X, Eye, EyeOff } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/services/api'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'
import { Select } from '@/components/ui'
import { makePasswordSchema } from '@/schemas/auth'
import { RELATIONSHIP_PRESETS } from '@/types/family'
import type { User } from '@/types/user'

interface AddEditUserModalProps {
  isOpen: boolean
  onClose: () => void
  user?: User | null
  onSave: () => void
  currentUserId: number
  activeAdminCount: number
}

export default function AddEditUserModal({ isOpen, onClose, user, onSave, currentUserId, activeAdminCount }: AddEditUserModalProps) {
  const { t } = useTranslation('forms')
  const isEditMode = !!user
  const isOidc = isEditMode && user?.auth_method === 'oidc'
  // The last active admin can't be disabled, whoever it is, not only you.
  // The server refuses it too.
  const isLastActiveAdmin = !!user && user.is_admin && user.is_active && activeAdminCount === 1
  // You can't change your own role when you're that last admin. With auth on
  // it's the same as isLastActiveAdmin; with auth off the server refuses it.
  const isSelfLastActiveAdmin = isLastActiveAdmin && user?.id === currentUserId
  const [formData, setFormData] = useState({
    username: '',
    email: '',
    full_name: '',
    password: '',
    confirmPassword: '',
    is_admin: false,
    is_active: true,
    relationship: '' as string,
    relationship_custom: '',
  })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)

  // Zod bakes its messages in at construction, so the schema is rebuilt when
  // the language changes. It is only read inside the submit handler — it is
  // deliberately NOT a dependency of the reset effect below, which would wipe
  // the form on a language switch.
  const passwordSchema = useMemo(() => makePasswordSchema(t), [t])

  useEffect(() => {
    if (user) {
      setFormData({
        username: user.username,
        email: user.email,
        full_name: user.full_name || '',
        password: '',
        confirmPassword: '',
        is_admin: user.is_admin,
        is_active: user.is_active,
        relationship: user.relationship || '',
        relationship_custom: user.relationship_custom || '',
      })
    } else {
      setFormData({
        username: '',
        email: '',
        full_name: '',
        password: '',
        confirmPassword: '',
        is_admin: false,
        is_active: true,
        relationship: '',
        relationship_custom: '',
      })
    }
    setErrors({})
  }, [user, isOpen])

  const handleSubmit = async (e: SyntheticEvent<HTMLFormElement>) => {
    e.preventDefault()
    setErrors({})

    const validationErrors: Record<string, string> = {}

    // Validate password if provided (required for create, optional for edit)
    if (!isEditMode || formData.password) {
      try {
        passwordSchema.parse(formData.password)
      } catch (err) {
        // Zod 4.4.3's ZodError has no `.errors` property at all (only
        // `.issues` — `.errors` was a v3-only alias this codebase never ran
        // against), so reading `.errors` here always returned `undefined`
        // and this always fell through to the generic fallback message.
        const error = err as { issues?: Array<{ message: string }> }
        validationErrors.password =
          error.issues?.[0]?.message || t('common:validation.password.invalid')
      }

      if (formData.password !== formData.confirmPassword) {
        validationErrors.confirmPassword = t('common:validation.password.mismatch')
      }
    }

    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors)
      return
    }

    setLoading(true)

    try {
      if (isEditMode) {
        // The IdP resets an SSO user's name on every sign-in, so it isn't sent.
        // Nothing syncs their email, so an admin can change it. It's only sent
        // when changed, since the IdP's address can be one the server's email
        // check refuses (admin@localhost), and that would block every save.
        const emailChanged = formData.email !== user.email
        await api.put(`/auth/users/${user.id}`, {
          ...((!isOidc || emailChanged) && { email: formData.email }),
          ...(!isOidc && { full_name: formData.full_name || null }),
          is_active: formData.is_active,
          is_admin: formData.is_admin,
          relationship: formData.relationship || null,
          relationship_custom: formData.relationship === 'other' ? formData.relationship_custom || null : null,
        })

        // Update password separately if provided (never for OIDC)
        if (!isOidc && formData.password) {
          await api.put(`/auth/users/${user.id}/password`, {
            new_password: formData.password,
          })
        }

        toast.success(t('modal.userUpdated'))
      } else {
        // Create user
        const response = await api.post('/auth/users', {
          username: formData.username,
          email: formData.email,
          full_name: formData.full_name || null,
          password: formData.password,
          relationship: formData.relationship || null,
          relationship_custom: formData.relationship === 'other' ? formData.relationship_custom || null : null,
        })

        const newUserId = response.data.id

        // Activate and set admin if needed
        if (formData.is_active || formData.is_admin) {
          await api.put(`/auth/users/${newUserId}`, {
            is_active: formData.is_active,
            is_admin: formData.is_admin,
          })
        }

        toast.success(t('modal.userCreated'))
      }

      onSave()
      onClose()
    } catch (err) {
      const action = isEditMode ? t('modal.updateUserAction') : t('modal.createUserAction')
      toast.error(getActionErrorMessage(err, action))
    } finally {
      setLoading(false)
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-[60] p-4">
      <div className="bg-garage-surface border border-garage-border rounded-lg max-w-md w-full max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="p-6 border-b border-garage-border flex items-center justify-between sticky top-0 bg-garage-surface">
          <h2 className="text-xl font-bold text-garage-text">
            {isEditMode ? t('modal.editUser') : t('modal.addUser')}
          </h2>
          <button onClick={onClose} className="p-2 hover:bg-garage-surface-light rounded-lg transition-colors">
            <X className="w-5 h-5 text-garage-text-muted" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {/* Username */}
          <div>
            <label className="block text-sm font-medium text-garage-text mb-1.5">
              {t('modal.username')} {!isEditMode && <span className="text-danger">*</span>}
            </label>
            <input
              type="text"
              value={formData.username}
              onChange={(e) => setFormData({ ...formData, username: e.target.value })}
              disabled={isEditMode}
              required={!isEditMode}
              className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50 disabled:cursor-not-allowed"
            />
          </div>

          {/* Email */}
          <div>
            <label className="block text-sm font-medium text-garage-text mb-1.5">
              {t('modal.email')} <span className="text-danger">*</span>
            </label>
            {/* The IdP's address may not pass the browser's email check, and that
                would block every save. The server still checks a changed one. */}
            <input
              type={isOidc ? 'text' : 'email'}
              value={formData.email}
              onChange={(e) => setFormData({ ...formData, email: e.target.value })}
              required
              className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50 disabled:cursor-not-allowed"
            />
          </div>

          {/* Full Name */}
          <div>
            <label className="block text-sm font-medium text-garage-text mb-1.5">
              {t('modal.fullName')}
            </label>
            <input
              type="text"
              value={formData.full_name}
              onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
              disabled={isOidc}
              className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50 disabled:cursor-not-allowed"
            />
            {isOidc && <p className="text-xs text-garage-text-muted mt-1">{t('modal.managedByOidc')}</p>}
          </div>

          {/* Password (hidden for OIDC users) */}
          {!isOidc && (
            <div>
              <label className="block text-sm font-medium text-garage-text mb-1.5">
                {t('modal.password')} {!isEditMode && <span className="text-danger">*</span>}
                {isEditMode && <span className="text-xs text-garage-text-muted ml-2">({t('modal.leaveBlankToKeep')})</span>}
              </label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={formData.password}
                  onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                  required={!isEditMode}
                  className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary pr-10"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 hover:bg-garage-border rounded transition-colors"
                >
                  {showPassword ? <EyeOff className="w-4 h-4 text-garage-text-muted" /> : <Eye className="w-4 h-4 text-garage-text-muted" />}
                </button>
              </div>
              {errors.password && <p className="text-sm text-danger mt-1">{errors.password}</p>}
            </div>
          )}

          {/* Confirm Password (hidden for OIDC users) */}
          {!isOidc && (!isEditMode || formData.password) && (
            <div>
              <label className="block text-sm font-medium text-garage-text mb-1.5">
                {t('modal.confirmPassword')} <span className="text-danger">*</span>
              </label>
              <div className="relative">
                <input
                  type={showConfirmPassword ? 'text' : 'password'}
                  value={formData.confirmPassword}
                  onChange={(e) => setFormData({ ...formData, confirmPassword: e.target.value })}
                  required
                  className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary pr-10"
                />
                <button
                  type="button"
                  onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 hover:bg-garage-border rounded transition-colors"
                >
                  {showConfirmPassword ? <EyeOff className="w-4 h-4 text-garage-text-muted" /> : <Eye className="w-4 h-4 text-garage-text-muted" />}
                </button>
              </div>
              {errors.confirmPassword && <p className="text-sm text-danger mt-1">{errors.confirmPassword}</p>}
            </div>
          )}

          {/* Relationship */}
          <div>
            <label className="block text-sm font-medium text-garage-text mb-1.5">
              {t('modal.relationship')}
            </label>
            <Select
              value={formData.relationship}
              onChange={(e) => setFormData({ ...formData, relationship: e.target.value, relationship_custom: e.target.value !== 'other' ? '' : formData.relationship_custom })}
              placeholder={t('common:none')}
              options={RELATIONSHIP_PRESETS.map((preset) => ({ value: preset.value, label: t(preset.labelKey) }))}
            />
            <p className="text-xs text-garage-text-muted mt-1">
              {t('modal.relationshipHint')}
            </p>
          </div>

          {/* Custom Relationship (only when "Other" is selected) */}
          {formData.relationship === 'other' && (
            <div>
              <label className="block text-sm font-medium text-garage-text mb-1.5">
                {t('modal.customRelationship')}
              </label>
              <input
                type="text"
                value={formData.relationship_custom}
                onChange={(e) => setFormData({ ...formData, relationship_custom: e.target.value })}
                placeholder="e.g., Roommate, Neighbor, Coworker"
                maxLength={100}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>
          )}

          {/* Role */}
          <div>
            <label className="block text-sm font-medium text-garage-text mb-1.5">
              {t('modal.role')}
            </label>
            <Select
              value={formData.is_admin ? 'admin' : 'user'}
              onChange={(e) => setFormData({ ...formData, is_admin: e.target.value === 'admin' })}
              disabled={isSelfLastActiveAdmin}
              options={[
                { value: 'user', label: t('common:user') },
                { value: 'admin', label: t('common:admin') },
              ]}
            />
            {isSelfLastActiveAdmin && (
              <p className="text-xs text-warning mt-1">{t('modal.lastActiveAdminWarning')}</p>
            )}
          </div>

          {/* Active Status */}
          <div>
            <label className={`flex items-center gap-3 ${isLastActiveAdmin ? 'cursor-not-allowed' : 'cursor-pointer'}`}>
              <input
                type="checkbox"
                checked={formData.is_active}
                onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
                disabled={isLastActiveAdmin}
                className="w-4 h-4 accent-(--accent-solid) bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2 disabled:opacity-50 disabled:cursor-not-allowed"
              />
              <span className="text-sm font-medium text-garage-text">
                {t('modal.activeUser')}
              </span>
            </label>
            <p className="mt-1 ml-7 text-sm text-garage-text-muted">
              {t('modal.inactiveUsersCannotLogin')}
            </p>
            {isLastActiveAdmin && (
              <p className="mt-1 ml-7 text-xs text-warning">{t('modal.lastActiveAdminDisableWarning')}</p>
            )}
          </div>

          {/* OIDC Badge */}
          {isOidc && (
            <div className="p-3 bg-warning/10 border border-warning/30 rounded-lg">
              <p className="text-sm text-garage-text">
                <strong>{t('modal.oidcUser')}</strong> - {t('modal.oidcUserDescriptionEditable', { provider: user?.oidc_provider || t('modal.externalProvider') })}
              </p>
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 bg-garage-bg border border-garage-border rounded-lg hover:bg-garage-surface text-garage-text transition-colors"
            >
              {t('common:cancel')}
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex-1 px-4 py-2 bg-gray-700 border border-gray-600 hover:bg-gray-800 text-white rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? t('common:saving') : (isEditMode ? t('common:update') : t('common:create'))}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
