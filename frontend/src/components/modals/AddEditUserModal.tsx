import { useState, useEffect } from 'react'
import { X, Eye, EyeOff } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/services/api'
import { passwordSchema } from '@/schemas/auth'

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
}

interface AddEditUserModalProps {
  isOpen: boolean
  onClose: () => void
  user?: User | null
  onSave: () => void
  currentUserId: number
  activeAdminCount: number
}

export default function AddEditUserModal({ isOpen, onClose, user, onSave, currentUserId, activeAdminCount }: AddEditUserModalProps) {
  const isEditMode = !!user
  const [formData, setFormData] = useState({
    username: '',
    email: '',
    full_name: '',
    password: '',
    confirmPassword: '',
    is_admin: false,
    is_active: true,
  })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)

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
      })
    }
    setErrors({})
  }, [user, isOpen])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setErrors({})

    const validationErrors: Record<string, string> = {}

    // Validate password if provided (required for create, optional for edit)
    if (!isEditMode || formData.password) {
      try {
        passwordSchema.parse(formData.password)
      } catch (err) {
        const error = err as { errors?: Array<{ message: string }> }
        validationErrors.password = error.errors?.[0]?.message || 'Invalid password'
      }

      if (formData.password !== formData.confirmPassword) {
        validationErrors.confirmPassword = 'Passwords do not match'
      }
    }

    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors)
      return
    }

    setLoading(true)

    try {
      if (isEditMode) {
        // Update user
        await api.put(`/auth/users/${user.id}`, {
          email: formData.email,
          full_name: formData.full_name || null,
          is_admin: formData.is_admin,
          is_active: formData.is_active,
        })

        // Update password separately if provided
        if (formData.password) {
          await api.put(`/auth/users/${user.id}/password`, {
            new_password: formData.password,
          })
        }

        toast.success('User updated successfully')
      } else {
        // Create user
        const response = await api.post('/auth/users', {
          username: formData.username,
          email: formData.email,
          full_name: formData.full_name || null,
          password: formData.password,
        })

        const newUserId = response.data.id

        // Activate and set admin if needed
        if (formData.is_active || formData.is_admin) {
          await api.put(`/auth/users/${newUserId}`, {
            is_active: formData.is_active,
            is_admin: formData.is_admin,
          })
        }

        toast.success('User created successfully')
      }

      onSave()
      onClose()
    } catch (err) {
      const error = err as { response?: { data?: { detail?: string } } }
      const detail = error.response?.data?.detail
      if (typeof detail === 'string') {
        toast.error(detail)
      } else {
        toast.error(isEditMode ? 'Failed to update user' : 'Failed to create user')
      }
    } finally {
      setLoading(false)
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-garage-surface border border-garage-border rounded-lg max-w-md w-full max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="p-6 border-b border-garage-border flex items-center justify-between sticky top-0 bg-garage-surface">
          <h2 className="text-xl font-bold text-garage-text">
            {isEditMode ? 'Edit User' : 'Add User'}
          </h2>
          <button onClick={onClose} className="p-2 hover:bg-garage-muted rounded-lg transition-colors">
            <X className="w-5 h-5 text-garage-text-muted" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {/* Username */}
          <div>
            <label className="block text-sm font-medium text-garage-text mb-1.5">
              Username {!isEditMode && <span className="text-danger">*</span>}
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
              Email <span className="text-danger">*</span>
            </label>
            <input
              type="email"
              value={formData.email}
              onChange={(e) => setFormData({ ...formData, email: e.target.value })}
              required
              className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>

          {/* Full Name */}
          <div>
            <label className="block text-sm font-medium text-garage-text mb-1.5">
              Full Name
            </label>
            <input
              type="text"
              value={formData.full_name}
              onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
              className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>

          {/* Password */}
          <div>
            <label className="block text-sm font-medium text-garage-text mb-1.5">
              Password {!isEditMode && <span className="text-danger">*</span>}
              {isEditMode && <span className="text-xs text-garage-text-muted ml-2">(leave blank to keep current)</span>}
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

          {/* Confirm Password */}
          {(!isEditMode || formData.password) && (
            <div>
              <label className="block text-sm font-medium text-garage-text mb-1.5">
                Confirm Password <span className="text-danger">*</span>
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

          {/* Role */}
          <div>
            <label className="block text-sm font-medium text-garage-text mb-1.5">
              Role
            </label>
            <select
              value={formData.is_admin ? 'admin' : 'user'}
              onChange={(e) => setFormData({ ...formData, is_admin: e.target.value === 'admin' })}
              disabled={isEditMode && user?.id === currentUserId && user?.is_admin && user?.is_active && activeAdminCount === 1}
              className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <option value="user">User</option>
              <option value="admin">Admin</option>
            </select>
            {isEditMode && user?.id === currentUserId && user?.is_admin && user?.is_active && activeAdminCount === 1 && (
              <p className="text-xs text-warning mt-1">Cannot change role - you are the last active admin</p>
            )}
          </div>

          {/* Active Status */}
          <div>
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={formData.is_active}
                onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
                className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2"
              />
              <span className="text-sm font-medium text-garage-text">
                Active User
              </span>
            </label>
            <p className="mt-1 ml-7 text-sm text-garage-text-muted">
              Inactive users cannot log in
            </p>
          </div>

          {/* OIDC Badge */}
          {user?.auth_method === 'oidc' && (
            <div className="p-3 bg-warning/10 border border-warning/30 rounded-lg">
              <p className="text-sm text-garage-text">
                <strong>OIDC User</strong> - Password managed by {user.oidc_provider || 'identity provider'}
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
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex-1 px-4 py-2 bg-gray-700 border border-gray-600 hover:bg-gray-800 text-white rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? 'Saving...' : (isEditMode ? 'Update' : 'Create')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
