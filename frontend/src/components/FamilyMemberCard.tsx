/**
 * Family Member Card - Collapsible card showing member's vehicles and maintenance.
 * Optionally shows admin action icons when showActions is true.
 */

import { useId, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ChevronDown, ChevronRight, ChevronUp, Car, AlertTriangle, Bell, User,
  Eye, EyeOff, Edit, Key, Link2, Link2Off, Power, PowerOff, Trash2,
} from 'lucide-react'
import type { FamilyMemberData, FamilyVehicleSummary, TranslateFn } from '@/types/family'
import type { User as UserType } from '@/types/user'
import { useTranslation } from 'react-i18next'
import { formatRelationship } from '@/types/family'
import { formatDateForDisplay } from '@/utils/dateUtils'
import { formatTime, parseAPITimestamp } from '@/utils/parseAPITimestamp'
import { useDateLocale } from '@/hooks/useDateLocale'
import { useTimeFormat } from '@/hooks/useTimeFormat'
import { withBase } from '@/utils/basePath'
import { isSelectingText } from '@/utils/textSelection'
import { cameFromNestedControl } from './ClickableCard'

/** Matches a bare ISO calendar date (YYYY-MM-DD). */
const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/

/** When the account's SSO relink closes, or null if none is open. The value is naive UTC. */
function openRelinkUntil(value: string | null | undefined): Date | null {
  const until = parseAPITimestamp(value)
  return until !== null && until.getTime() > Date.now() ? until : null
}

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
  /** Allow (true) or cancel (false) a one-time SSO relink for this account. */
  onToggleRelink?: (arm: boolean) => void
  onMoveUp?: () => void
  onMoveDown?: () => void
  canMoveUp?: boolean
  canMoveDown?: boolean
}

function VehicleSummaryRow({ vehicle, t }: { vehicle: FamilyVehicleSummary; t: TranslateFn }) {
  const dateLocale = useDateLocale()
  const vehicleTitle = vehicle.year && vehicle.make && vehicle.model
    ? `${vehicle.year} ${vehicle.make} ${vehicle.model}`
    : vehicle.nickname

  // Backend sends an ISO date here, but the schema allows a free-form value
  // (e.g. a mileage string) — only date-shaped values get locale formatting.
  const nextMaintenanceDue = vehicle.next_maintenance_due && ISO_DATE_RE.test(vehicle.next_maintenance_due)
    ? formatDateForDisplay(vehicle.next_maintenance_due, undefined, dateLocale)
    : vehicle.next_maintenance_due

  return (
    <Link
      to={`/vehicles/${vehicle.vin}`}
      className="flex items-center gap-4 p-3 rounded-lg hover:bg-garage-bg transition-colors"
    >
      {/* Vehicle Photo */}
      <div className="w-16 h-12 rounded-lg overflow-hidden bg-garage-border flex-shrink-0">
        {vehicle.main_photo ? (
          <img
            src={withBase(vehicle.main_photo)}
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
              {formatDateForDisplay(vehicle.last_service_date, undefined, dateLocale)}
            </p>
          </>
        ) : (
          <p className="text-sm text-garage-text-muted">{t('familyCard.noServiceRecords')}</p>
        )}
      </div>

      {/* Next Maintenance */}
      <div className="hidden lg:block text-right min-w-32">
        {vehicle.next_maintenance_description ? (
          <>
            <p className="text-sm text-garage-text truncate">{vehicle.next_maintenance_description}</p>
            <p className="text-xs text-garage-text-muted">{nextMaintenanceDue}</p>
          </>
        ) : (
          <p className="text-sm text-garage-text-muted">{t('familyCard.noMaintenanceScheduled')}</p>
        )}
      </div>

      {/* Overdue Badge */}
      {vehicle.overdue_maintenance > 0 && (
        <div className="flex items-center gap-1 px-2 py-1 bg-danger/20 text-danger rounded-full">
          <AlertTriangle className="w-3 h-3" />
          <span className="text-xs font-medium">{vehicle.overdue_maintenance}</span>
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
  onToggleRelink,
  onMoveUp,
  onMoveDown,
  canMoveUp = false,
  canMoveDown = false,
}: FamilyMemberCardProps) {
  const { t } = useTranslation('common')
  const { timeFormat } = useTimeFormat()
  const [isExpanded, setIsExpanded] = useState(defaultExpanded)

  const displayName = member.full_name || member.username
  const relationshipLabel = formatRelationship(member.relationship ?? null, member.relationship_custom, t)

  const isOidc = user?.auth_method === 'oidc'
  const isInactive = user ? !user.is_active : false
  const isSelf = user ? user.id === currentUserId : false
  const isLastAdmin = user ? (user.is_admin && user.is_active && (activeAdminCount ?? 0) === 1) : false
  const relinkUntil = openRelinkUntil(user?.oidc_relink_until)
  const relinkOpen = relinkUntil !== null

  // Permission matrix
  const canToggleDashboard = showActions && !isInactive && membersLoaded && !!onToggleDashboard
  const canEdit = showActions && !!onEdit
  const canResetPassword = showActions && !isOidc && !isInactive && !!onResetPassword
  // Not on your own card: one tap would lock you out. Edit User still can.
  const canToggleActive = showActions && !isLastAdmin && !isSelf && !!onToggleActive
  const canDeleteUser = showActions && !isSelf && !!onDelete
  // Offered to active SSO users, since a disabled one is refused before the
  // relink is read. An open one can be cancelled whoever it's on.
  const canToggleRelink = showActions && ((isOidc && !isInactive) || relinkOpen) && !!onToggleRelink
  const canReorder = showActions && !isInactive && membersLoaded && !!(onMoveUp || onMoveDown)

  const nameId = useId()
  // Icon-only actions repeat on every card, so each one says whose card it is.
  const actionLabel = (action: string): string => t('familyCard.actionFor', { action, name: displayName })

  return (
    <div className={`bg-garage-surface border border-garage-border rounded-lg overflow-hidden ${isInactive ? 'opacity-60' : ''}`}>
      {/* Header. Same split as ServiceVisitList: the whole row toggles, but only
          the chevron is the disclosure button, so the action buttons aren't
          nested inside a role=button and their own clicks stay their own. */}
      <div
        onClick={(e) => {
          if (cameFromNestedControl(e) || isSelectingText()) return
          setIsExpanded(!isExpanded)
        }}
        className="w-full flex items-center gap-4 p-4 hover:bg-garage-bg transition-colors cursor-pointer"
      >
        <button
          type="button"
          onClick={() => setIsExpanded(!isExpanded)}
          aria-expanded={isExpanded}
          aria-labelledby={nameId}
          className="flex-shrink-0 cursor-pointer rounded-row ui-focus-ring"
        >
          {isExpanded ? (
            <ChevronDown aria-hidden="true" className="w-5 h-5 text-garage-text-muted" />
          ) : (
            <ChevronRight aria-hidden="true" className="w-5 h-5 text-garage-text-muted" />
          )}
        </button>

        {/* Avatar */}
        <div className="w-12 h-12 rounded-full bg-garage-border flex items-center justify-center flex-shrink-0">
          <User className="w-6 h-6 text-garage-text-muted" />
        </div>

        {/* Member Info */}
        <div className="flex-1 text-left min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <p id={nameId} className="font-semibold text-garage-text truncate">{displayName}</p>
            {relationshipLabel && (
              <span className="px-2 py-0.5 text-xs bg-info/20 text-info rounded">
                {relationshipLabel}
              </span>
            )}
            {showActions && user?.is_admin && (
              <span className="px-2 py-0.5 text-xs bg-primary/20 text-(--accent-fg) rounded">
                {t('admin')}
              </span>
            )}
            {showActions && isOidc && (
              <span className="px-2 py-0.5 text-xs bg-warning/20 text-warning rounded">
                OIDC
              </span>
            )}
            {showActions && isInactive && (
              <span className="px-2 py-0.5 text-xs bg-danger/20 text-danger rounded">
                {t('inactive')}
              </span>
            )}
            {showActions && relinkOpen && (
              <span className="px-2 py-0.5 text-xs bg-warning/20 text-warning rounded">
                {t('familyCard.relinkOpenUntil', { time: formatTime(relinkUntil, timeFormat) })}
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
          {member.upcoming_maintenance > 0 && (
            <div className="flex items-center gap-1.5 text-info">
              <Bell className="w-4 h-4" />
              <span className="text-sm">{member.upcoming_maintenance}</span>
            </div>
          )}
          {member.overdue_maintenance > 0 && (
            <div className="flex items-center gap-1.5 text-danger">
              <AlertTriangle className="w-4 h-4" />
              <span className="text-sm font-medium">{member.overdue_maintenance}</span>
            </div>
          )}
        </div>

        {/* Action Icons */}
        {showActions && (
          <div className="flex items-center gap-1 flex-shrink-0">
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
                title={member.show_on_family_dashboard ? t('familyCard.hideFromDashboard') : t('familyCard.showOnDashboard')}
                aria-label={actionLabel(member.show_on_family_dashboard ? t('familyCard.hideFromDashboard') : t('familyCard.showOnDashboard'))}
              >
                {member.show_on_family_dashboard ? (
                  <Eye aria-hidden="true" className="w-4 h-4 text-success" />
                ) : (
                  <EyeOff aria-hidden="true" className="w-4 h-4 text-garage-text-muted" />
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
                title={t('familyCard.editUser')}
                aria-label={actionLabel(t('familyCard.editUser'))}
              >
                <Edit aria-hidden="true" className="w-4 h-4 text-garage-text-muted" />
              </button>
            )}

            {/* Reset Password (local auth only, active only) */}
            {canResetPassword && (
              <button
                type="button"
                onClick={() => onResetPassword!()}
                disabled={isUpdating}
                className="p-1.5 hover:bg-garage-border rounded transition-colors disabled:opacity-50"
                title={t('familyCard.resetPassword')}
                aria-label={actionLabel(t('familyCard.resetPassword'))}
              >
                <Key aria-hidden="true" className="w-4 h-4 text-garage-text-muted" />
              </button>
            )}

            {/* SSO relink (active OIDC users, or any account with one open) */}
            {canToggleRelink && (
              <button
                type="button"
                onClick={() => onToggleRelink!(!relinkOpen)}
                disabled={isUpdating}
                className={`p-1.5 rounded transition-colors disabled:opacity-50 ${
                  relinkOpen ? 'bg-warning/20 hover:bg-warning/30' : 'hover:bg-garage-border'
                }`}
                title={relinkOpen ? t('familyCard.cancelSsoRelink') : t('familyCard.allowSsoRelink')}
                aria-label={actionLabel(relinkOpen ? t('familyCard.cancelSsoRelink') : t('familyCard.allowSsoRelink'))}
              >
                {relinkOpen ? (
                  <Link2Off aria-hidden="true" className="w-4 h-4 text-warning" />
                ) : (
                  <Link2 aria-hidden="true" className="w-4 h-4 text-garage-text-muted" />
                )}
              </button>
            )}

            {/* Toggle Active (not the last active admin, not yourself) */}
            {canToggleActive && (
              <button
                type="button"
                onClick={() => onToggleActive!()}
                disabled={isUpdating}
                className="p-1.5 hover:bg-garage-border rounded transition-colors disabled:opacity-50"
                title={isInactive ? t('familyCard.enableUser') : t('familyCard.disableUser')}
                aria-label={actionLabel(isInactive ? t('familyCard.enableUser') : t('familyCard.disableUser'))}
              >
                {isInactive ? (
                  <Power aria-hidden="true" className="w-4 h-4 text-garage-text-muted" />
                ) : (
                  <PowerOff aria-hidden="true" className="w-4 h-4 text-garage-text-muted" />
                )}
              </button>
            )}

            {/* Delete (not self) */}
            {canDeleteUser && (
              <button
                type="button"
                onClick={() => onDelete!()}
                disabled={isUpdating}
                className="p-1.5 hover:bg-danger/20 rounded transition-colors disabled:opacity-50"
                title={t('familyCard.deleteUser')}
                aria-label={actionLabel(t('familyCard.deleteUser'))}
              >
                <Trash2 aria-hidden="true" className="w-4 h-4 text-danger" />
              </button>
            )}
          </div>
        )}

        {/* Reorder Arrows */}
        {canReorder && (
          <div className="flex flex-col gap-0.5 flex-shrink-0">
            <button
              type="button"
              onClick={() => onMoveUp?.()}
              disabled={!canMoveUp || isUpdating}
              className="p-1 hover:bg-garage-border rounded transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              title={t('familyCard.moveUp')}
              aria-label={actionLabel(t('familyCard.moveUp'))}
            >
              <ChevronUp aria-hidden="true" className="w-4 h-4 text-garage-text-muted" />
            </button>
            <button
              type="button"
              onClick={() => onMoveDown?.()}
              disabled={!canMoveDown || isUpdating}
              className="p-1 hover:bg-garage-border rounded transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              title={t('familyCard.moveDown')}
              aria-label={actionLabel(t('familyCard.moveDown'))}
            >
              <ChevronDown aria-hidden="true" className="w-4 h-4 text-garage-text-muted" />
            </button>
          </div>
        )}
      </div>

      {/* Expanded Content */}
      {isExpanded && (
        <div className="border-t border-garage-border">
          {!member.vehicles || member.vehicles.length === 0 ? (
            <div className="p-6 text-center text-garage-text-muted">
              <Car className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p>{t('familyCard.noVehicles')}</p>
            </div>
          ) : (
            <div className="divide-y divide-garage-border">
              {/* Table Header (desktop only) */}
              <div className="hidden md:grid grid-cols-[1fr_auto_auto_auto] gap-4 px-4 py-2 text-xs font-medium text-garage-text-muted uppercase bg-garage-bg">
                <span>{t('familyCard.columnVehicle')}</span>
                <span className="text-right min-w-32">{t('familyCard.columnLastService')}</span>
                <span className="hidden lg:block text-right min-w-32">{t('familyCard.columnNextMaintenance')}</span>
                <span className="w-16"></span>
              </div>

              {/* Vehicle Rows */}
              {member.vehicles.map((vehicle) => (
                <VehicleSummaryRow key={vehicle.vin} vehicle={vehicle} t={t} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
