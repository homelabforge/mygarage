import { memo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Car,
  Wrench,
  Fuel,
  Gauge,
  Bell,
  FileText,
  StickyNote,
  Camera,
  TrendingUp,
  AlertCircle,
} from 'lucide-react'
import type { VehicleStatistics } from '../types/dashboard'
import { formatDateForDisplay } from '../utils/dateUtils'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitFormatter } from '../utils/units'

interface VehicleStatisticsCardProps {
  stats: VehicleStatistics
}

function VehicleStatisticsCard({ stats }: VehicleStatisticsCardProps) {
  const navigate = useNavigate()
  const { system, showBoth } = useUnitPreference()

  const handleClick = () => {
    navigate(`/vehicles/${stats.vin}`)
  }

  const formatDate = (dateString?: string): string => {
    if (!dateString) return 'Never'
    return formatDateForDisplay(dateString, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
  }

  const hasActivity =
    stats.total_service_records > 0 ||
    stats.total_fuel_records > 0 ||
    stats.total_odometer_records > 0

  return (
    <div
      onClick={handleClick}
      className="bg-garage-surface border border-garage-border rounded-lg overflow-hidden hover:border-primary transition-all cursor-pointer group"
    >
      {/* Vehicle Header */}
      <div className="relative h-48 bg-gradient-to-br from-primary/20 to-primary/5">
        {stats.main_photo_url ? (
          <img
            src={stats.main_photo_url}
            alt={`${stats.year} ${stats.make} ${stats.model}`}
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="flex items-center justify-center h-full">
            <Car className="w-16 h-16 text-garage-text-muted opacity-50" />
          </div>
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-garage-bg/90 via-garage-bg/50 to-transparent" />
        <div className="absolute bottom-0 left-0 right-0 p-4">
          <h3 className="text-xl font-bold text-white">
            {stats.year} {stats.make} {stats.model}
          </h3>
          <p className="text-sm text-garage-text-muted">{stats.vin}</p>
        </div>

        {/* Reminder badges */}
        {stats.overdue_reminders_count > 0 && (
          <div className="absolute top-3 right-3 bg-danger text-white px-2 py-1 rounded-md text-xs font-semibold flex items-center gap-1">
            <AlertCircle className="w-3 h-3" />
            {stats.overdue_reminders_count} Overdue
          </div>
        )}
        {stats.overdue_reminders_count === 0 && stats.upcoming_reminders_count > 0 && (
          <div className="absolute top-3 right-3 bg-warning text-white px-2 py-1 rounded-md text-xs font-semibold flex items-center gap-1">
            <Bell className="w-3 h-3" />
            {stats.upcoming_reminders_count} Upcoming
          </div>
        )}

        {/* Archived watermark */}
        {stats.archived_at && (
          <div className="absolute inset-0 pointer-events-none overflow-hidden">
            <div className="absolute top-8 right-0 transform rotate-45 translate-x-1/4 -translate-y-1/4 bg-red-600/20 text-red-600 font-bold text-2xl px-16 py-2 border-y-2 border-red-600 shadow-lg">
              ARCHIVED
            </div>
          </div>
        )}
      </div>

      {/* Statistics Grid */}
      <div className="p-4 space-y-3">
        {/* Quick Stats */}
        <div className="grid grid-cols-4 gap-2">
          <StatBadge
            icon={<Wrench className="w-3 h-3" />}
            count={stats.total_service_records}
            label="Service"
          />
          <StatBadge
            icon={<Fuel className="w-3 h-3" />}
            count={stats.total_fuel_records}
            label="Fuel"
          />
          <StatBadge
            icon={<Bell className="w-3 h-3" />}
            count={stats.total_reminders}
            label="Reminders"
          />
          <StatBadge
            icon={<FileText className="w-3 h-3" />}
            count={stats.total_documents}
            label="Docs"
          />
        </div>

        {/* Recent Activity */}
        {hasActivity && (
          <div className="border-t border-garage-border pt-3 space-y-2">
            <h4 className="text-xs font-semibold text-garage-text-muted uppercase">
              Recent Activity
            </h4>
            <div className="space-y-1.5 text-sm">
              {stats.latest_service_date && (
                <ActivityRow
                  icon={<Wrench className="w-3.5 h-3.5" />}
                  label="Last Service"
                  value={formatDate(stats.latest_service_date)}
                />
              )}
              {stats.latest_fuel_date && (
                <ActivityRow
                  icon={<Fuel className="w-3.5 h-3.5" />}
                  label="Last Fill-up"
                  value={formatDate(stats.latest_fuel_date)}
                />
              )}
              {stats.latest_odometer_reading && (
                <ActivityRow
                  icon={<Gauge className="w-3.5 h-3.5" />}
                  label="Latest Odometer"
                  value={UnitFormatter.formatDistance(stats.latest_odometer_reading, system, false)}
                />
              )}
            </div>
          </div>
        )}

        {/* Fuel Economy */}
        {stats.average_mpg && (
          <div className="border-t border-garage-border pt-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-primary" />
                <span className="text-sm text-garage-text-muted">
                  Avg {UnitFormatter.getFuelEconomyUnit(system)}
                </span>
              </div>
              <span className="text-lg font-bold text-garage-text">
                {UnitFormatter.formatFuelEconomy(stats.average_mpg, system, false)}
              </span>
            </div>
            {stats.recent_mpg && stats.recent_mpg !== stats.average_mpg && (
              <div className="text-xs text-garage-text-muted mt-1">
                Recent: {UnitFormatter.formatFuelEconomy(stats.recent_mpg, system, false)}
              </div>
            )}
          </div>
        )}

        {/* Content Counts */}
        <div className="border-t border-garage-border pt-3">
          <div className="flex items-center justify-between text-xs text-garage-text-muted">
            <div className="flex items-center gap-1">
              <Camera className="w-3 h-3" />
              <span>{stats.total_photos} photos</span>
            </div>
            <div className="flex items-center gap-1">
              <StickyNote className="w-3 h-3" />
              <span>{stats.total_notes} notes</span>
            </div>
          </div>
        </div>

        {/* View Details Button */}
        <button
          onClick={handleClick}
          className="w-full py-2 mt-2 bg-primary/10 text-primary rounded-md hover:bg-primary hover:text-white transition-colors font-medium text-sm"
        >
          View Details
        </button>
      </div>
    </div>
  )
}

interface StatBadgeProps {
  icon: React.ReactNode
  count: number
  label: string
}

function StatBadge({ icon, count, label }: StatBadgeProps) {
  return (
    <div className="flex flex-col items-center p-2 bg-garage-bg rounded-md">
      <div className="flex items-center gap-1 text-garage-text-muted mb-0.5">
        {icon}
      </div>
      <div className="text-lg font-bold text-garage-text">{count}</div>
      <div className="text-xs text-garage-text-muted">{label}</div>
    </div>
  )
}

interface ActivityRowProps {
  icon: React.ReactNode
  label: string
  value: string
}

function ActivityRow({ icon, label, value }: ActivityRowProps) {
  return (
    <div className="flex items-center justify-between text-garage-text">
      <div className="flex items-center gap-2">
        <div className="text-garage-text-muted">{icon}</div>
        <span className="text-garage-text-muted">{label}</span>
      </div>
      <span className="font-medium">{value}</span>
    </div>
  )
}

export default memo(VehicleStatisticsCard)
