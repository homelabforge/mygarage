/**
 * Every term and insurer in one policy's chain, oldest first, with what the
 * premium did from one to the next. For reviewing what insurance has cost and
 * what the last renewal changed.
 */

import { useTranslation } from 'react-i18next'
import { TrendingDown, TrendingUp } from 'lucide-react'
import FormModalWrapper from '../FormModalWrapper'
import { Badge, Button, Mono } from '../ui'
import { usePolicyHistory } from '../../hooks/queries/useInsuranceRecords'
import { formatDateForDisplay } from '../../utils/dateUtils'
import { useDateLocale } from '../../hooks/useDateLocale'
import { formatCurrency } from '../../utils/formatUtils'
import { useCurrencyPreference } from '../../hooks/useCurrencyPreference'
import { getActionErrorMessage } from '../../utils/httpErrorHandler'
import type { InsurancePolicy } from '../../types/insurance'

interface PolicyHistoryDialogProps {
  policy: InsurancePolicy
  onClose: () => void
}

export default function PolicyHistoryDialog({ policy, onClose }: PolicyHistoryDialogProps) {
  const { t } = useTranslation('vehicles')
  const { data: history = [], isLoading, error } = usePolicyHistory(policy.id)
  const dateLocale = useDateLocale()
  const { currencyCode, locale } = useCurrencyPreference()

  const money = (value: string | number): string => formatCurrency(value, { currencyCode, locale })
  const formatDate = (value: string): string =>
    formatDateForDisplay(value, { year: 'numeric', month: 'short', day: 'numeric' }, dateLocale)

  return (
    <FormModalWrapper
      title={t('insurancePolicies.historyTitle')}
      onClose={onClose}
      width="md"
      footer={
        <Button variant="secondary" onClick={onClose}>
          {t('common:close')}
        </Button>
      }
    >
      <div className="p-6">
        {isLoading && <p className="text-text-mute">{t('insuranceList.loading')}</p>}
        {error && (
          <p className="text-danger">
            {getActionErrorMessage(error, t('insurancePolicies.historyLoadAction'))}
          </p>
        )}
        <ol className="space-y-3">
          {history.map((entry) => {
            const change = entry.premium_change != null ? Number(entry.premium_change) : null
            const previous =
              change != null && entry.premium_amount != null
                ? Number(entry.premium_amount) - change
                : null
            const percent = change != null && previous ? Math.round((change / previous) * 100) : null
            return (
              <li
                key={entry.id}
                aria-current={entry.is_current ? 'true' : undefined}
                className={`rounded-lg border p-4 ${
                  entry.is_current ? 'border-(--accent-line) bg-(--accent-soft)' : 'border-border-soft bg-surface-2'
                }`}
              >
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="min-w-0">
                    <span className="font-medium text-text">{entry.provider}</span>{' '}
                    <Mono size="sm" tabular={false} className="text-text-mute">
                      {entry.policy_number}
                    </Mono>
                  </div>
                  {entry.premium_amount != null && (
                    <Mono size="sm" className="text-text">
                      {money(entry.premium_amount)}
                      {entry.premium_frequency ? ` / ${entry.premium_frequency}` : ''}
                    </Mono>
                  )}
                </div>
                <p className="text-sm text-text-mute mt-1">
                  {formatDate(entry.start_date)} – {formatDate(entry.end_date)}
                </p>
                {change != null && change !== 0 && (
                  <p className="mt-2">
                    <Badge
                      tone={change > 0 ? 'warning' : 'success'}
                      icon={change > 0 ? TrendingUp : TrendingDown}
                    >
                      {t('insurancePolicies.premiumChange', {
                        amount: `${change > 0 ? '+' : '-'}${money(Math.abs(change))}`,
                        percent: percent != null ? `${percent > 0 ? '+' : ''}${percent}%` : '',
                      })}
                    </Badge>
                  </p>
                )}
                {(entry.vehicles ?? []).length > 0 && (
                  <ul className="mt-3 space-y-1 text-sm">
                    {(entry.vehicles ?? []).map((vehicle) => (
                      <li key={vehicle.id} className="flex justify-between gap-2">
                        <span className="text-text-dim">{vehicle.vehicle_name}</span>
                        {vehicle.effective_share != null && (
                          <Mono size="sm" className="text-text-dim">
                            {money(vehicle.effective_share)}
                          </Mono>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            )
          })}
        </ol>
      </div>
    </FormModalWrapper>
  )
}
