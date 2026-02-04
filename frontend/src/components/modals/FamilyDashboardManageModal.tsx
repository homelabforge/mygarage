/**
 * Modal for managing family dashboard member visibility and ordering.
 */

import { useState, useEffect, useCallback } from 'react'
import { X, Eye, EyeOff, ChevronUp, ChevronDown, Loader2, Users } from 'lucide-react'
import { toast } from 'sonner'
import { familyService } from '@/services/familyService'
import type { FamilyMemberData } from '@/types/family'
import { formatRelationship } from '@/types/family'

interface FamilyDashboardManageModalProps {
  isOpen: boolean
  onClose: () => void
  onUpdate: () => void
}

export default function FamilyDashboardManageModal({
  isOpen,
  onClose,
  onUpdate,
}: FamilyDashboardManageModalProps) {
  const [members, setMembers] = useState<FamilyMemberData[]>([])
  const [loading, setLoading] = useState(true)
  const [updating, setUpdating] = useState<number | null>(null)

  const loadMembers = useCallback(async () => {
    setLoading(true)
    try {
      const data = await familyService.getDashboardMembers()
      // Sort by current order, then by visibility (visible first), then by username
      const sorted = [...data].sort((a, b) => {
        // First, sort by visibility (visible first)
        if (a.show_on_family_dashboard !== b.show_on_family_dashboard) {
          return a.show_on_family_dashboard ? -1 : 1
        }
        // Then by order
        if (a.family_dashboard_order !== b.family_dashboard_order) {
          return a.family_dashboard_order - b.family_dashboard_order
        }
        // Finally by username
        return a.username.localeCompare(b.username)
      })
      setMembers(sorted)
    } catch (err) {
      console.error('Failed to load dashboard members:', err)
      toast.error('Failed to load dashboard members')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (isOpen) {
      loadMembers()
    }
  }, [isOpen, loadMembers])

  const handleToggleVisibility = async (member: FamilyMemberData) => {
    setUpdating(member.id)
    try {
      await familyService.updateDashboardMember(member.id, {
        show_on_family_dashboard: !member.show_on_family_dashboard,
        family_dashboard_order: member.family_dashboard_order,
      })
      setMembers(prev =>
        prev.map(m =>
          m.id === member.id
            ? { ...m, show_on_family_dashboard: !m.show_on_family_dashboard }
            : m
        )
      )
      toast.success(
        member.show_on_family_dashboard
          ? `${member.username} hidden from dashboard`
          : `${member.username} shown on dashboard`
      )
    } catch (err) {
      console.error('Failed to update visibility:', err)
      toast.error('Failed to update visibility')
    } finally {
      setUpdating(null)
    }
  }

  const handleMoveUp = async (member: FamilyMemberData, index: number) => {
    if (index === 0) return
    const visibleMembers = members.filter(m => m.show_on_family_dashboard)
    const visibleIndex = visibleMembers.findIndex(m => m.id === member.id)
    if (visibleIndex <= 0) return

    const prevMember = visibleMembers[visibleIndex - 1]
    setUpdating(member.id)

    try {
      // Swap orders
      const newOrder = prevMember.family_dashboard_order
      const prevOrder = member.family_dashboard_order

      await Promise.all([
        familyService.updateDashboardMember(member.id, {
          show_on_family_dashboard: member.show_on_family_dashboard,
          family_dashboard_order: newOrder,
        }),
        familyService.updateDashboardMember(prevMember.id, {
          show_on_family_dashboard: prevMember.show_on_family_dashboard,
          family_dashboard_order: prevOrder,
        }),
      ])

      // Update local state
      setMembers(prev => {
        const updated = prev.map(m => {
          if (m.id === member.id) return { ...m, family_dashboard_order: newOrder }
          if (m.id === prevMember.id) return { ...m, family_dashboard_order: prevOrder }
          return m
        })
        // Re-sort
        return [...updated].sort((a, b) => {
          if (a.show_on_family_dashboard !== b.show_on_family_dashboard) {
            return a.show_on_family_dashboard ? -1 : 1
          }
          if (a.family_dashboard_order !== b.family_dashboard_order) {
            return a.family_dashboard_order - b.family_dashboard_order
          }
          return a.username.localeCompare(b.username)
        })
      })
    } catch (err) {
      console.error('Failed to reorder:', err)
      toast.error('Failed to reorder members')
    } finally {
      setUpdating(null)
    }
  }

  const handleMoveDown = async (member: FamilyMemberData) => {
    const visibleMembers = members.filter(m => m.show_on_family_dashboard)
    const visibleIndex = visibleMembers.findIndex(m => m.id === member.id)
    if (visibleIndex < 0 || visibleIndex >= visibleMembers.length - 1) return

    const nextMember = visibleMembers[visibleIndex + 1]
    setUpdating(member.id)

    try {
      // Swap orders
      const newOrder = nextMember.family_dashboard_order
      const nextOrder = member.family_dashboard_order

      await Promise.all([
        familyService.updateDashboardMember(member.id, {
          show_on_family_dashboard: member.show_on_family_dashboard,
          family_dashboard_order: newOrder,
        }),
        familyService.updateDashboardMember(nextMember.id, {
          show_on_family_dashboard: nextMember.show_on_family_dashboard,
          family_dashboard_order: nextOrder,
        }),
      ])

      // Update local state
      setMembers(prev => {
        const updated = prev.map(m => {
          if (m.id === member.id) return { ...m, family_dashboard_order: newOrder }
          if (m.id === nextMember.id) return { ...m, family_dashboard_order: nextOrder }
          return m
        })
        // Re-sort
        return [...updated].sort((a, b) => {
          if (a.show_on_family_dashboard !== b.show_on_family_dashboard) {
            return a.show_on_family_dashboard ? -1 : 1
          }
          if (a.family_dashboard_order !== b.family_dashboard_order) {
            return a.family_dashboard_order - b.family_dashboard_order
          }
          return a.username.localeCompare(b.username)
        })
      })
    } catch (err) {
      console.error('Failed to reorder:', err)
      toast.error('Failed to reorder members')
    } finally {
      setUpdating(null)
    }
  }

  const handleClose = () => {
    onUpdate()
    onClose()
  }

  if (!isOpen) return null

  const visibleMembers = members.filter(m => m.show_on_family_dashboard)
  const hiddenMembers = members.filter(m => !m.show_on_family_dashboard)

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-garage-surface border border-garage-border rounded-lg max-w-lg w-full max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-garage-border">
          <div className="flex items-center gap-2">
            <Users className="w-5 h-5 text-primary" />
            <h2 className="text-lg font-semibold text-garage-text">Manage Dashboard Members</h2>
          </div>
          <button
            onClick={handleClose}
            className="p-1 hover:bg-garage-bg rounded-lg transition-colors"
          >
            <X className="w-5 h-5 text-garage-text-muted" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-6 h-6 text-primary animate-spin" />
            </div>
          ) : (
            <>
              {/* Visible Members */}
              {visibleMembers.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-garage-text-muted mb-2">
                    Visible on Dashboard ({visibleMembers.length})
                  </h3>
                  <div className="space-y-2">
                    {visibleMembers.map((member, index) => (
                      <MemberRow
                        key={member.id}
                        member={member}
                        index={index}
                        isFirst={index === 0}
                        isLast={index === visibleMembers.length - 1}
                        isUpdating={updating === member.id}
                        onToggleVisibility={() => handleToggleVisibility(member)}
                        onMoveUp={() => handleMoveUp(member, index)}
                        onMoveDown={() => handleMoveDown(member)}
                        showReorder={true}
                      />
                    ))}
                  </div>
                </div>
              )}

              {/* Hidden Members */}
              {hiddenMembers.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-garage-text-muted mb-2">
                    Hidden from Dashboard ({hiddenMembers.length})
                  </h3>
                  <div className="space-y-2">
                    {hiddenMembers.map((member, index) => (
                      <MemberRow
                        key={member.id}
                        member={member}
                        index={index}
                        isFirst={true}
                        isLast={true}
                        isUpdating={updating === member.id}
                        onToggleVisibility={() => handleToggleVisibility(member)}
                        onMoveUp={() => {}}
                        onMoveDown={() => {}}
                        showReorder={false}
                      />
                    ))}
                  </div>
                </div>
              )}

              {members.length === 0 && (
                <div className="text-center py-8 text-garage-text-muted">
                  No users found
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-garage-border">
          <button
            onClick={handleClose}
            className="w-full px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  )
}

interface MemberRowProps {
  member: FamilyMemberData
  index: number
  isFirst: boolean
  isLast: boolean
  isUpdating: boolean
  onToggleVisibility: () => void
  onMoveUp: () => void
  onMoveDown: () => void
  showReorder: boolean
}

function MemberRow({
  member,
  isFirst,
  isLast,
  isUpdating,
  onToggleVisibility,
  onMoveUp,
  onMoveDown,
  showReorder,
}: MemberRowProps) {
  const displayName = member.full_name || member.username
  const relationship = formatRelationship(member.relationship, member.relationship_custom)

  return (
    <div className="flex items-center gap-3 p-3 bg-garage-bg rounded-lg">
      {/* Visibility Toggle */}
      <button
        onClick={onToggleVisibility}
        disabled={isUpdating}
        className="p-1.5 hover:bg-garage-surface rounded transition-colors disabled:opacity-50"
        title={member.show_on_family_dashboard ? 'Hide from dashboard' : 'Show on dashboard'}
      >
        {isUpdating ? (
          <Loader2 className="w-4 h-4 text-garage-text-muted animate-spin" />
        ) : member.show_on_family_dashboard ? (
          <Eye className="w-4 h-4 text-success" />
        ) : (
          <EyeOff className="w-4 h-4 text-garage-text-muted" />
        )}
      </button>

      {/* Member Info */}
      <div className="flex-1 min-w-0">
        <div className="font-medium text-garage-text truncate">{displayName}</div>
        <div className="text-sm text-garage-text-muted flex items-center gap-2">
          <span>@{member.username}</span>
          {relationship && (
            <>
              <span className="text-garage-border">•</span>
              <span>{relationship}</span>
            </>
          )}
        </div>
      </div>

      {/* Vehicle Count */}
      <div className="text-sm text-garage-text-muted">
        {member.vehicle_count} {member.vehicle_count === 1 ? 'vehicle' : 'vehicles'}
      </div>

      {/* Reorder Buttons */}
      {showReorder && (
        <div className="flex flex-col gap-0.5">
          <button
            onClick={onMoveUp}
            disabled={isFirst || isUpdating}
            className="p-1 hover:bg-garage-surface rounded transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            title="Move up"
          >
            <ChevronUp className="w-4 h-4 text-garage-text-muted" />
          </button>
          <button
            onClick={onMoveDown}
            disabled={isLast || isUpdating}
            className="p-1 hover:bg-garage-surface rounded transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            title="Move down"
          >
            <ChevronDown className="w-4 h-4 text-garage-text-muted" />
          </button>
        </div>
      )}
    </div>
  )
}
