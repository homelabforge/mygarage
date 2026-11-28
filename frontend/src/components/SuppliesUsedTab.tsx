import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Package } from 'lucide-react'
import { Badge, Card, Mono, EmptyState } from '@/components/ui'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'
import { useVehicleSupplyUsages } from '@/hooks/queries/useSupplies'
import { useCurrencyPreference } from '@/hooks/useCurrencyPreference'
import { useUnitPreference } from '@/hooks/useUnitPreference'
import { useDateLocale } from '@/hooks/useDateLocale'
import { useLanguageLocale } from '@/hooks/useLanguageLocale'
import { formatDateForDisplay } from '@/utils/dateUtils'
import {
  formatSupplyQuantity,
  supplyDisplayUnit,
  type SupplyUnit,
} from '@/utils/supplyUnits'
import type { SupplyUsage } from '@/types/supplies'

interface SuppliesUsedTabProps {
  vin: string
}

// Quantity is stored canonically (L for volume, count for count). Show it in
// the supply's own unit.
function formatQuantity(raw: string, unit: SupplyUnit, locale: string): string {
  const canonical = Number(raw)
  return Number.isNaN(canonical) ? raw : formatSupplyQuantity(canonical, unit, locale)
}

export default function SuppliesUsedTab({ vin }: SuppliesUsedTabProps) {
  const { t } = useTranslation('common')
  const { data, isLoading, error } = useVehicleSupplyUsages(vin)
  const { formatCurrency } = useCurrencyPreference()
  const { system } = useUnitPreference()
  const dateLocale = useDateLocale()
  const numberLocale = useLanguageLocale()

  const usages: SupplyUsage[] = data?.usages ?? []

  if (isLoading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-text-mute">{t('supplies.usedTab.loading')}</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-start gap-2 bg-danger/10 border border-danger rounded-lg p-4">
        <AlertTriangle aria-hidden="true" className="w-4 h-4 text-danger flex-shrink-0 mt-0.5" />
        <p className="text-danger">
          {getActionErrorMessage(error, t('supplies.usedTab.loadAction'))}
        </p>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-text">{t('supplies.usedTab.title')}</h2>
        <p className="text-sm text-text-mute">
          {/* The usage-count phrase (translated, key unchanged) is a <Mono> figure. Wrapping the whole
              resolved phrase leaves the accessible text + the i18n key identical. */}
          <Mono size="sm" tone="muted">{t('supplies.usedTab.count', { count: usages.length })}</Mono>
        </p>
      </div>

      {usages.length === 0 ? (
        <EmptyState icon={Package} title={t('supplies.usedTab.empty')} />
      ) : (
        <div className="space-y-3">
          {usages.map((usage) => (
            <Card key={usage.id} padding="sm" className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <h3 className="text-sm font-semibold text-text">{usage.supply_name}</h3>
                <p className="text-xs text-text-mute mt-0.5">
                  {t('supplies.usedTab.quantity')}:{' '}
                  <Mono size="xs" tone="muted">{formatQuantity(usage.quantity, supplyDisplayUnit(usage, system), numberLocale)}</Mono>
                </p>
                {usage.service_visit_date && (
                  <p className="text-xs text-text-mute mt-0.5">
                    <Mono size="xs" tone="muted">{formatDateForDisplay(usage.service_visit_date, undefined, dateLocale)}</Mono>
                  </p>
                )}
              </div>

              <div className="flex flex-col items-end gap-1 flex-shrink-0">
                <span className="flex items-center gap-2">
                  {usage.cost_estimated && <Badge tone="muted">{t('supplies.estimated')}</Badge>}
                  <Mono size="sm">{formatCurrency(usage.cost_snapshot)}</Mono>
                </span>
                {usage.service_visit_id != null && (
                  <Link
                    to={`/vehicles/${vin}?tab=service`}
                    className="text-xs text-(--accent-fg) hover:underline"
                  >
                    {t('supplies.usedTab.viewVisit')}
                  </Link>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
      {usages.some((usage) => usage.cost_estimated) && (
        <p className="text-xs text-text-mute mt-3">{t('supplies.estimatedHint')}</p>
      )}
    </div>
  )
}
