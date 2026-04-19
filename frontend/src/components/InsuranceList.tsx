import { Shield, Plus, Trash2, Edit3, Calendar } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import type { InsurancePolicy } from '../types/insurance'
import { useInsuranceRecords, useDeleteInsuranceRecord } from '../hooks/queries/useInsuranceRecords'
import { formatDateForDisplay, formatDateForInput } from '../utils/dateUtils'
import { useDateLocale } from '../hooks/useDateLocale'
import { formatCurrency } from '../utils/formatUtils'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'

interface InsuranceListProps {
  vin: string
  onAddClick: () => void
  onEditClick: (policy: InsurancePolicy) => void
}

export default function InsuranceList({ vin, onAddClick, onEditClick }: InsuranceListProps) {
  const { t } = useTranslation('vehicles')
  const { data: policies = [], isLoading, error } = useInsuranceRecords(vin)
  const deleteMutation = useDeleteInsuranceRecord(vin)
  const dateLocale = useDateLocale()
  const { currencyCode, locale } = useCurrencyPreference()

  const handleDelete = (policyId: number) => {
    if (!confirm(t('insuranceList.confirmDelete'))) {
      return
    }

    deleteMutation.mutate(policyId, {
      onError: (err) => {
        toast.error(err instanceof Error ? err.message : t('insuranceList.deleteError'))
      },
    })
  }

  const formatDate = (dateString: string): string => {
    return formatDateForDisplay(dateString, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    }, dateLocale)
  }

  const isExpired = (endDate: string): boolean => {
    // end_date is a backend `date` (YYYY-MM-DD), not a datetime. Compare as
    // calendar days in the user's local timezone via lexicographic YYYY-MM-DD
    // comparison — avoids the UTC-midnight drift a Date-based compare would
    // introduce for users west of UTC.
    return endDate < formatDateForInput()
  }

  if (isLoading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">{t('insuranceList.loading')}</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-danger/10 border border-danger rounded-lg p-4">
        <p className="text-danger">{error.message}</p>
      </div>
    )
  }

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-2xl font-bold text-garage-text">{t('insuranceList.title')}</h2>
          <p className="text-sm text-garage-text-muted">
            {t('insuranceList.policyCount', { count: policies.length })}
          </p>
        </div>
        <button
          onClick={onAddClick}
          className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
        >
          <Plus size={20} />
          {t('insuranceList.addPolicy')}
        </button>
      </div>

      {policies.length === 0 ? (
        <div className="text-center py-12 bg-garage-surface rounded-lg">
          <Shield size={48} className="mx-auto text-garage-text-muted mb-4" />
          <p className="text-garage-text-muted mb-4">{t('insuranceList.noRecords')}</p>
          <button onClick={onAddClick} className="inline-flex items-center gap-2 btn btn-primary rounded-lg transition-colors">
            {t('insuranceList.addFirstPolicy')}
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          {policies.map((policy) => (
            <div
              key={policy.id}
              className={`bg-garage-surface rounded-lg p-6 border ${
                isExpired(policy.end_date)
                  ? 'border-danger/30'
                  : 'border-garage-border'
              }`}
            >
              <div className="flex justify-between items-start mb-4">
                <div className="flex items-start gap-3">
                  <Shield
                    className={
                      isExpired(policy.end_date)
                        ? 'text-danger mt-1'
                        : 'text-primary mt-1'
                    }
                    size={20}
                  />
                  <div>
                    <h3 className="text-lg font-semibold text-garage-text">{policy.provider}</h3>
                    <p className="text-sm text-garage-text-muted">{policy.policy_type}</p>
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => onEditClick(policy)}
                    className="btn btn-ghost btn-sm"
                    title={t('common:edit')}
                  >
                    <Edit3 size={16} />
                  </button>
                  <button
                    onClick={() => handleDelete(policy.id)}
                    className="btn btn-ghost btn-sm text-danger"
                    disabled={deleteMutation.isPending && deleteMutation.variables === policy.id}
                    title={t('common:delete')}
                  >
                    {deleteMutation.isPending && deleteMutation.variables === policy.id ? '...' : <Trash2 size={16} />}
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                <div>
                  <p className="text-xs text-garage-text-muted mb-1">{t('insuranceList.policyNumber')}</p>
                  <p className="text-sm text-garage-text">{policy.policy_number}</p>
                </div>
                <div>
                  <p className="text-xs text-garage-text-muted mb-1">{t('insuranceList.startDate')}</p>
                  <p className="text-sm text-garage-text">{formatDate(policy.start_date)}</p>
                </div>
                <div>
                  <p className="text-xs text-garage-text-muted mb-1">{t('insuranceList.endDate')}</p>
                  <p className="text-sm text-garage-text">{formatDate(policy.end_date)}</p>
                </div>
                {policy.premium_amount && (
                  <div>
                    <p className="text-xs text-garage-text-muted mb-1">{t('insuranceList.premiumAmount')}</p>
                    <p className="text-sm text-garage-text">
                      {formatCurrency(policy.premium_amount, { currencyCode, locale })}
                      {policy.premium_frequency && ` / ${policy.premium_frequency}`}
                    </p>
                  </div>
                )}
              </div>

              {policy.deductible && (
                <div className="mb-2">
                  <p className="text-xs text-garage-text-muted mb-1">{t('insuranceList.deductible')}</p>
                  <p className="text-sm text-garage-text">{formatCurrency(policy.deductible, { currencyCode, locale })}</p>
                </div>
              )}

              {policy.coverage_limits && (
                <div className="mb-2">
                  <p className="text-xs text-garage-text-muted mb-1">{t('insuranceList.coverageLimits')}</p>
                  <p className="text-sm text-garage-text whitespace-pre-wrap">{policy.coverage_limits}</p>
                </div>
              )}

              {policy.notes && (
                <div>
                  <p className="text-xs text-garage-text-muted mb-1">{t('insuranceList.notes')}</p>
                  <p className="text-sm text-garage-text whitespace-pre-wrap">{policy.notes}</p>
                </div>
              )}

              {isExpired(policy.end_date) && (
                <div className="mt-4 text-sm text-danger flex items-center gap-2">
                  <Calendar size={16} />{t('insuranceList.expired')}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
