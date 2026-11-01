import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Calendar, ExternalLink, Gauge, Store } from 'lucide-react'
import type { ServiceVisit, ServiceLineItem } from '../types/serviceVisit'
import FormModalWrapper from './FormModalWrapper'
import { Button, Chip, Mono } from './ui'
import { formatDateForDisplay } from '../utils/dateUtils'
import { formatCurrency } from '../utils/formatUtils'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { useUnitFormat } from '../hooks/useUnitFormat'
import { supplyDisplayUnit, formatSupplyQuantity } from '../utils/supplyUnits'
import {
  INSPECTION_RESULT_KEYS,
  INSPECTION_RESULT_FALLBACK_KEY,
  getServiceCategoryTone,
} from '../constants/serviceVisit'

interface ServiceLineItemDetailProps {
  visit: ServiceVisit
  item: ServiceLineItem
  /** The vehicle's usage tracking, as the list resolved it, so both show the same readings. */
  tracksDistance: boolean
  tracksHours: boolean
  onClose: () => void
}

/** Read-only view of one service on a visit: what was done, what it cost, what was used. */
export default function ServiceLineItemDetail({
  visit,
  item,
  tracksDistance,
  tracksHours,
  onClose,
}: ServiceLineItemDetailProps): ReactElement {
  const { t } = useTranslation('vehicles')
  const { currencyCode, locale } = useCurrencyPreference()
  const { system } = useUnitPreference()
  const u = useUnitFormat()
  const fmt = (n: number) => formatCurrency(n, { currencyCode, locale })

  const usages = item.supply_usages ?? []
  const laborCost = item.cost ? Number(item.cost) : 0
  const partsCost = usages.reduce((sum, usage) => sum + Number(usage.cost_snapshot ?? 0), 0)

  return (
    <FormModalWrapper
      title={item.description}
      onClose={onClose}
      width="md"
      footer={
        <Button variant="secondary" onClick={onClose}>
          {t('common:close')}
        </Button>
      }
    >
      <div className="space-y-5">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-text-mute">
          <span className="flex items-center gap-1.5">
            <Calendar aria-hidden="true" className="w-4 h-4" />
            <Mono size="sm">{formatDateForDisplay(visit.date)}</Mono>
          </span>
          {tracksDistance && visit.odometer_km != null && (
            <span className="flex items-center gap-1.5">
              <Gauge aria-hidden="true" className="w-4 h-4" />
              <Mono size="sm">{u.distance.format(parseFloat(String(visit.odometer_km)))}</Mono>
            </span>
          )}
          {/* Same fixed "hr" symbol as the service list's engine-hours reading. */}
          {tracksHours && visit.engine_hours != null && (
            <span className="flex items-center gap-1.5">
              <Gauge aria-hidden="true" className="w-4 h-4" />
              <Mono size="sm">{Number(visit.engine_hours).toFixed(1)} hr</Mono>
            </span>
          )}
          {visit.vendor && (
            <span className="flex items-center gap-1.5">
              <Store aria-hidden="true" className="w-4 h-4" />
              {visit.vendor.name}
            </span>
          )}
          {item.category && <Chip tone={getServiceCategoryTone(item.category)}>{item.category}</Chip>}
          {item.is_inspection && item.inspection_result && (
            <Chip tone="info">
              {t(INSPECTION_RESULT_KEYS[item.inspection_result] ?? INSPECTION_RESULT_FALLBACK_KEY)}
            </Chip>
          )}
        </div>

        <section className="space-y-2">
          <h4 className="text-xs font-medium text-text-mute uppercase tracking-wide">{t('serviceList.detail.cost')}</h4>
          <div className="bg-surface-2/50 rounded-md p-3 space-y-1 text-sm">
            <div className="flex justify-between text-text-mute">
              <span>{t('serviceList.detail.labor')}</span>
              <Mono size="sm">{fmt(laborCost)}</Mono>
            </div>
            <div className="flex justify-between text-text-mute">
              <span>{t('serviceList.detail.parts')}</span>
              <Mono size="sm">{fmt(partsCost)}</Mono>
            </div>
            <div className="flex justify-between font-medium text-text border-t border-border pt-1 mt-1">
              <span>{t('serviceList.total')}</span>
              <Mono size="sm" weight="semibold">{fmt(laborCost + partsCost)}</Mono>
            </div>
          </div>
        </section>

        <section className="space-y-2">
          <h4 className="text-xs font-medium text-text-mute uppercase tracking-wide">{t('serviceList.detail.supplies')}</h4>
          {usages.length === 0 ? (
            <p className="text-sm text-text-mute">{t('serviceList.detail.noSupplies')}</p>
          ) : (
            <ul className="space-y-1">
              {usages.map((usage) => (
                <li key={usage.id}>
                  <Link
                    to={`/supplies?supply=${usage.supply_id}`}
                    className="group flex items-center justify-between gap-3 rounded-md bg-surface-2/50 px-3 py-2 text-sm transition-colors hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-primary"
                  >
                    <span className="flex min-w-0 items-center gap-1.5 text-text group-hover:text-(--accent-fg)">
                      {/* The link's name is this sentence plus the quantity and cost below,
                          not an aria-label, which would hide those two from a screen reader. */}
                      <span className="sr-only">{t('serviceList.detail.openSupply', { name: usage.supply_name })}</span>
                      <span aria-hidden="true" className="truncate">{usage.supply_name}</span>
                      <ExternalLink aria-hidden="true" className="h-3.5 w-3.5 flex-shrink-0 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" />
                    </span>
                    <span className="flex flex-shrink-0 items-center gap-3 text-text-mute">
                      <Mono size="sm">
                        {formatSupplyQuantity(Number(usage.quantity), supplyDisplayUnit(usage, system), locale)}
                      </Mono>
                      <Mono size="sm">{usage.cost_snapshot != null ? fmt(Number(usage.cost_snapshot)) : '-'}</Mono>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        {item.notes && (
          <section className="space-y-2">
            <h4 className="text-xs font-medium text-text-mute uppercase tracking-wide">{t('lineItemEditor.notes')}</h4>
            <p className="text-sm text-text whitespace-pre-wrap">{item.notes}</p>
          </section>
        )}
      </div>
    </FormModalWrapper>
  )
}
