import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Package } from 'lucide-react'
import { useVehicleSupplyUsages } from '@/hooks/queries/useSupplies'
import { useCurrencyPreference } from '@/hooks/useCurrencyPreference'
import { useUnitPreference } from '@/hooks/useUnitPreference'
import { useDateLocale } from '@/hooks/useDateLocale'
import { formatDateForDisplay } from '@/utils/dateUtils'
import {
  canonicalToDisplay,
  supplyUnitLabel,
  type SupplyUnitType,
  type UnitSystem,
} from '@/utils/supplyUnits'
import type { SupplyUsage } from '@/types/supplies'

interface SuppliesUsedTabProps {
  vin: string
}

// Quantity is stored canonically (L for volume, count for count); convert to the
// user's display units and append the unit label (SupplyUsageResponse carries the
// owning supply's unit_type).
function formatQuantity(
  raw: string,
  unitType: SupplyUnitType,
  system: UnitSystem,
  locale: string,
): string {
  const canonical = Number(raw)
  if (Number.isNaN(canonical)) return raw
  const value = canonicalToDisplay(canonical, unitType, system)
  const text = value.toLocaleString(locale, { maximumFractionDigits: 3 })
  const label = supplyUnitLabel(unitType, system)
  return label ? `${text} ${label}` : text
}

export default function SuppliesUsedTab({ vin }: SuppliesUsedTabProps) {
  const { t } = useTranslation('common')
  const { data, isLoading, error } = useVehicleSupplyUsages(vin)
  const { formatCurrency } = useCurrencyPreference()
  const { system } = useUnitPreference()
  const dateLocale = useDateLocale()

  const usages: SupplyUsage[] = data?.usages ?? []

  if (isLoading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">{t('supplies.usedTab.loading')}</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-start gap-2 bg-danger/10 border border-danger rounded-lg p-4">
        <AlertTriangle className="w-4 h-4 text-danger flex-shrink-0 mt-0.5" />
        <p className="text-danger">
          {error instanceof Error ? error.message : t('supplies.usedTab.loadError')}
        </p>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-garage-text">{t('supplies.usedTab.title')}</h2>
        <p className="text-sm text-garage-text-muted">
          {t('supplies.usedTab.count', { count: usages.length })}
        </p>
      </div>

      {usages.length === 0 ? (
        <div className="text-center py-12 bg-garage-surface rounded-lg">
          <Package size={48} className="mx-auto text-garage-text-muted mb-4" />
          <p className="text-garage-text-muted">{t('supplies.usedTab.empty')}</p>
        </div>
      ) : (
        <div className="space-y-3">
          {usages.map((usage) => (
            <div
              key={usage.id}
              className="flex items-start justify-between gap-4 bg-garage-surface rounded-lg p-4 border border-garage-border"
            >
              <div className="min-w-0">
                <h3 className="text-sm font-semibold text-garage-text">{usage.supply_name}</h3>
                <p className="text-xs text-garage-text-muted mt-0.5">
                  {t('supplies.usedTab.quantity')}:{' '}
                  {formatQuantity(usage.quantity, usage.unit_type, system, dateLocale)}
                </p>
                {usage.service_visit_date && (
                  <p className="text-xs text-garage-text-muted mt-0.5">
                    {formatDateForDisplay(usage.service_visit_date, undefined, dateLocale)}
                  </p>
                )}
              </div>

              <div className="flex flex-col items-end gap-1 flex-shrink-0">
                <span className="text-sm font-medium text-garage-text">
                  {formatCurrency(usage.cost_snapshot)}
                </span>
                {usage.service_visit_id != null && (
                  <Link
                    to={`/vehicles/${vin}?tab=service`}
                    className="text-xs text-primary hover:underline"
                  >
                    {t('supplies.usedTab.viewVisit')}
                  </Link>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
