/**
 * Family Management Modal - Single unified view for managing family members,
 * user accounts, and dashboard visibility. Action icons live directly on
 * member cards — no separate Users tab or Manage Members modal.
 *
 * State ownership: users[] is the authoritative source for active/inactive
 * classification. allMembers provides vehicle data for active users only.
 */

import { useTranslation } from 'react-i18next'
import { useState, useEffect, useCallback } from 'react'
import {
  Users, X, Car, AlertTriangle, Bell, Loader2,
  Shield, UserPlus, Key, Info,
} from 'lucide-react'
import { toast } from 'sonner'
import api from '@/services/api'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'
import { useAuth } from '@/contexts/AuthContext'
import { familyService } from '@/services/familyService'
import type { FamilyMemberData } from '@/types/family'
import type { User } from '@/types/user'
import FamilyMemberCard from '@/components/FamilyMemberCard'
import AddEditUserModal from '@/components/modals/AddEditUserModal'
import DeleteUserModal from '@/components/modals/DeleteUserModal'
import LocalAuthModal from '@/components/modals/LocalAuthModal'

type RawSetting = { key: string; value?: string | null }

interface FamilyManagementModalProps {
  isOpen: boolean
  onClose: () => void
}

// Python compares str by code point. JS < compares UTF-16 code units, which
// flips a name outside the BMP against one near the top of it.
function compareCodePoints(a: string, b: string): number {
  const x = Array.from(a, ch => ch.codePointAt(0) ?? 0)
  const y = Array.from(b, ch => ch.codePointAt(0) ?? 0)
  const at = x.findIndex((cp, i) => i >= y.length || cp !== y[i])
  if (at === -1) return x.length - y.length
  return at >= y.length ? 1 : x[at] - y[at]
}

export default function FamilyManagementModal({ isOpen, onClose }: FamilyManagementModalProps) {
  const { t } = useTranslation('forms')
  const { user: currentUser } = useAuth()

  // Data state
  const [users, setUsers] = useState<User[]>([])
  const [allMembers, setAllMembers] = useState<FamilyMemberData[]>([])
  const [membersLoaded, setMembersLoaded] = useState(true)
  const [authMode, setAuthMode] = useState<string>('none')
  const [multiUserEnabled, setMultiUserEnabled] = useState<string>('false')
  const [loading, setLoading] = useState(true)
  const [updatingUserId, setUpdatingUserId] = useState<number | null>(null)

  // Child modal orchestration
  const [selectedUser, setSelectedUser] = useState<User | null>(null)
  const [showAddEditModal, setShowAddEditModal] = useState(false)
  const [isEditMode, setIsEditMode] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [showLocalAuthModal, setShowLocalAuthModal] = useState(false)

  // Derived state
  const authEverEnabled = users.length > 0
  const activeAdminCount = users.filter(u => u.is_admin && u.is_active).length
  const shouldLoadUsers = authMode === 'oidc' || (authMode === 'local' && multiUserEnabled === 'true')

  // Stats (active users only, computed from allMembers)
  const totalMembers = allMembers.length
  const totalVehicles = allMembers.reduce((sum, m) => sum + m.vehicle_count, 0)
  const totalUpcoming = allMembers.reduce((sum, m) => sum + m.upcoming_maintenance, 0)
  const totalOverdue = allMembers.reduce((sum, m) => sum + m.overdue_maintenance, 0)

  // View model: merge users[] (authoritative) with allMembers (vehicle data)
  const memberById = new Map(allMembers.map(m => [m.id, m]))

  const visibleMembers: { user: User; member: FamilyMemberData | null }[] = []
  const hiddenMembers: { user: User; member: FamilyMemberData | null }[] = []
  const inactiveUsers: User[] = []

  for (const u of users) {
    if (!u.is_active) {
      inactiveUsers.push(u)
    } else if (u.show_on_family_dashboard) {
      visibleMembers.push({ user: u, member: memberById.get(u.id) ?? null })
    } else {
      hiddenMembers.push({ user: u, member: memberById.get(u.id) ?? null })
    }
  }

  // Matches the backend: lowercased name, then as typed, by code point. Pinned
  // for ASCII names and one supplementary pair; Python's lower() and JS's
  // toLowerCase() can still differ on a few special casings nothing tests.
  visibleMembers.sort(
    (a, b) =>
      a.user.family_dashboard_order - b.user.family_dashboard_order ||
      compareCodePoints(a.user.username.toLowerCase(), b.user.username.toLowerCase()) ||
      compareCodePoints(a.user.username, b.user.username),
  )

  // ─── Reload helpers ──────────────────────────────────────────────────

  const reloadUsers = useCallback(async () => {
    try {
      const usersRes = await api.get('/auth/users')
      setUsers(usersRes.data)
    } catch {
      // Keep existing users on failure
    }
  }, [])

  const reloadAllMembers = useCallback(async () => {
    try {
      const data = await familyService.getDashboardMembers()
      setAllMembers(data)
      setMembersLoaded(true)
    } catch {
      setAllMembers([])
      setMembersLoaded(false)
    }
  }, [])

  const reloadAll = useCallback(async () => {
    await Promise.all([reloadUsers(), reloadAllMembers()])
  }, [reloadUsers, reloadAllMembers])

  // ─── Initial data load ───────────────────────────────────────────────

  const loadData = useCallback(async () => {
    if (!isOpen) return
    setLoading(true)

    try {
      // Fetch settings
      const settingsRes = await api.get('/settings')
      const settingsMap: Record<string, string> = {}
      settingsRes.data.settings.forEach((s: RawSetting) => {
        settingsMap[s.key] = s.value || ''
      })
      const fetchedAuthMode = settingsMap.auth_mode || 'none'
      const fetchedMultiUser = settingsMap.multi_user_enabled || 'false'
      setAuthMode(fetchedAuthMode)
      setMultiUserEnabled(fetchedMultiUser)

      // Load users if auth mode warrants it
      const shouldLoad = fetchedAuthMode === 'oidc' || (fetchedAuthMode === 'local' && fetchedMultiUser === 'true')
      if (shouldLoad) {
        try {
          const usersRes = await api.get('/auth/users')
          setUsers(usersRes.data)
        } catch {
          setUsers([])
        }
      } else {
        // Still check whether anyone's registered, for authEverEnabled
        try {
          const countRes = await api.get('/auth/users/count')
          if (countRes.data.has_users === true) {
            const usersRes = await api.get('/auth/users')
            setUsers(usersRes.data)
          } else {
            setUsers([])
          }
        } catch {
          setUsers([])
        }
      }

      // Load all members (active users with vehicle data)
      try {
        const membersData = await familyService.getDashboardMembers()
        setAllMembers(membersData)
        setMembersLoaded(true)
      } catch {
        setAllMembers([])
        setMembersLoaded(false)
      }
    } catch {
      toast.error(t('modal.failedToLoadFamilyData'))
    } finally {
      setLoading(false)
    }
  }, [isOpen, t])

  useEffect(() => {
    if (isOpen) {
      void loadData()
    } else {
      // Reset state when modal closes
      setSelectedUser(null)
      setShowAddEditModal(false)
      setShowDeleteModal(false)
      setShowLocalAuthModal(false)
      setUpdatingUserId(null)
    }
  }, [isOpen, loadData])

  // ─── Action handlers ─────────────────────────────────────────────────

  const handleEditUser = (u: User) => {
    setSelectedUser(u)
    setIsEditMode(true)
    setShowAddEditModal(true)
  }

  const handleAddUser = () => {
    setSelectedUser(null)
    setIsEditMode(false)
    setShowAddEditModal(true)
  }

  const handleDeleteUser = (u: User) => {
    if (u.id === currentUser?.id) {
      toast.error(t('modal.cannotDeleteOwnAccount'))
      return
    }
    setSelectedUser(u)
    setShowDeleteModal(true)
  }

  const handleResetPassword = (u: User) => {
    if (u.auth_method === 'oidc') {
      toast.error(t('modal.cannotResetOidcPassword'))
      return
    }
    setSelectedUser(u)
    setIsEditMode(true)
    setShowAddEditModal(true)
  }

  const handleToggleActive = async (u: User) => {
    setUpdatingUserId(u.id)
    try {
      await api.put(`/auth/users/${u.id}`, { is_active: !u.is_active })
      toast.success(u.is_active ? t('modal.userDisabled') : t('modal.userEnabled'))
      await reloadAll()
    } catch (err) {
      toast.error(getActionErrorMessage(err, t('modal.updateStatusAction')))
    } finally {
      setUpdatingUserId(null)
    }
  }

  const handleToggleRelink = async (u: User, arm: boolean): Promise<void> => {
    setUpdatingUserId(u.id)
    try {
      if (arm) {
        await api.post(`/auth/users/${u.id}/oidc-relink`)
      } else {
        await api.delete(`/auth/users/${u.id}/oidc-relink`)
      }
      toast.success(arm ? t('modal.ssoRelinkAllowed') : t('modal.ssoRelinkCancelled'))
      await reloadUsers()
    } catch (err) {
      toast.error(getActionErrorMessage(err, t('modal.updateSsoRelinkAction')))
    } finally {
      setUpdatingUserId(null)
    }
  }

  const handleToggleDashboard = async (u: User) => {
    setUpdatingUserId(u.id)
    try {
      await familyService.updateDashboardMember(u.id, {
        show_on_family_dashboard: !u.show_on_family_dashboard,
      })
      toast.success(
        u.show_on_family_dashboard
          ? t('modal.hiddenFromDashboardMsg', { name: u.username })
          : t('modal.shownOnDashboardMsg', { name: u.username })
      )
      await reloadAll()
    } catch {
      toast.error(t('modal.failedToUpdateDashboard'))
    } finally {
      setUpdatingUserId(null)
    }
  }

  // Every order starts at 0, so swapping two members' orders swapped 0 for 0
  // and nothing moved. Write each member's new position instead, skipping the
  // ones already there.
  const moveMember = async (userId: number, from: number, to: number) => {
    if (to < 0 || to >= visibleMembers.length) return
    setUpdatingUserId(userId)
    const reordered = [...visibleMembers]
    const [moved] = reordered.splice(from, 1)
    reordered.splice(to, 0, moved)
    try {
      await Promise.all(
        reordered.flatMap(({ user }, position) =>
          user.family_dashboard_order === position
            ? []
            : [
                familyService.updateDashboardMember(user.id, {
                  show_on_family_dashboard: true,
                  family_dashboard_order: position,
                }),
              ],
        ),
      )
      await reloadAll()
    } catch {
      toast.error(t('modal.failedToReorder'))
      await reloadAll()  // Resync on failure
    } finally {
      setUpdatingUserId(null)
    }
  }

  const handleMoveUp = (userId: number, index: number) => moveMember(userId, index, index - 1)
  const handleMoveDown = (userId: number, index: number) => moveMember(userId, index, index + 1)

  const handleUserSaved = () => {
    setShowAddEditModal(false)
    setSelectedUser(null)
    void reloadAll()
  }

  const handleUserDeleted = () => {
    setShowDeleteModal(false)
    setSelectedUser(null)
    void reloadAll()
  }

  const handleMultiUserToggle = async (enabled: boolean) => {
    const newValue = enabled ? 'true' : 'false'
    setMultiUserEnabled(newValue)
    try {
      await api.post('/settings/batch', {
        settings: { multi_user_enabled: newValue },
      })
      toast.success(
        enabled
          ? t('familyManagementModal.multiUserModeEnabled')
          : t('familyManagementModal.multiUserModeDisabled')
      )
      await reloadAll()
    } catch {
      toast.error(t('modal.failedToUpdateMultiUser'))
      setMultiUserEnabled(enabled ? 'false' : 'true') // Revert
    }
  }

  // ─── Escape key handler ──────────────────────────────────────────────

  useEffect(() => {
    if (!isOpen) return

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return

      if (showAddEditModal) {
        setShowAddEditModal(false)
        setSelectedUser(null)
      } else if (showDeleteModal) {
        setShowDeleteModal(false)
        setSelectedUser(null)
      } else if (showLocalAuthModal) {
        setShowLocalAuthModal(false)
      } else {
        onClose()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, showAddEditModal, showDeleteModal, showLocalAuthModal, onClose])

  // ─── Helpers ─────────────────────────────────────────────────────────

  /** Synthetic FamilyMemberData for inactive users (backend excludes them). */
  const buildSyntheticMember = (u: User): FamilyMemberData => ({
    id: u.id,
    username: u.username,
    full_name: u.full_name,
    relationship: u.relationship,
    relationship_custom: u.relationship_custom,
    vehicle_count: 0,
    vehicles: [],
    overdue_maintenance: 0,
    upcoming_maintenance: 0,
    show_on_family_dashboard: false,
    family_dashboard_order: 999,
  })

  if (!isOpen) return null

  return (
    <>
      <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50 p-4">
        <div className="bg-garage-surface border border-garage-border rounded-lg max-w-6xl w-full max-h-[90vh] flex flex-col">
          {/* Header */}
          <div className="p-6 border-b border-garage-border flex items-center justify-between flex-shrink-0">
            <div className="flex items-center gap-2">
              <Users className="w-6 h-6 text-primary" />
              <div>
                <h2 className="text-2xl font-bold text-garage-text">{t('modal.familyManagement')}</h2>
                <p className="text-sm text-garage-text-muted">
                  {t('modal.familyManagementDescription')}
                </p>
              </div>
            </div>
            <button onClick={onClose} className="p-2 hover:bg-garage-surface-light rounded-lg transition-colors">
              <X className="w-5 h-5 text-garage-text-muted" />
            </button>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto p-6">
            {loading ? (
              <div className="flex items-center justify-center py-16">
                <Loader2 className="w-8 h-8 text-primary animate-spin" />
              </div>
            ) : (
              <div className="space-y-6">
                {/* Stats Row */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div className="bg-garage-bg border border-garage-border rounded-lg p-4">
                    <div className="flex items-center gap-3">
                      <div className="p-2 bg-primary/20 rounded-lg">
                        <Users className="w-5 h-5 text-primary" />
                      </div>
                      <div>
                        <p className="text-2xl font-bold text-garage-text">{totalMembers}</p>
                        <p className="text-sm text-garage-text-muted">{t('modal.members')}</p>
                      </div>
                    </div>
                  </div>
                  <div className="bg-garage-bg border border-garage-border rounded-lg p-4">
                    <div className="flex items-center gap-3">
                      <div className="p-2 bg-info/20 rounded-lg">
                        <Car className="w-5 h-5 text-info" />
                      </div>
                      <div>
                        <p className="text-2xl font-bold text-garage-text">{totalVehicles}</p>
                        <p className="text-sm text-garage-text-muted">{t('modal.vehicles')}</p>
                      </div>
                    </div>
                  </div>
                  <div className="bg-garage-bg border border-garage-border rounded-lg p-4">
                    <div className="flex items-center gap-3">
                      <div className="p-2 bg-warning/20 rounded-lg">
                        <Bell className="w-5 h-5 text-warning" />
                      </div>
                      <div>
                        <p className="text-2xl font-bold text-garage-text">{totalUpcoming}</p>
                        <p className="text-sm text-garage-text-muted">{t('modal.upcoming')}</p>
                      </div>
                    </div>
                  </div>
                  <div className="bg-garage-bg border border-garage-border rounded-lg p-4">
                    <div className="flex items-center gap-3">
                      <div className="p-2 bg-danger/20 rounded-lg">
                        <AlertTriangle className="w-5 h-5 text-danger" />
                      </div>
                      <div>
                        <p className="text-2xl font-bold text-garage-text">{totalOverdue}</p>
                        <p className="text-sm text-garage-text-muted">{t('modal.overdue')}</p>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Warning banner when members failed to load */}
                {!membersLoaded && (
                  <div className="flex items-center gap-3 p-3 bg-warning/10 border border-warning/30 rounded-lg">
                    <Info className="w-5 h-5 text-warning flex-shrink-0" />
                    <p className="text-sm text-garage-text">
                      {t('modal.memberDataUnavailable')}
                    </p>
                  </div>
                )}

                {/* Toolbar */}
                <div className="flex items-center justify-between gap-4 flex-wrap">
                  {/* Multi-user toggle (local auth only) */}
                  {authMode === 'local' ? (
                    <label className="flex items-center gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={multiUserEnabled === 'true'}
                        onChange={(e) => void handleMultiUserToggle(e.target.checked)}
                        className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2"
                      />
                      <span className="text-sm font-medium text-garage-text">
                        {t('familyManagementModal.multiUserMode')}
                      </span>
                    </label>
                  ) : (
                    <div />
                  )}

                  <div className="flex items-center gap-2">
                    {authMode === 'local' && (
                      <>
                        <button
                          onClick={() => setShowLocalAuthModal(true)}
                          className="flex items-center gap-2 px-3 py-2 bg-garage-bg border border-garage-border rounded-lg hover:bg-garage-surface text-garage-text transition-colors text-sm"
                        >
                          <Key className="w-4 h-4" />
                          {t('modal.configureAuth')}
                        </button>
                        <button
                          onClick={handleAddUser}
                          className="flex items-center gap-2 px-3 py-2 bg-primary text-(--accent-on-solid) rounded-lg hover:bg-primary/90 transition-colors text-sm"
                        >
                          <UserPlus className="w-4 h-4" />
                          {t('familyManagementModal.addUser')}
                        </button>
                      </>
                    )}
                  </div>
                </div>

                {/* Member sections */}
                {!shouldLoadUsers && !authEverEnabled ? (
                  <div className="text-center py-12">
                    <Shield className="w-16 h-16 text-garage-text-muted mx-auto mb-4 opacity-50" />
                    <h3 className="text-xl font-semibold text-garage-text mb-2">{t('modal.authNotEnabled')}</h3>
                    <p className="text-garage-text-muted">
                      {t('modal.enableAuthDescription')}
                    </p>
                  </div>
                ) : (
                  <>
                    {/* On Dashboard */}
                    {visibleMembers.length > 0 && (
                      <section>
                        <h3 className="text-sm font-medium text-garage-text-muted mb-3 uppercase tracking-wide">
                          {t('modal.onDashboard')} ({visibleMembers.length})
                        </h3>
                        <div className="space-y-3">
                          {visibleMembers.map(({ user: u, member }, index) => (
                            <FamilyMemberCard
                              key={u.id}
                              member={member ?? buildSyntheticMember(u)}
                              defaultExpanded={false}
                              user={u}
                              currentUserId={currentUser?.id}
                              activeAdminCount={activeAdminCount}
                              showActions
                              isUpdating={updatingUserId === u.id}
                              membersLoaded={membersLoaded}
                              onEdit={() => handleEditUser(u)}
                              onDelete={() => handleDeleteUser(u)}
                              onToggleActive={() => void handleToggleActive(u)}
                              onToggleDashboard={() => void handleToggleDashboard(u)}
                              onResetPassword={() => handleResetPassword(u)}
                              onToggleRelink={(arm) => void handleToggleRelink(u, arm)}
                              onMoveUp={() => void handleMoveUp(u.id, index)}
                              onMoveDown={() => void handleMoveDown(u.id, index)}
                              canMoveUp={index > 0}
                              canMoveDown={index < visibleMembers.length - 1}
                            />
                          ))}
                        </div>
                      </section>
                    )}

                    {/* Hidden from Dashboard */}
                    {hiddenMembers.length > 0 && (
                      <section>
                        <h3 className="text-sm font-medium text-garage-text-muted mb-3 uppercase tracking-wide">
                          {t('modal.hiddenFromDashboard')} ({hiddenMembers.length})
                        </h3>
                        <div className="space-y-3">
                          {hiddenMembers.map(({ user: u, member }) => (
                            <FamilyMemberCard
                              key={u.id}
                              member={member ?? buildSyntheticMember(u)}
                              defaultExpanded={false}
                              user={u}
                              currentUserId={currentUser?.id}
                              activeAdminCount={activeAdminCount}
                              showActions
                              isUpdating={updatingUserId === u.id}
                              membersLoaded={membersLoaded}
                              onEdit={() => handleEditUser(u)}
                              onDelete={() => handleDeleteUser(u)}
                              onToggleActive={() => void handleToggleActive(u)}
                              onToggleDashboard={() => void handleToggleDashboard(u)}
                              onResetPassword={() => handleResetPassword(u)}
                              onToggleRelink={(arm) => void handleToggleRelink(u, arm)}
                            />
                          ))}
                        </div>
                      </section>
                    )}

                    {/* Inactive */}
                    {inactiveUsers.length > 0 && (
                      <section>
                        <h3 className="text-sm font-medium text-garage-text-muted mb-3 uppercase tracking-wide">
                          {t('modal.inactive')} ({inactiveUsers.length})
                        </h3>
                        <div className="space-y-3">
                          {inactiveUsers.map((u) => (
                            <FamilyMemberCard
                              key={u.id}
                              member={buildSyntheticMember(u)}
                              defaultExpanded={false}
                              user={u}
                              currentUserId={currentUser?.id}
                              activeAdminCount={activeAdminCount}
                              showActions
                              isUpdating={updatingUserId === u.id}
                              membersLoaded={membersLoaded}
                              onEdit={() => handleEditUser(u)}
                              onDelete={() => handleDeleteUser(u)}
                              onToggleActive={() => void handleToggleActive(u)}
                              onToggleRelink={(arm) => void handleToggleRelink(u, arm)}
                            />
                          ))}
                        </div>
                      </section>
                    )}

                    {/* Empty state */}
                    {visibleMembers.length === 0 && hiddenMembers.length === 0 && inactiveUsers.length === 0 && (
                      <div className="text-center py-12">
                        <Users className="w-16 h-16 text-garage-text-muted mx-auto mb-4 opacity-50" />
                        <h3 className="text-xl font-semibold text-garage-text mb-2">{t('modal.noUsers')}</h3>
                        <p className="text-garage-text-muted">
                          {t('modal.addUsersDescription')}
                        </p>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Child modals — stacked above (z-[60]) */}
      <AddEditUserModal
        isOpen={showAddEditModal}
        onClose={() => { setShowAddEditModal(false); setSelectedUser(null) }}
        user={isEditMode ? selectedUser : null}
        onSave={handleUserSaved}
        currentUserId={currentUser?.id || 0}
        activeAdminCount={activeAdminCount}
      />

      <DeleteUserModal
        isOpen={showDeleteModal}
        onClose={() => { setShowDeleteModal(false); setSelectedUser(null) }}
        user={selectedUser}
        onConfirm={handleUserDeleted}
      />

      <LocalAuthModal
        isOpen={showLocalAuthModal}
        onClose={() => setShowLocalAuthModal(false)}
        authEverEnabled={authEverEnabled}
        userCount={users.length}
        users={users}
        onShowUserManagement={() => setShowLocalAuthModal(false)}
        onShowAddUser={() => { setShowLocalAuthModal(false); handleAddUser() }}
      />
    </>
  )
}
