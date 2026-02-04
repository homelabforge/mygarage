/**
 * Family Member Card - Collapsible card showing member's vehicles and reminders
 */

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronDown, ChevronRight, Car, AlertTriangle, Bell, User } from 'lucide-react'
import type { FamilyMemberData, FamilyVehicleSummary } from '@/types/family'
import { formatRelationship } from '@/types/family'

interface FamilyMemberCardProps {
  member: FamilyMemberData
  defaultExpanded?: boolean
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

export default function FamilyMemberCard({ member, defaultExpanded = false }: FamilyMemberCardProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded)

  const displayName = member.full_name || member.username
  const relationshipLabel = formatRelationship(member.relationship, member.relationship_custom)

  return (
    <div className="bg-garage-surface border border-garage-border rounded-lg overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center gap-4 p-4 hover:bg-garage-bg transition-colors"
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
        <div className="flex-1 text-left">
          <div className="flex items-center gap-2">
            <p className="font-semibold text-garage-text">{displayName}</p>
            {relationshipLabel && (
              <span className="px-2 py-0.5 text-xs bg-info/20 text-info rounded">
                {relationshipLabel}
              </span>
            )}
          </div>
          <p className="text-sm text-garage-text-muted">@{member.username}</p>
        </div>

        {/* Stats */}
        <div className="flex items-center gap-4">
          {/* Vehicle Count */}
          <div className="flex items-center gap-1.5 text-garage-text-muted">
            <Car className="w-4 h-4" />
            <span className="text-sm">{member.vehicle_count}</span>
          </div>

          {/* Upcoming Reminders */}
          {member.upcoming_reminders > 0 && (
            <div className="flex items-center gap-1.5 text-info">
              <Bell className="w-4 h-4" />
              <span className="text-sm">{member.upcoming_reminders}</span>
            </div>
          )}

          {/* Overdue Reminders */}
          {member.overdue_reminders > 0 && (
            <div className="flex items-center gap-1.5 text-danger">
              <AlertTriangle className="w-4 h-4" />
              <span className="text-sm font-medium">{member.overdue_reminders}</span>
            </div>
          )}
        </div>
      </button>

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
