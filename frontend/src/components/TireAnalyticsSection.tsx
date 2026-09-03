/**
 * Tire wear and life on the Analytics page (spec B).
 *
 * **Readiness comes first, and that is a measurement rather than a taste.** On
 * the instance that asked for tire analytics there were two tires, two
 * readings and zero readings carrying an odometer, so every analytical block
 * would have rendered empty. A page whose job is to display tire data has to
 * first help you produce some, and this block disappears on its own once
 * everything is answerable.
 *
 * Nothing here recomputes a distance or a projection. Every figure is the one
 * `TireService` already computed for the tire card, so the two surfaces cannot
 * drift: a second copy that can disagree with the first is worse than no copy.
 * The status strings are the authority for what to render, and each one has
 * its own wording because collapsing five of them into "unknown" is the defect
 * the typed results exist to prevent.
 */

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Gauge, AlertTriangle } from 'lucide-react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import api from '@/services/api'
import type { Tire, TireReading } from '@/types/tire'
import type { components } from '@/types/api.generated'
import { useUnitFormat } from '../hooks/useUnitFormat'
import { formatDateForDisplay } from '../utils/dateUtils'

type TireAnalytics = components['schemas']['TireAnalyticsSummary']
type TireReadiness = components['schemas']['TireReadiness']

/** Six line colours, reused round-robin. Four corners plus a spare fit inside. */
const SERIES_COLORS = ['#2563eb', '#16a34a', '#d97706', '#dc2626', '#7c3aed', '#0891b2']

/**
 * Fetch this vehicle's tire analytics.
 *
 * `useEffect` + `api.get` rather than react-query, matching the page this
 * section lives on: Analytics.tsx fetches all six of its other payloads this
 * way, and its own tests render it with no `QueryClientProvider`, so a
 * `useQuery` here threw and took the entire page down with it. The provider
 * does exist in the real tree (`App.tsx`), which is why this only ever showed
 * up in tests -- the worst place for a difference to live.
 *
 * A failed fetch leaves `data` null and the section renders nothing, which is
 * how the page's other sections behave and is right for a read-only block: an
 * analytics panel is not worth an error banner over.
 */
export function useTireAnalytics(vin: string) {
  const [data, setData] = useState<TireAnalytics | null>(null)

  useEffect(() => {
    if (!vin) return
    let cancelled = false
    api
      .get<TireAnalytics>(`/analytics/vehicles/${vin}/tires`)
      .then((response) => {
        if (!cancelled) setData(response.data)
      })
      .catch((err) => {
        console.error('Failed to fetch tire analytics:', err)
      })
    return () => {
      cancelled = true
    }
  }, [vin])

  return { data }
}

const num = (v: number | string | null | undefined): number | null =>
  v === null || v === undefined || v === '' ? null : Number(v)

interface TireAnalyticsSectionProps {
  vin: string
}

export default function TireAnalyticsSection({ vin }: TireAnalyticsSectionProps) {
  const { t } = useTranslation('analytics')
  const u = useUnitFormat()
  const { data } = useTireAnalytics(vin)

  const tires: Tire[] = data?.tires ?? []
  /* Gated on data presence and on nothing else (B9). The analytics page's own
     convention is to gate a section on whether it has data, and that is
     sufficient here: a vehicle with no tires recorded gets no empty blocks,
     and anything with tires gets the section whatever its type. Deliberately
     NOT `isMotorized`: `NON_MOTORIZED_TYPES` excludes trailers, which are
     exactly the vehicles that have tires and have blowouts. */
  if (tires.length === 0) return null

  /* Optional at the top level only: every field inside is required in the
     generated type, because the backend always sends the whole block. */
  const readiness: TireReadiness | undefined = data?.readiness
  const live = tires.filter((tire) => tire.retired_on == null)

  const label = (tire: Tire): string => {
    const where = tire.position ?? t('vehicle.tires.inStorage')
    const name = [tire.brand, tire.model_name].filter(Boolean).join(' ')
    return name ? `${where} - ${name}` : where
  }

  /* Tread over time, one series per tire that has two or more tread-bearing
     readings. Recharts wants one row per x value with a column per series, so
     the readings are pivoted by date. A tire with one reading is deliberately
     absent rather than plotted as a single dot: one reading is a point, and a
     point drawn on a trend chart reads as a flat line. */
  const trending = live.filter(
    (tire) => (tire.readings ?? []).filter((r: TireReading) => r.tread_depth_mm != null).length >= 2
  )
  const trendRows = (() => {
    const byDate = new Map<string, Record<string, number | string>>()
    for (const tire of trending) {
      for (const reading of tire.readings ?? []) {
        if (reading.tread_depth_mm == null) continue
        const row = byDate.get(reading.recorded_at) ?? { date: reading.recorded_at }
        const converted = u.tread.toDisplay(num(reading.tread_depth_mm))
        if (converted != null) row[label(tire)] = converted
        byDate.set(reading.recorded_at, row)
      }
    }
    return [...byDate.values()].sort((a, b) => String(a.date).localeCompare(String(b.date)))
  })()

  /**
   * The single most useful thing to record next.
   *
   * Ordered by consequence rather than by count: a tire at or below its
   * minimum is a safety matter and outranks any amount of missing data, and
   * after that the prompts are ranked by how many tires each unblocks. Ties
   * resolve in the order listed, which is stable.
   */
  const nextAction = ((): string | null => {
    if ((readiness?.under_minimum ?? 0) > 0) {
      return t('vehicle.tires.actionUnderMinimum', { count: readiness?.under_minimum ?? 0 })
    }
    const candidates: [number, string][] = [
      [readiness?.needs_second_reading ?? 0, 'actionSecondReading'],
      [readiness?.needs_reading_odometer ?? 0, 'actionReadingOdometer'],
      [readiness?.needs_minimum_tread ?? 0, 'actionMinimumTread'],
      [readiness?.needs_mount_odometer ?? 0, 'actionMountOdometer'],
    ]
    const best = candidates.reduce((a, b) => (b[0] > a[0] ? b : a))
    if (best[0] === 0) return null
    // Spelled out rather than t(`vehicle.tires.${best[1]}`): the i18n usage
    // gate scans for string literals, so a computed key is invisible to it and
    // a typo would ship a raw key to the user.
    switch (best[1]) {
      case 'actionSecondReading':
        return t('vehicle.tires.actionSecondReading', { count: best[0] })
      case 'actionReadingOdometer':
        return t('vehicle.tires.actionReadingOdometer', { count: best[0] })
      case 'actionMinimumTread':
        return t('vehicle.tires.actionMinimumTread', { count: best[0] })
      default:
        return t('vehicle.tires.actionMountOdometer', { count: best[0] })
    }
  })()

  /** What to show for a projection, per `WearStatus`. Exhaustive by design. */
  const projection = (tire: Tire): string => {
    switch (tire.wear_status) {
      case 'projected':
        return tire.projected_km_remaining != null
          ? `~${u.distance.format(num(tire.projected_km_remaining))}` +
              (tire.projected_wear_date
                ? ` · ${formatDateForDisplay(tire.projected_wear_date)}`
                : '')
          : '—'
      case 'at_or_below_minimum':
        return t('vehicle.tires.actionUnderMinimum', { count: 1 })
      case 'no_minimum_set':
        return t('vehicle.tires.actionMinimumTread', { count: 1 })
      case 'insufficient_readings':
        return t('vehicle.tires.actionSecondReading', { count: 1 })
      case 'no_reading_odometers':
        return t('vehicle.tires.actionReadingOdometer', { count: 1 })
      case 'no_distance_on_tire':
      case 'unverified_mount_history':
        // The legacy raw-delta figure is SUPPRESSED, not labelled: an
        // "estimate" badge does not communicate that 648,000 km is
        // structurally invalid rather than merely imprecise.
        return t('vehicle.tires.actionMountOdometer', { count: 1 })
      default:
        return '—'
    }
  }

  /** What to show for distance, per `DistanceStatus`. Never a bare zero. */
  const distance = (tire: Tire): string => {
    switch (tire.distance_status) {
      case 'complete':
        return tire.distance_km != null ? u.distance.format(num(tire.distance_km)) : '—'
      case 'incomplete':
        return tire.known_distance_km != null
          ? `${u.distance.format(num(tire.known_distance_km))} (${
              tire.known_distance_since ? formatDateForDisplay(tire.known_distance_since) : ''
            })`
          : t('vehicle.tires.actionMountOdometer', { count: 1 })
      case 'nothing_bounded':
      case 'no_periods':
        return t('vehicle.tires.actionMountOdometer', { count: 1 })
      case 'spare_only':
        return t('vehicle.tires.inStorage')
      case 'odometer_rollback':
        return '—'
      default:
        return '—'
    }
  }

  return (
    <div className="bg-garage-surface border border-garage-border rounded-lg p-6 mb-8">
      <div className="flex items-center gap-2 mb-4">
        <Gauge className="w-5 h-5 text-garage-text-muted" />
        <h2 className="text-xl font-bold text-garage-text">{t('vehicle.tires.title')}</h2>
      </div>

      {/* Readiness. Only for tires the user can still act on: telling someone
          to add an odometer reading to a tire in a landfill is noise. */}
      {live.length > 0 && (
        <div className="mb-6">
          <h3 className="text-sm font-semibold text-garage-text mb-2">
            {t('vehicle.tires.readinessTitle')}
          </h3>
          <p className="text-garage-text-muted text-sm">
            {t('vehicle.tires.readinessSummary', { total: readiness?.total ?? 0 })}
          </p>
          <ul className="text-garage-text-muted text-sm list-disc list-inside mt-1 space-y-0.5">
            <li>{t('vehicle.tires.canTrend', { count: readiness?.can_trend ?? 0 })}</li>
            <li>{t('vehicle.tires.canProject', { count: readiness?.can_project ?? 0 })}</li>
            <li>
              {t('vehicle.tires.canReportDistance', { count: readiness?.can_report_distance ?? 0 })}
            </li>
          </ul>
          <p className="mt-2 text-sm text-garage-text">
            <strong>
              {nextAction === null ? t('vehicle.tires.allAnswered') : `${t('vehicle.tires.nextAction')}: ${nextAction}`}
            </strong>
          </p>
          {/* Explained once, not per tire: an open period's upper bound is the
              vehicle's latest odometer record, so with none there is no
              distance for any fitted tire however complete its history. */}
          {data?.has_odometer_record === false && (
            <p className="mt-2 flex items-start gap-2 text-sm text-garage-text-muted">
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
              {t('vehicle.tires.noOdometerRecord')}
            </p>
          )}
        </div>
      )}

      <div className="mb-6">
        <h3 className="text-sm font-semibold text-garage-text mb-2">
          {t('vehicle.tires.trendTitle')}
        </h3>
        {trendRows.length === 0 ? (
          <p className="text-garage-text-muted text-sm">{t('vehicle.tires.trendEmpty')}</p>
        ) : (
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={trendRows}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" tickFormatter={(v: string) => formatDateForDisplay(v)} />
              <YAxis unit={u.tread.label} />
              <Tooltip />
              <Legend />
              {trending.map((tire, index) => (
                <Line
                  key={tire.id}
                  type="monotone"
                  dataKey={label(tire)}
                  stroke={SERIES_COLORS[index % SERIES_COLORS.length]}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Retired tires are here and not in readiness (B10): their final
          distance and wear are the most complete data the app will ever hold
          about them, and they are also the tires nothing can be done about. */}
      <h3 className="text-sm font-semibold text-garage-text mb-2">
        {t('vehicle.tires.tableTitle')}
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-garage-text-muted border-b border-garage-border">
              <th className="py-2 pr-4 font-medium">{t('vehicle.tires.colTire')}</th>
              <th className="py-2 pr-4 font-medium">{t('vehicle.tires.colTread')}</th>
              <th className="py-2 pr-4 font-medium">{t('vehicle.tires.colProjection')}</th>
              <th className="py-2 font-medium">{t('vehicle.tires.colDistance')}</th>
            </tr>
          </thead>
          <tbody>
            {tires.map((tire) => (
              <tr key={tire.id} className="border-b border-garage-border last:border-0">
                <td className="py-2 pr-4 text-garage-text">
                  {label(tire)}
                  {tire.retired_on && (
                    <span className="ml-2 text-xs text-garage-text-muted">
                      {t('vehicle.tires.retiredOn', {
                        date: formatDateForDisplay(tire.retired_on),
                      })}
                    </span>
                  )}
                </td>
                <td className="py-2 pr-4 font-mono text-garage-text">
                  {tire.tread_depth_mm != null ? u.tread.format(num(tire.tread_depth_mm)) : '—'}
                </td>
                <td className="py-2 pr-4 text-garage-text-muted">{projection(tire)}</td>
                <td className="py-2 text-garage-text-muted">{distance(tire)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
