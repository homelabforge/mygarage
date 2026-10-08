import { useTranslation } from 'react-i18next'
import { Fuel } from 'lucide-react'
import { Button, Chip } from './ui'
import type { FuelPrice, FuelPricesResponse } from '../hooks/queries/useFuelPrices'
import { useDateLocale } from '../hooks/useDateLocale'

interface FuelPriceHintProps {
  prices: FuelPricesResponse | undefined
  /** The EN 16942 label the form currently holds (E10, B7…), to pick the matching pump. */
  grade?: string | null
  /** The octane the form holds, to tell E5 at 95 from E5 at 98. */
  octane?: number | null
  /** The whole answer is still loading. */
  loading?: boolean
  /** Called with the price per litre in the provider's currency. */
  onUsePrice: (price: FuelPrice) => void
  /** The price as the form shows money per volume: the caller owns the
   *  currency, the volume unit and the conversion, this component renders
   *  the string it is given. */
  formatPrice: (price: FuelPrice) => string
  disabled?: boolean
}

/** « 12 min ago » / « il y a 12 min », or null when the time is unknown or odd. */
export function relativeMinutes(iso: string | null | undefined, locale: string, now = Date.now()): string | null {
  if (!iso) return null
  const at = new Date(iso).getTime()
  if (!Number.isFinite(at)) return null
  const minutes = Math.round((at - now) / 60_000)
  if (minutes > 0) return null
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'always' })
  if (minutes > -60) return rtf.format(minutes, 'minute')
  if (minutes > -60 * 48) return rtf.format(Math.round(minutes / 60), 'hour')
  return rtf.format(Math.round(minutes / (60 * 24)), 'day')
}

function matches(price: FuelPrice, grade: string | null | undefined, octane: number | null | undefined) {
  if (!grade || price.grade !== grade) return false
  return price.octane == null || octane == null || price.octane === octane
}

/**
 * The pump prices at the station the fill-up names (#211): one line per fuel
 * the station sells, the fuel the form holds first, and a button that puts
 * that price in the price field. Nothing is rendered when no source covers
 * the country or the station reports nothing: a missing hint is not an error.
 */
export default function FuelPriceHint({
  prices,
  grade,
  octane,
  loading = false,
  onUsePrice,
  formatPrice,
  disabled = false,
}: FuelPriceHintProps) {
  const { t } = useTranslation('forms')
  const locale = useDateLocale()
  if (loading || !prices?.provider) return null
  const station = prices.stations?.[0]
  const stationPrices = station?.prices ?? []
  if (!station || stationPrices.length === 0) {
    return (
      <p className="text-xs text-text-mute" data-testid="fuel-price-hint-empty">
        {prices.warnings?.length ? t('fuel.pricesUnavailable') : t('fuel.pricesNone')}
      </p>
    )
  }
  const ordered = [...stationPrices].sort((a, b) =>
    Number(matches(b, grade, octane)) - Number(matches(a, grade, octane))
  )
  return (
    <div
      className="rounded-lg border border-border-soft bg-surface-2 px-3 py-2 space-y-1"
      data-testid="fuel-price-hint"
    >
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-text-mute">
        <Fuel aria-hidden="true" size={14} />
        <span>
          {t('fuel.pricesTitle', {
            station: station.name ?? station.address ?? station.city ?? station.external_id,
          })}
        </span>
      </div>
      <ul className="space-y-1">
        {ordered.map((price) => {
          const current = matches(price, grade, octane)
          const updated = relativeMinutes(price.updated_at, locale)
          const label = price.octane != null ? `${price.grade} ${price.octane}` : price.grade
          return (
            <li
              key={`${price.grade}-${price.octane ?? ''}`}
              className="flex items-center justify-between gap-2 text-sm"
              data-testid={current ? 'fuel-price-current' : 'fuel-price-other'}
            >
              <span className="flex items-center gap-2 min-w-0">
                <span className="font-medium text-text">{label}</span>
                <span className="text-text">{formatPrice(price)}</span>
                {updated && (
                  <span className="text-xs text-text-mute truncate">
                    {t('fuel.pricesUpdated', { when: updated })}
                  </span>
                )}
                {current && <Chip tone="accent">{t('fuel.pricesCurrentFuel')}</Chip>}
              </span>
              <Button
                type="button"
                variant={current ? 'secondary' : 'ghost'}
                size="sm"
                disabled={disabled}
                onClick={() => onUsePrice(price)}
              >
                {t('fuel.pricesUseThisPrice')}
              </Button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
