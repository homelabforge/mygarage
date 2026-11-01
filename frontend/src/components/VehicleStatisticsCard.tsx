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
  Truck,
  Flame,
} from 'lucide-react'
import type { VehicleStatistics } from '../types/dashboard'
import { formatDateForDisplay } from '../utils/dateUtils'
import { useUnitFormat } from '../hooks/useUnitFormat'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { formatFuelRate, formatVolumeRate, fuelRateLabel, PER_MONTH } from '../utils/unitFormat'
import { withBase } from '../utils/basePath'
import { getUsageTracking } from '../utils/usageTracking'
import { vehicleLogKinds } from '../utils/vehicleLogKinds'
import { yearMakeModel } from '../utils/vehicleLabel'
import VehicleLiveLinkWidget from './livelink/VehicleLiveLinkWidget'
import { ListRow, Tile, Badge, Mono } from './ui'
import { unlessSelectingText } from '../utils/textSelection'

/** How many tanks `recent_l_per_100km` covers: `_RECENT_WINDOW` in the backend's routes/dashboard.py. */
const RECENT_TANKS = 3

interface VehicleStatisticsCardProps {
  stats: VehicleStatistics
  selectMode?: boolean
  selected?: boolean
  onToggleSelect?: (vin: string) => void
}

function VehicleStatisticsCard({ stats, selectMode = false, selected = false, onToggleSelect }: VehicleStatisticsCardProps) {
  const { t } = useTranslation('vehicles')
  const navigate = useNavigate()
  const u = useUnitFormat()
  // The engine-hours rate is a DERIVED quantity (volume per a dimensionless
  // hour), so it composes from the resolved set rather than reading one of
  // `u`'s ten per-quantity formatters.
  const { units } = useUnitPreference()

  const handleClick = () => {
    if (selectMode) {
      onToggleSelect?.(stats.vin)
      return
    }
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

  // Fuel economy and towing (issue #181). The headline leaves towing tanks out,
  // matching the vehicle's own Fuel tab, and the towing tanks get a line of
  // their own; the headline says "not towing" only when there is such a line.
  // A vehicle that never tows shows one number and no explaining.
  //
  // A vehicle whose every tank was towing has NO ordinary figure. Hiding the
  // strip would hide a number it genuinely has, so the towing one headlines
  // instead and says so; an unlabelled towing figure in the headline is the bug
  // #181 fixed, so that case must never fall through silently.
  const towingEconomy = stats.towing_l_per_100km
  const headlineIsTowing = stats.average_l_per_100km == null && towingEconomy != null
  const headlineEconomy = headlineIsTowing ? towingEconomy : stats.average_l_per_100km
  const headlineRecent = headlineIsTowing ? null : stats.recent_l_per_100km
  const showTowingLine = !headlineIsTowing && towingEconomy != null

  // Towable RVs (fifth wheels and travel trailers: they log propane and are
  // not motorized) have no odometer and no MPG. Their card fills those two
  // slots with the tow vehicle and propane use per month, so the cards line
  // up with the motorized ones beside them.
  const kinds = vehicleLogKinds(stats)
  const isTowableRv = kinds.propane && !kinds.motorized
  const towVehicleLabel = isTowableRv && stats.tow_vehicle ? yearMakeModel(stats.tow_vehicle) : null
  const propaneRate =
    isTowableRv && stats.propane_l_per_month != null ? parseFloat(String(stats.propane_l_per_month)) : null
  const recentPropaneRate =
    propaneRate != null && stats.recent_propane_l_per_month != null
      ? parseFloat(String(stats.recent_propane_l_per_month))
      : null

  const hasActivity =
    towVehicleLabel != null ||
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
    Boat: t('vehicleTypeLabels.Boat'),
    UTV: t('vehicleTypeLabels.UTV'),
    Snowmobile: t('vehicleTypeLabels.Snowmobile'),
    Bicycle: t('vehicleTypeLabels.Bicycle'),
    EBike: t('vehicleTypeLabels.EBike'),
  }
  // Null is a stored type the app doesn't know, so it says so rather than
  // dropping the badge.
  const typeLabel = stats.vehicle_type
    ? (typeLabels[stats.vehicle_type] ?? stats.vehicle_type)
    : t('common:unknown')

  return (
    <article
      className={`group relative isolate overflow-hidden rounded-card border bg-surface ui-motion hover:shadow-card-hover ${
        selected ? 'border-primary ring-2 ring-primary/30' : 'border-border'
      }`}
    >
      {selectMode && (
        <div className="absolute left-3 top-3 z-20">
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggleSelect?.(stats.vin)}
            onClick={(e) => e.stopPropagation()}
            aria-label={t('dashboard.selectVehicles')}
            className="h-5 w-5 rounded border-border accent-(--accent-solid)"
          />
        </div>
      )}
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

        {/* Name + type chip + VIN overlay.
            ★ NOT display-only any more, and it needs BOTH changes below to be
            selectable (issue #179). `pointer-events-none` stops the text
            receiving a selection at all, and the footer button's
            `after:inset-0` covers the whole card, so dropping one without the
            other changes nothing. `relative z-10` lifts it over that
            pseudo-element, the same trick the LiveLink widget already uses.
            Lifting it also takes it OUT of the stretched nav target, so it
            carries `handleClick` itself or clicking the title would silently
            stop navigating. No `tabIndex` or `role`: the footer button is still
            the only focusable nav target, which keeps the a11y model intact. */}
        <div
          className="absolute inset-x-4 bottom-3 z-10"
          onClick={unlessSelectingText(handleClick)}
        >
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[19px] font-bold tracking-[-.01em] text-text">
              {stats.year} {stats.make} {stats.model}
            </h3>
            <Badge>{typeLabel}</Badge>
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
        {/* Due-soon badge (warning); the REMINDERS tile below counts every reminder. */}
        {stats.overdue_maintenance_count === 0 && stats.due_soon_maintenance_count > 0 && (
          <div className="pointer-events-none absolute right-3 top-3">
            <Badge tone="warning" icon={Bell}>
              {t('vehicleStats.dueSoon', { count: stats.due_soon_maintenance_count })}
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
                  value={u.distance.formatPrimary(parseFloat(String(stats.latest_odometer_km)))}
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
              {towVehicleLabel && (
                <ListRow icon={Truck} label={t('vehicleStats.towedBy')} value={towVehicleLabel} />
              )}
            </div>
          </div>
        )}

        {/* Highlight strip — average fuel economy (accent). Consumption is
            distance-based (hidden for hour-metered vehicles); the fuel rate is
            the hours analog, volume per engine hour, hidden for distance-only
            vehicles. A dual-tracking vehicle shows both. Each names the unit
            the reader's own resolved set chose, so the strip cannot disagree
            with the odometer row above it. */}
        {((usage.tracksDistance && headlineEconomy) ||
          (usage.tracksHours && stats.average_l_per_hr) ||
          propaneRate != null) && (
          <div className="space-y-3 border-t border-border pt-3">
            {usage.tracksDistance && headlineEconomy && (
              <div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <TrendingUp aria-hidden="true" className="h-4 w-4 text-(--accent-fg)" />
                    <span className="text-sm text-text-mute">
                      {t(
                        showTowingLine
                          ? 'vehicleStatisticsCardExtra.averageFuelEconomyNotTowing'
                          : 'vehicleStatisticsCardExtra.averageFuelEconomy',
                        { unit: u.consumption.label },
                      )}
                    </span>
                  </div>
                  <Mono size="lg" weight="bold" tone="accent">
                    {u.consumption.formatPrimary(parseFloat(String(headlineEconomy)))}
                  </Mono>
                </div>
                {headlineIsTowing && (
                  <div className="mt-1 text-xs text-text-mute">{t('vehicleStats.towingAll')}</div>
                )}
                {headlineRecent && headlineRecent !== headlineEconomy && (
                  <div className="mt-1 text-xs text-text-mute">
                    {t('vehicleStats.lastTanks', { tanks: RECENT_TANKS })}:{' '}
                    {u.consumption.formatPrimary(parseFloat(String(headlineRecent)))}
                  </div>
                )}
                {showTowingLine && (
                  <div className="mt-1 text-xs text-text-mute">
                    {t('vehicleStats.towing')}: {u.consumption.formatPrimary(parseFloat(String(towingEconomy)))}
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
                      unit: fuelRateLabel(units),
                    })}
                  </span>
                </div>
                <Mono size="lg" weight="bold" tone="accent">
                  {formatFuelRate(units, parseFloat(String(stats.average_l_per_hr)))}
                </Mono>
              </div>
            )}
            {propaneRate != null && (
              <div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Flame aria-hidden="true" className="h-4 w-4 text-(--accent-fg)" />
                    <span className="text-sm text-text-mute">{t('vehicleStats.averagePropane')}</span>
                  </div>
                  <Mono size="lg" weight="bold" tone="accent">
                    {formatVolumeRate(units, propaneRate, PER_MONTH)}
                  </Mono>
                </div>
                {recentPropaneRate != null && recentPropaneRate !== propaneRate && (
                  <div className="mt-1 text-xs text-text-mute">
                    {t('vehicleStats.lastRefills', { count: RECENT_TANKS })}:{' '}
                    {formatVolumeRate(units, recentPropaneRate, PER_MONTH)}
                  </div>
                )}
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
