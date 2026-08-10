import { memo } from 'react'
import { useTranslation } from 'react-i18next'
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
  Share2,
  ChevronRight,
} from 'lucide-react'
import type { VehicleStatistics } from '../types/dashboard'
import { formatDateForDisplay } from '../utils/dateUtils'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitFormatter } from '../utils/units'
import { withBase } from '../utils/basePath'
import { getUsageTracking } from '../utils/usageTracking'
import VehicleLiveLinkWidget from './livelink/VehicleLiveLinkWidget'
import { ListRow, Tile, Badge, Mono } from './ui'

interface VehicleStatisticsCardProps {
  stats: VehicleStatistics
}

function VehicleStatisticsCard({ stats }: VehicleStatisticsCardProps) {
  const { t } = useTranslation('vehicles')
  const navigate = useNavigate()
  const { system } = useUnitPreference()

  const handleClick = () => {
    navigate(`/vehicles/${stats.vin}`)
  }

  const formatDate = (dateString?: string): string => {
    if (!dateString) return t('vehicleStats.never')
    return formatDateForDisplay(dateString, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
  }

  const usage = getUsageTracking(stats)
  const hasActivity =
    stats.total_service_records > 0 ||
    stats.total_fuel_records > 0 ||
    stats.total_odometer_records > 0 ||
    (usage.tracksHours && stats.latest_hours != null)

  const typeLabels: Record<string, string> = {
    Car: t('vehicleTypeLabels.Car'),
    SUV: t('vehicleTypeLabels.SUV'),
    Truck: t('vehicleTypeLabels.Truck'),
    Motorcycle: t('vehicleTypeLabels.Motorcycle'),
    ATV: t('vehicleTypeLabels.ATV'),
    RV: t('vehicleTypeLabels.RV'),
    Trailer: t('vehicleTypeLabels.Trailer'),
    FifthWheel: t('vehicleTypeLabels.FifthWheel'),
    TravelTrailer: t('vehicleTypeLabels.TravelTrailer'),
    Electric: t('vehicleTypeLabels.Electric'),
    Hybrid: t('vehicleTypeLabels.Hybrid'),
  }
  const typeLabel = stats.vehicle_type
    ? (typeLabels[stats.vehicle_type] ?? stats.vehicle_type)
    : null

  return (
    <article className="group relative isolate overflow-hidden rounded-card border border-border bg-surface ui-motion hover:shadow-card-hover">
      {/* Image header — real photo or diagonal-stripe placeholder */}
      <div className="relative h-[172px] overflow-hidden [background:repeating-linear-gradient(135deg,var(--color-photo-a)_0_13px,var(--color-photo-b)_13px_26px)]">
        {stats.main_photo_url ? (
          <img
            src={withBase(stats.main_photo_url)}
            alt={`${stats.year} ${stats.make} ${stats.model}`}
            className="pointer-events-none h-full w-full object-cover"
          />
        ) : (
          <div className="pointer-events-none flex h-full items-center justify-center">
            <Car aria-hidden="true" className="h-16 w-16 text-text-mute opacity-40" />
          </div>
        )}
        {/* Scrim — bg-derived, theme-aware */}
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-bg via-bg/55 to-transparent" />

        {/* Name + type chip + VIN overlay (display-only) */}
        <div className="pointer-events-none absolute inset-x-4 bottom-3">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[19px] font-bold tracking-[-.01em] text-text">
              {stats.year} {stats.make} {stats.model}
            </h3>
            {typeLabel ? <Badge>{typeLabel}</Badge> : null}
          </div>
          <Mono size="sm" tone="muted" variant="vin" className="mt-1 block">
            {stats.vin}
          </Mono>
        </div>

        {/* Shared badge (display-only). The wrapper is pointer-events-none
            (overlay chrome), so a `title` here can never fire on hover — the
            can-edit/view-only distinction goes in an sr-only span inside the
            Badge instead, which stays in the accessibility tree regardless
            of pointer-events. Badge has no aria-label passthrough, so this
            is the reliably-exposed option without touching the primitive. */}
        {stats.is_shared_with_me && (
          <div className="pointer-events-none absolute left-3 top-3">
            <Badge tone="info" icon={Share2}>
              {t('vehicleStatisticsCardExtra.sharedBadge')}
              <span className="sr-only">
                {' '}
                {stats.share_permission === 'write'
                  ? t('vehicleStatisticsCardExtra.sharedByCanEdit', { username: stats.shared_by_username })
                  : t('vehicleStatisticsCardExtra.sharedByViewOnly', { username: stats.shared_by_username })}
              </span>
            </Badge>
          </div>
        )}

        {/* Overdue badge (danger, top-right, only when applicable) */}
        {stats.overdue_maintenance_count > 0 && (
          <div className="pointer-events-none absolute right-3 top-3">
            <Badge tone="danger" icon={AlertCircle}>
              {t('vehicleStats.overdue', { count: stats.overdue_maintenance_count })}
            </Badge>
          </div>
        )}
        {stats.overdue_maintenance_count === 0 && stats.upcoming_maintenance_count > 0 && (
          <div className="pointer-events-none absolute right-3 top-3">
            <Badge tone="warning" icon={Bell}>
              {t('vehicleStats.upcoming', { count: stats.upcoming_maintenance_count })}
            </Badge>
          </div>
        )}

        {/* Archived watermark */}
        {stats.archived_at && (
          <div className="pointer-events-none absolute inset-0 overflow-hidden">
            <div className="absolute right-0 top-8 translate-x-1/4 -translate-y-1/4 rotate-45 border-y-2 border-danger bg-danger/15 px-16 py-2 text-2xl font-bold text-danger shadow-lg">
              {t('vehicleStatisticsCardExtra.archivedWatermark')}
            </div>
          </div>
        )}
      </div>

      {/* Body */}
      <div className="space-y-3 p-4">
        {stats.is_shared_with_me && (
          <p className="text-sm text-text-mute">
            {stats.share_permission === 'write'
              ? t('vehicleStatisticsCardExtra.sharedByCanEdit', {
                  username: stats.shared_by_username,
                })
              : t('vehicleStatisticsCardExtra.sharedByViewOnly', {
                  username: stats.shared_by_username,
                })}
            {stats.owner_relationship
              ? ` · ${
                  stats.owner_relationship === 'other' && stats.owner_relationship_custom
                    ? stats.owner_relationship_custom
                    : t(`common:relationships.${stats.owner_relationship}`, {
                        defaultValue: stats.owner_relationship,
                      })
                }`
              : null}
          </p>
        )}
        {/* Four metric tiles */}
        <div className="grid grid-cols-4 gap-2">
          <Tile icon={Wrench} value={stats.total_service_records} label={t('vehicleStats.service')} />
          <Tile icon={Fuel} value={stats.total_fuel_records} label={t('vehicleStats.fuel')} />
          <Tile
            icon={Bell}
            value={stats.total_maintenance_items}
            label={t('vehicleStats.maintenance')}
            tone={stats.overdue_maintenance_count > 0 ? 'danger' : 'default'}
          />
          <Tile icon={FileText} value={stats.total_documents} label={t('vehicleStats.docs')} />
        </div>

        {/* Recent activity */}
        {hasActivity && (
          <div className="space-y-2 border-t border-border pt-3">
            <h4 className="text-xs font-semibold uppercase text-text-mute">{t('vehicleStats.recentActivity')}</h4>
            <div className="space-y-1.5 text-sm">
              {stats.latest_service_date && (
                <ListRow icon={Wrench} label={t('vehicleStats.lastService')} value={formatDate(stats.latest_service_date)} />
              )}
              {stats.latest_fuel_date && (
                <ListRow icon={Fuel} label={t('vehicleStats.lastFillUp')} value={formatDate(stats.latest_fuel_date)} />
              )}
              {usage.tracksDistance && stats.latest_odometer_km && (
                <ListRow
                  icon={Gauge}
                  label={t('vehicleStats.latestOdometer')}
                  value={UnitFormatter.formatDistance(
                    parseFloat(String(stats.latest_odometer_km)),
                    system,
                    false
                  )}
                />
              )}
              {usage.tracksHours && stats.latest_hours != null && (
                <ListRow
                  icon={Gauge}
                  label={t('vehicleStats.latestHours')}
                  value={t('vehicleStats.hoursValue', {
                    value: Number(stats.latest_hours).toLocaleString(),
                  })}
                />
              )}
            </div>
          </div>
        )}

        {/* Highlight strip — average fuel economy (accent). MPG is distance-
            based (hidden for hour-metered vehicles); GPH/L·hr is the hours
            analog (Phase 13's formatFuelRate/getFuelRateUnit), hidden for
            distance-only vehicles. A dual-tracking vehicle shows both. */}
        {((usage.tracksDistance && stats.average_l_per_100km) ||
          (usage.tracksHours && stats.average_l_per_hr)) && (
          <div className="space-y-3 border-t border-border pt-3">
            {usage.tracksDistance && stats.average_l_per_100km && (
              <div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <TrendingUp aria-hidden="true" className="h-4 w-4 text-(--accent-fg)" />
                    <span className="text-sm text-text-mute">
                      {t('vehicleStatisticsCardExtra.averageFuelEconomy', {
                        unit: UnitFormatter.getFuelEconomyUnit(system),
                      })}
                    </span>
                  </div>
                  <Mono size="lg" weight="bold" tone="accent">
                    {UnitFormatter.formatFuelEconomy(parseFloat(String(stats.average_l_per_100km)), system, false)}
                  </Mono>
                </div>
                {stats.recent_l_per_100km && stats.recent_l_per_100km !== stats.average_l_per_100km && (
                  <div className="mt-1 text-xs text-text-mute">
                    {t('vehicleStats.recent')}: {UnitFormatter.formatFuelEconomy(parseFloat(String(stats.recent_l_per_100km)), system, false)}
                  </div>
                )}
              </div>
            )}
            {usage.tracksHours && stats.average_l_per_hr && (
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <TrendingUp aria-hidden="true" className="h-4 w-4 text-(--accent-fg)" />
                  <span className="text-sm text-text-mute">
                    {t('vehicleStatisticsCardExtra.averageFuelEconomy', {
                      unit: UnitFormatter.getFuelRateUnit(system),
                    })}
                  </span>
                </div>
                <Mono size="lg" weight="bold" tone="accent">
                  {UnitFormatter.formatFuelRate(parseFloat(String(stats.average_l_per_hr)), system, false)}
                </Mono>
              </div>
            )}
          </div>
        )}

        {/* LiveLink widget (telemetry, out of P4 reskin scope) — its own root
            carries `relative z-10` (Step 4c) so it sits ABOVE the footer button's
            stretched pseudo-element and stays independently clickable + keyboard-
            operable. */}
        <VehicleLiveLinkWidget vin={stats.vin} />

        {/* Footer — counts (non-interactive) + the stretched-link nav button.
            The button is STATIC (no `relative`/`z`), so its `after:inset-0`
            anchors to the `relative` <article> root and overlays the WHOLE card:
            a click anywhere on the card navigates, and the button is natively
            keyboard-operable. It is the only interactive nav target (a11y model
            above); LiveLink's `z-10` keeps it above this pseudo-element. */}
        <div className="flex items-center justify-between border-t border-border pt-3">
          <div className="flex items-center gap-4 text-[11.5px] text-text-faint">
            <span className="flex items-center gap-1">
              <Camera aria-hidden="true" className="h-3 w-3" />
              {t('vehicleStats.photoCount', { count: stats.total_photos })}
            </span>
            <span className="flex items-center gap-1">
              <StickyNote aria-hidden="true" className="h-3 w-3" />
              {t('vehicleStats.noteCount', { count: stats.total_notes })}
            </span>
          </div>
          <button
            type="button"
            onClick={handleClick}
            className="ui-focus-ring flex cursor-pointer items-center gap-1 rounded-control text-[12.5px] font-semibold text-(--accent-fg) after:absolute after:inset-0 after:content-['']"
          >
            {t('vehicleStatisticsCardExtra.viewDetails')}
            <ChevronRight aria-hidden="true" className="h-4 w-4" />
          </button>
        </div>
      </div>
    </article>
  )
}

export default memo(VehicleStatisticsCard)
