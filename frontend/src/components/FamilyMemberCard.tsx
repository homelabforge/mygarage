/**
 * Family Member Card - Collapsible card showing member's vehicles and reminders.
 * Optionally shows admin action icons when showActions is true.
 */

import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ChevronDown, ChevronRight, ChevronUp, Car, AlertTriangle, Bell, User,
  Eye, EyeOff, Edit, Key, Power, PowerOff, Trash2,
} from 'lucide-react'
import type { FamilyMemberData, FamilyVehicleSummary } from '@/types/family'
import type { User as UserType } from '@/types/user'
import { formatRelationship } from '@/types/family'

interface FamilyMemberCardProps {
  member: FamilyMemberData
  defaultExpanded?: boolean
  // Admin management (all optional, backward compatible)
  user?: UserType
  currentUserId?: number
  activeAdminCount?: number
  showActions?: boolean
  isUpdating?: boolean
  membersLoaded?: boolean
  onEdit?: () => void
  onDelete?: () => void
  onToggleActive?: () => void
  onToggleDashboard?: () => void
  onResetPassword?: () => void
  onMoveUp?: () => void
  onMoveDown?: () => void
  canMoveUp?: boolean
  canMoveDown?: boolean
}

function VehicleSummaryRow({ vehicle }: { vehicle: FamilyVehicleSummary }) {
  const vehicleTitle = vehicle.year && vehicle.make && vehicle.model
    ? `${vehicle.year} ${vehicle.make} ${vehicle.model}`
    : vehicle.nickname

  return (
    <Link
      to={`/vehicles/${vehicle.vin}`}
      className="flex items-center gap-4 p-3 rounded-lg hover:bg-garage-bg transition-colors"
    >
      {/* Vehicle Photo */}
      <div className="w-16 h-12 rounded-lg overflow-hidden bg-garage-border flex-shrink-0">
        {vehicle.main_photo ? (
          <img
            src={vehicle.main_photo}
            alt={vehicle.nickname}
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <Car className="w-6 h-6 text-garage-text-muted" />
          </div>
        )}
      </div>

      {/* Vehicle Info */}
      <div className="flex-1 min-w-0">
        <p className="font-medium text-garage-text truncate">{vehicle.nickname}</p>
        <p className="text-sm text-garage-text-muted truncate">{vehicleTitle}</p>
      </div>

      {/* Last Service */}
      <div className="hidden md:block text-right min-w-32">
        {vehicle.last_service_date ? (
          <>
            <p className="text-sm text-garage-text truncate">{vehicle.last_service_description}</p>
            <p className="text-xs text-garage-text-muted">
              {new Date(vehicle.last_service_date).toLocaleDateString()}
            </p>
          </>
        ) : (
          <p className="text-sm text-garage-text-muted">No service records</p>
        )}
      </div>

      {/* Next Reminder */}
      <div className="hidden lg:block text-right min-w-32">
        {vehicle.next_reminder_description ? (
          <>
            <p className="text-sm text-garage-text truncate">{vehicle.next_reminder_description}</p>
            <p className="text-xs text-garage-text-muted">{vehicle.next_reminder_due}</p>
          </>
        ) : (
          <p className="text-sm text-garage-text-muted">No reminders</p>
        )}
      </div>

      {/* Overdue Badge */}
      {vehicle.overdue_reminders > 0 && (
        <div className="flex items-center gap-1 px-2 py-1 bg-danger/20 text-danger rounded-full">
          <AlertTriangle className="w-3 h-3" />
          <span className="text-xs font-medium">{vehicle.overdue_reminders}</span>
        </div>
      )}
    </Link>
  )
}

export default function FamilyMemberCard({
  member,
  defaultExpanded = false,
  user,
  currentUserId,
  activeAdminCount,
  showActions = false,
  isUpdating = false,
  membersLoaded = true,
  onEdit,
  onDelete,
  onToggleActive,
  onToggleDashboard,
  onResetPassword,
  onMoveUp,
  onMoveDown,
  canMoveUp = false,
  canMoveDown = false,
}: FamilyMemberCardProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded)

  const displayName = member.full_name || member.username
  const relationshipLabel = formatRelationship(member.relationship, member.relationship_custom)

  const isOidc = user?.auth_method === 'oidc'
  const isInactive = user ? !user.is_active : false
  const isSelf = user ? user.id === currentUserId : false
  const isLastAdmin = user ? (user.is_admin && user.is_active && (activeAdminCount ?? 0) === 1) : false

  // Permission matrix
  const canToggleDashboard = showActions && !isInactive && membersLoaded && !!onToggleDashboard
  const canEdit = showActions && !!onEdit
  const canResetPassword = showActions && !isOidc && !isInactive && !!onResetPassword
  const canToggleActive = showActions && !isOidc && !isLastAdmin && !!onToggleActive
  const canDeleteUser = showActions && !isOidc && !isSelf && !!onDelete
  const canReorder = showActions && !isInactive && membersLoaded && !!(onMoveUp || onMoveDown)

  const handleHeaderKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      setIsExpanded(!isExpanded)
    }
  }

  return (
    <div className={`bg-garage-surface border border-garage-border rounded-lg overflow-hidden ${isInactive ? 'opacity-60' : ''}`}>
      {/* Header */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => setIsExpanded(!isExpanded)}
        onKeyDown={handleHeaderKeyDown}
        className="w-full flex items-center gap-4 p-4 hover:bg-garage-bg transition-colors cursor-pointer"
      >
        {/* Expand Icon */}
        <div className="flex-shrink-0">
          {isExpanded ? (
            <ChevronDown className="w-5 h-5 text-garage-text-muted" />
          ) : (
            <ChevronRight className="w-5 h-5 text-garage-text-muted" />
          )}
        </div>

        {/* Avatar */}
        <div className="w-12 h-12 rounded-full bg-garage-border flex items-center justify-center flex-shrink-0">
          <User className="w-6 h-6 text-garage-text-muted" />
        </div>

        {/* Member Info */}
        <div className="flex-1 text-left min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="font-semibold text-garage-text truncate">{displayName}</p>
            {relationshipLabel && (
              <span className="px-2 py-0.5 text-xs bg-info/20 text-info rounded">
                {relationshipLabel}
              </span>
            )}
            {showActions && user?.is_admin && (
              <span className="px-2 py-0.5 text-xs bg-primary/20 text-primary rounded">
                Admin
              </span>
            )}
            {showActions && isOidc && (
              <span className="px-2 py-0.5 text-xs bg-warning/20 text-warning rounded">
                OIDC
              </span>
            )}
            {showActions && isInactive && (
              <span className="px-2 py-0.5 text-xs bg-danger/20 text-danger rounded">
                Inactive
              </span>
            )}
          </div>
          <p className="text-sm text-garage-text-muted">@{member.username}</p>
        </div>

        {/* Stats */}
        <div className="flex items-center gap-4 flex-shrink-0">
          <div className="flex items-center gap-1.5 text-garage-text-muted">
            <Car className="w-4 h-4" />
            <span className="text-sm">{member.vehicle_count}</span>
          </div>
          {member.upcoming_reminders > 0 && (
            <div className="flex items-center gap-1.5 text-info">
              <Bell className="w-4 h-4" />
              <span className="text-sm">{member.upcoming_reminders}</span>
            </div>
          )}
          {member.overdue_reminders > 0 && (
            <div className="flex items-center gap-1.5 text-danger">
              <AlertTriangle className="w-4 h-4" />
              <span className="text-sm font-medium">{member.overdue_reminders}</span>
            </div>
          )}
        </div>

        {/* Action Icons */}
        {showActions && (
          <div className="flex items-center gap-1 flex-shrink-0" onClick={e => e.stopPropagation()}>
            {/* Dashboard Visibility */}
            {canToggleDashboard && (
              <button
                type="button"
                onClick={() => onToggleDashboard!()}
                disabled={isUpdating}
                className={`p-1.5 rounded transition-colors disabled:opacity-50 ${
                  member.show_on_family_dashboard
                    ? 'bg-success/20 hover:bg-success/30'
                    : 'hover:bg-garage-border'
                }`}
                title={member.show_on_family_dashboard ? 'Hide from dashboard' : 'Show on dashboard'}
              >
                {member.show_on_family_dashboard ? (
                  <Eye className="w-4 h-4 text-success" />
                ) : (
                  <EyeOff className="w-4 h-4 text-garage-text-muted" />
                )}
              </button>
            )}

            {/* Edit */}
            {canEdit && (
              <button
                type="button"
                onClick={() => onEdit!()}
                disabled={isUpdating}
                className="p-1.5 hover:bg-garage-border rounded transition-colors disabled:opacity-50"
                title="Edit user"
              >
                <Edit className="w-4 h-4 text-garage-text-muted" />
              </button>
            )}

            {/* Reset Password (local auth only, active only) */}
            {canResetPassword && (
              <button
                type="button"
                onClick={() => onResetPassword!()}
                disabled={isUpdating}
                className="p-1.5 hover:bg-garage-border rounded transition-colors disabled:opacity-50"
                title="Reset password"
              >
                <Key className="w-4 h-4 text-garage-text-muted" />
              </button>
            )}

            {/* Toggle Active (not OIDC, not last admin) */}
            {canToggleActive && (
              <button
                type="button"
                onClick={() => onToggleActive!()}
                disabled={isUpdating}
                className="p-1.5 hover:bg-garage-border rounded transition-colors disabled:opacity-50"
                title={isInactive ? 'Enable user' : 'Disable user'}
              >
                {isInactive ? (
                  <Power className="w-4 h-4 text-garage-text-muted" />
                ) : (
                  <PowerOff className="w-4 h-4 text-garage-text-muted" />
                )}
              </button>
            )}

            {/* Delete (not OIDC, not self) */}
            {canDeleteUser && (
              <button
                type="button"
                onClick={() => onDelete!()}
                disabled={isUpdating}
                className="p-1.5 hover:bg-danger/20 rounded transition-colors disabled:opacity-50"
                title="Delete user"
              >
                <Trash2 className="w-4 h-4 text-danger" />
              </button>
            )}
          </div>
        )}

        {/* Reorder Arrows */}
        {canReorder && (
          <div className="flex flex-col gap-0.5 flex-shrink-0" onClick={e => e.stopPropagation()}>
            <button
              type="button"
              onClick={() => onMoveUp?.()}
              disabled={!canMoveUp || isUpdating}
              className="p-1 hover:bg-garage-border rounded transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              title="Move up"
            >
              <ChevronUp className="w-4 h-4 text-garage-text-muted" />
            </button>
            <button
              type="button"
              onClick={() => onMoveDown?.()}
              disabled={!canMoveDown || isUpdating}
              className="p-1 hover:bg-garage-border rounded transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              title="Move down"
            >
              <ChevronDown className="w-4 h-4 text-garage-text-muted" />
            </button>
          </div>
        )}
      </div>

      {/* Expanded Content */}
      {isExpanded && (
        <div className="border-t border-garage-border">
          {member.vehicles.length === 0 ? (
            <div className="p-6 text-center text-garage-text-muted">
              <Car className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p>No vehicles</p>
            </div>
          ) : (
            <div className="divide-y divide-garage-border">
              {/* Table Header (desktop only) */}
              <div className="hidden md:grid grid-cols-[1fr_auto_auto_auto] gap-4 px-4 py-2 text-xs font-medium text-garage-text-muted uppercase bg-garage-bg">
                <span>Vehicle</span>
                <span className="text-right min-w-32">Last Service</span>
                <span className="hidden lg:block text-right min-w-32">Next Reminder</span>
                <span className="w-16"></span>
              </div>

              {/* Vehicle Rows */}
              {member.vehicles.map((vehicle) => (
                <VehicleSummaryRow key={vehicle.vin} vehicle={vehicle} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
