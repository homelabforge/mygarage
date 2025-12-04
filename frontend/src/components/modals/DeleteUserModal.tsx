import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/services/api'

interface User {
  id: number
  username: string
  email: string
  is_admin: boolean
}

interface DeleteUserModalProps {
  isOpen: boolean
  onClose: () => void
  user: User | null
  onConfirm: () => void
}

export default function DeleteUserModal({ isOpen, onClose, user, onConfirm }: DeleteUserModalProps) {
  const [confirmText, setConfirmText] = useState('')
  const [loading, setLoading] = useState(false)

  const handleDelete = async () => {
    if (confirmText !== 'DELETE' || !user) return

    setLoading(true)
    try {
      await api.delete(`/auth/users/${user.id}`)
      toast.success('User deleted successfully')
      onConfirm()
      onClose()
      setConfirmText('')
    } catch (error: any) {
      const detail = error.response?.data?.detail
      if (typeof detail === 'string') {
        toast.error(detail)
      } else {
        toast.error('Failed to delete user')
      }
    } finally {
      setLoading(false)
    }
  }

  if (!isOpen || !user) return null

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-garage-surface border border-garage-border rounded-lg max-w-md w-full">
        <div className="p-6 space-y-4">
          {/* Warning Icon */}
          <div className="flex items-center gap-3">
            <div className="p-3 bg-danger/10 rounded-full">
              <AlertTriangle className="w-6 h-6 text-danger" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-garage-text">Delete User</h2>
              <p className="text-sm text-garage-text-muted">This action cannot be undone</p>
            </div>
          </div>

          {/* User Info */}
          <div className="p-4 bg-garage-bg border border-garage-border rounded-lg">
            <p className="text-sm text-garage-text">
              <strong>Username:</strong> {user.username}
            </p>
            <p className="text-sm text-garage-text">
              <strong>Email:</strong> {user.email}
            </p>
            {user.is_admin && (
              <p className="text-sm text-warning mt-2">
                <strong>⚠️ This is an admin user</strong>
              </p>
            )}
          </div>

          {/* Impact Warning */}
          <div className="p-4 bg-danger/10 border border-danger/30 rounded-lg">
            <p className="text-sm text-danger font-semibold mb-2">Data Impact:</p>
            <ul className="text-sm text-garage-text space-y-1">
              <li>• User account will be permanently deleted</li>
              <li>• All associated vehicles will be deleted</li>
              <li>• All service and fuel records will be deleted</li>
              <li>• This action cannot be reversed</li>
            </ul>
          </div>

          {/* Confirmation Input */}
          <div>
            <label className="block text-sm font-medium text-garage-text mb-2">
              Type <code className="px-1.5 py-0.5 bg-garage-bg border border-danger rounded text-danger font-mono">DELETE</code> to confirm:
            </label>
            <input
              type="text"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder="DELETE"
              className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-danger"
            />
          </div>

          {/* Actions */}
          <div className="flex gap-3">
            <button
              onClick={() => {
                onClose()
                setConfirmText('')
              }}
              className="flex-1 px-4 py-2 bg-garage-bg border border-garage-border rounded-lg hover:bg-garage-surface text-garage-text transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleDelete}
              disabled={confirmText !== 'DELETE' || loading}
              className="flex-1 px-4 py-2 bg-danger text-white rounded-lg hover:bg-danger/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? 'Deleting...' : 'Delete User'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
