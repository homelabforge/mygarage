import { useTranslation } from 'react-i18next'
import { Car, AlertTriangle, AlertCircle, Bell, Gauge } from 'lucide-react'
import type { Vehicle, VehicleDetailStats } from '../../types/vehicle'
import { NON_MOTORIZED_TYPES } from '../../schemas/vehicle'
import { useUnitPreference } from '../../hooks/useUnitPreference'
import { UnitFormatter } from '../../utils/units'
import { formatDateForDisplay } from '../../utils/dateUtils'
import { useDateLocale } from '../../hooks/useDateLocale'
import { getUsageTracking } from '../../utils/usageTracking'
import { Chip, Badge, Mono } from '../ui'

interface VehicleHeroProps {
  vehicle: Vehicle
  photoUrl: string | null
  fromCache: boolean
  detailStats: VehicleDetailStats | null
}

/**
 * Vehicle Detail hero (P5 Task 3). Full-bleed 300px cover photo (or diagonal-
 * stripe placeholder) + bg-derived scrim + absolute display-only overlays
 * (type chip, odometer reading chip incl. the reading DATE, nickname h1,
 * year/make/model, mono VIN), with an overdue/upcoming Badge top-right. All
 * overlays are pointer-events-none (display-only; e2e only asserts
 * .toBeVisible()). Bespoke by design (G4 (a)). Reading is metric-canonical km
 * converted at the boundary (G9). The reading date renders `latest_odometer_km`'s
 * companion `latest_odometer_date` (m2) so every contract field is displayed.
 */
export default function VehicleHero({ vehicle, photoUrl, fromCache, detailStats }: VehicleHeroProps) {
  const { t } = useTranslation('vehicles')
  const { system } = useUnitPreference()
  const dateLocale = useDateLocale()

  const isMotorized =
    vehicle.vehicle_type &&
    !(NON_MOTORIZED_TYPES as readonly string[]).includes(vehicle.vehicle_type)

  // Usage reading(s): engine hours for hour-metered vehicles, odometer
  // distance otherwise — derived from `latest_hours` (the maintained
  // aggregate), NOT the retired stale-hours column. Hours carry no
  // companion date (a single current value). A dual-tracking vehicle (both
  // dimensions enabled) shows its PRIMARY dimension as the headline reading
  // plus the other dimension as a secondary chip.
  const usage = detailStats ? getUsageTracking(detailStats) : null
  const primaryIsHours = usage?.primary === 'hours'
  const isDualTracking = !!usage && usage.tracksDistance && usage.tracksHours

  const primaryReading = primaryIsHours
    ? detailStats?.latest_hours != null
      ? t('vehicleStats.hoursValue', { value: Number(detailStats.latest_hours).toLocaleString() })
      : null
    : isMotorized && detailStats?.latest_odometer_km
      ? UnitFormatter.formatDistance(parseFloat(detailStats.latest_odometer_km), system)
      : null

  const primaryLabel = primaryIsHours ? t('detail.misc.hours') : t('detail.misc.odometer')

  // Companion reading date (m2) — distance only; a formatted date is DATA, not
  // UI copy (G2), so it needs no i18n key. Rendered only when there's a reading.
  const primaryReadingDate =
    !primaryIsHours && primaryReading && detailStats?.latest_odometer_date
      ? formatDateForDisplay(
          detailStats.latest_odometer_date,
          { year: 'numeric', month: 'short', day: 'numeric' },
          dateLocale,
        )
      : null

  // Secondary reading — the OTHER usage dimension, dual-tracking vehicles only.
  const secondaryReading = isDualTracking
    ? primaryIsHours
      ? isMotorized && detailStats?.latest_odometer_km
        ? UnitFormatter.formatDistance(parseFloat(detailStats.latest_odometer_km), system)
        : null
      : detailStats?.latest_hours != null
        ? t('vehicleStats.hoursValue', { value: Number(detailStats.latest_hours).toLocaleString() })
        : null
    : null

  const secondaryLabel = primaryIsHours ? t('detail.misc.odometer') : t('detail.misc.hours')

  const overdue = detailStats?.overdue_count ?? 0
  const upcoming = detailStats?.upcoming_count ?? 0

  return (
    <div className="relative h-[300px] overflow-hidden rounded-[18px] border border-border">
      {/* Photo or diagonal-stripe placeholder */}
      {photoUrl ? (
        <img
          src={photoUrl}
          alt={vehicle.nickname}
          className="pointer-events-none absolute inset-0 h-full w-full object-cover"
        />
      ) : (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center [background:repeating-linear-gradient(135deg,var(--color-photo-a)_0_16px,var(--color-photo-b)_16px_32px)]">
          <Car aria-hidden="true" className="h-20 w-20 text-text-mute opacity-40" />
        </div>
      )}

      {/* Scrim — bg-derived, theme-aware, bottom-up */}
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-bg via-bg/55 to-transparent" />

      {/* Overdue / upcoming badge (top-right, display-only) */}
      {overdue > 0 ? (
        <div className="pointer-events-none absolute right-4 top-4">
          <Badge tone="danger" icon={AlertCircle}>{t('vehicleStats.overdue', { count: overdue })}</Badge>
        </div>
      ) : upcoming > 0 ? (
        <div className="pointer-events-none absolute right-4 top-4">
          <Badge tone="warning" icon={Bell}>{t('vehicleStats.upcoming', { count: upcoming })}</Badge>
        </div>
      ) : null}

      {/* Bottom overlay (display-only): type chip + reading chip + name + ymm + VIN */}
      <div className="pointer-events-none absolute inset-x-6 bottom-5">
        <div className="mb-2 flex flex-wrap items-center gap-2.5">
          <Chip tone="accent">{vehicle.vehicle_type}</Chip>
          {primaryReading ? (
            <span className="inline-flex items-center gap-1.5 rounded-chip bg-badge-bg px-2.5 py-1 text-text-dim">
              <Gauge aria-hidden="true" className="h-3.5 w-3.5" />
              <span className="text-[11px] font-medium">{primaryLabel}</span>
              <span className="text-[11px]">·</span>
              <Mono size="sm">{primaryReading}</Mono>
              {primaryReadingDate ? (
                <>
                  <span className="text-[11px]">·</span>
                  <span className="text-[11px]">{primaryReadingDate}</span>
                </>
              ) : null}
            </span>
          ) : null}
          {secondaryReading ? (
            <span className="inline-flex items-center gap-1.5 rounded-chip bg-badge-bg px-2.5 py-1 text-text-dim">
              <Gauge aria-hidden="true" className="h-3.5 w-3.5" />
              <span className="text-[11px] font-medium">{secondaryLabel}</span>
              <span className="text-[11px]">·</span>
              <Mono size="sm">{secondaryReading}</Mono>
            </span>
          ) : null}
          {vehicle.sold_date ? <Badge tone="warning">{t('vehicleCard.sold')}</Badge> : null}
        </div>
        <h1 className="text-[clamp(24px,3.5vw,32px)] font-extrabold tracking-[-.02em] text-text">
          {vehicle.nickname}
        </h1>
        <p className="mt-0.5 text-sm text-text-mute">
          {[vehicle.year, vehicle.make, vehicle.model].filter(Boolean).join(' ')}
        </p>
        <Mono size="sm" tone="muted" variant="vin" className="mt-1 block [overflow-wrap:anywhere]">
          {vehicle.vin}
        </Mono>
        {fromCache ? (
          <div className="mt-2 flex items-center gap-2 text-xs text-warning">
            <AlertTriangle aria-hidden="true" className="h-4 w-4" />
            <span>{t('detail.offlineCachedData')}</span>
          </div>
        ) : null}
      </div>
    </div>
  )
}
