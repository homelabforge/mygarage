import { useState, useEffect } from 'react'
import { Users, X, Search, Edit, Trash2, Key, Power, PowerOff } from 'lucide-react'
import { toast } from 'sonner'
import api from '@/services/api'

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

interface UserManagementModalProps {
  isOpen: boolean
  onClose: () => void
  currentUserId: number
  onEditUser: (user: User) => void
  onDeleteUser: (user: User) => void
  onResetPassword: (user: User) => void
  onToggleActive: (user: User) => void
}

export default function UserManagementModal({
  isOpen,
  onClose,
  currentUserId,
  onEditUser,
  onDeleteUser,
  onResetPassword,
  onToggleActive
}: UserManagementModalProps) {
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')

  useEffect(() => {
    if (!isOpen) return

    const fetchUsers = async () => {
      try {
        const response = await api.get('/auth/users')
        setUsers(response.data)
      } catch (error) {
        toast.error('Failed to load users')
      } finally {
        setLoading(false)
      }
    }

    fetchUsers()
  }, [isOpen])

  const filteredUsers = users.filter(user =>
    user.username.toLowerCase().includes(searchQuery.toLowerCase()) ||
    user.email.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (user.full_name?.toLowerCase().includes(searchQuery.toLowerCase()))
  )

  // Count active admins
  const activeAdminCount = users.filter(u => u.is_admin && u.is_active).length

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-garage-surface border border-garage-border rounded-lg max-w-5xl w-full max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="p-6 border-b border-garage-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Users className="w-6 h-6 text-primary" />
            <h2 className="text-2xl font-bold text-garage-text">User Management</h2>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-garage-muted rounded-lg transition-colors">
            <X className="w-5 h-5 text-garage-text-muted" />
          </button>
        </div>

        {/* Search Bar */}
        <div className="p-6 border-b border-garage-border">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-garage-text-muted" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search users by username, email, or name..."
              className="w-full pl-10 pr-4 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>
        </div>

        {/* User Table */}
        <div className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="text-center py-8 text-garage-text-muted">Loading users...</div>
          ) : filteredUsers.length === 0 ? (
            <div className="text-center py-8 text-garage-text-muted">
              {searchQuery ? 'No users found matching your search.' : 'No users yet.'}
            </div>
          ) : (
            <table className="w-full">
              <thead className="border-b border-garage-border">
                <tr className="text-left">
                  <th className="pb-3 text-sm font-medium text-garage-text">Username</th>
                  <th className="pb-3 text-sm font-medium text-garage-text">Email</th>
                  <th className="pb-3 text-sm font-medium text-garage-text">Role</th>
                  <th className="pb-3 text-sm font-medium text-garage-text">Status</th>
                  <th className="pb-3 text-sm font-medium text-garage-text">Auth</th>
                  <th className="pb-3 text-sm font-medium text-garage-text text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredUsers.map((user) => (
                  <tr key={user.id} className="border-b border-garage-border hover:bg-garage-bg transition-colors">
                    <td className="py-3 text-sm text-garage-text">
                      {user.username}
                      {user.id === currentUserId && (
                        <span className="ml-2 text-xs text-garage-text-muted">(You)</span>
                      )}
                    </td>
                    <td className="py-3 text-sm text-garage-text">{user.email}</td>
                    <td className="py-3">
                      {user.is_admin ? (
                        <span className="px-2 py-1 text-xs bg-primary/20 text-primary rounded">Admin</span>
                      ) : (
                        <span className="px-2 py-1 text-xs bg-garage-border text-garage-text-muted rounded">User</span>
                      )}
                    </td>
                    <td className="py-3">
                      {user.is_active ? (
                        <span className="px-2 py-1 text-xs bg-success/20 text-success rounded">Active</span>
                      ) : (
                        <span className="px-2 py-1 text-xs bg-danger/20 text-danger rounded">Inactive</span>
                      )}
                    </td>
                    <td className="py-3">
                      {user.auth_method === 'oidc' ? (
                        <span className="px-2 py-1 text-xs bg-warning/20 text-warning rounded">OIDC</span>
                      ) : (
                        <span className="px-2 py-1 text-xs bg-garage-border text-garage-text-muted rounded">Local</span>
                      )}
                    </td>
                    <td className="py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => onEditUser(user)}
                          className="p-1.5 hover:bg-garage-border rounded transition-colors"
                          title="Edit user"
                        >
                          <Edit className="w-4 h-4 text-garage-text-muted" />
                        </button>
                        {user.auth_method === 'local' && (
                          <button
                            onClick={() => onResetPassword(user)}
                            className="p-1.5 hover:bg-garage-border rounded transition-colors"
                            title="Reset password"
                          >
                            <Key className="w-4 h-4 text-garage-text-muted" />
                          </button>
                        )}
                        <button
                          onClick={() => onToggleActive(user)}
                          disabled={user.id === currentUserId && user.is_admin && user.is_active && activeAdminCount === 1}
                          className="p-1.5 hover:bg-garage-border rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                          title={
                            user.id === currentUserId && user.is_admin && user.is_active && activeAdminCount === 1
                              ? 'Cannot disable the last active admin'
                              : user.is_active ? 'Disable user' : 'Enable user'
                          }
                        >
                          {user.is_active ? (
                            <PowerOff className="w-4 h-4 text-garage-text-muted" />
                          ) : (
                            <Power className="w-4 h-4 text-garage-text-muted" />
                          )}
                        </button>
                        {user.id !== currentUserId && (
                          <button
                            onClick={() => onDeleteUser(user)}
                            className="p-1.5 hover:bg-danger/20 rounded transition-colors"
                            title="Delete user"
                          >
                            <Trash2 className="w-4 h-4 text-danger" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-garage-border text-sm text-garage-text-muted text-center">
          Showing {filteredUsers.length} of {users.length} users
        </div>
      </div>
    </div>
  )
}
