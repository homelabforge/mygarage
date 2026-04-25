import { Shield, Plus, Trash2, Edit3, Calendar } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import type { WarrantyRecord } from '../types/warranty'
import { useWarrantyRecords, useDeleteWarrantyRecord } from '../hooks/queries/useWarrantyRecords'
import { formatDateForDisplay, formatDateForInput } from '../utils/dateUtils'
import { useDateLocale } from '../hooks/useDateLocale'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitFormatter } from '../utils/units'

interface WarrantyListProps {
  vin: string
  onAddClick: () => void
  onEditClick: (warranty: WarrantyRecord) => void
}

export default function WarrantyList({ vin, onAddClick, onEditClick }: WarrantyListProps) {
  const { t } = useTranslation('vehicles')
  const { data: warranties = [], isLoading, error } = useWarrantyRecords(vin)
  const deleteMutation = useDeleteWarrantyRecord(vin)
  const dateLocale = useDateLocale()
  const { system, showBoth } = useUnitPreference()

  const handleDelete = (warrantyId: number) => {
    if (!confirm(t('warrantyList.confirmDelete'))) {
      return
    }

    deleteMutation.mutate(warrantyId, {
      onError: (err) => {
        toast.error(err instanceof Error ? err.message : t('warrantyList.deleteError'))
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

  const isExpired = (endDate: string | null): boolean => {
    if (!endDate) return false
    // end_date is a backend `date` (YYYY-MM-DD). Lexicographic compare against
    // today's local YYYY-MM-DD avoids UTC-midnight drift for users west of UTC.
    return endDate < formatDateForInput()
  }

  if (isLoading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">{t('warrantyList.loading')}</div>
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
          <h2 className="text-2xl font-bold text-garage-text">{t('warrantyList.title')}</h2>
          <p className="text-sm text-garage-text-muted">
            {t('warrantyList.warrantyCount', { count: warranties.length })}
          </p>
        </div>
        <button
          onClick={onAddClick}
          className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
        >
          <Plus size={20} />
          {t('warrantyList.addWarranty')}
        </button>
      </div>

      {warranties.length === 0 ? (
        <div className="text-center py-12 bg-garage-surface rounded-lg">
          <Shield size={48} className="mx-auto text-garage-text-muted mb-4" />
          <p className="text-garage-text-muted mb-4">{t('warrantyList.noRecords')}</p>
          <button onClick={onAddClick} className="inline-flex items-center gap-2 btn btn-primary rounded-lg transition-colors">
            {t('warrantyList.addFirstWarranty')}
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          {warranties.map((warranty) => (
            <div
              key={warranty.id}
              className={`bg-garage-surface rounded-lg p-6 border ${
                warranty.end_date && isExpired(warranty.end_date)
                  ? 'border-danger/30'
                  : 'border-garage-border'
              }`}
            >
              <div className="flex justify-between items-start mb-4">
                <div className="flex items-start gap-3">
                  <Shield
                    className={
                      warranty.end_date && isExpired(warranty.end_date)
                        ? 'text-danger mt-1'
                        : 'text-primary mt-1'
                    }
                    size={20}
                  />
                  <div>
                    <h3 className="text-lg font-semibold text-garage-text">{warranty.warranty_type}</h3>
                    {warranty.provider && (
                      <p className="text-sm text-garage-text-muted">{warranty.provider}</p>
                    )}
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => onEditClick(warranty)}
                    className="btn btn-ghost btn-sm"
                    title={t('common:edit')}
                  >
                    <Edit3 size={16} />
                  </button>
                  <button
                    onClick={() => handleDelete(warranty.id)}
                    className="btn btn-ghost btn-sm text-danger"
                    disabled={deleteMutation.isPending && deleteMutation.variables === warranty.id}
                    title={t('common:delete')}
                  >
                    {deleteMutation.isPending && deleteMutation.variables === warranty.id ? '...' : <Trash2 size={16} />}
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                <div>
                  <p className="text-xs text-garage-text-muted mb-1">{t('warrantyList.startDate')}</p>
                  <p className="text-sm text-garage-text">{formatDate(warranty.start_date)}</p>
                </div>
                <div>
                  <p className="text-xs text-garage-text-muted mb-1">{t('warrantyList.endDate')}</p>
                  <p className="text-sm text-garage-text">
                    {warranty.end_date ? formatDate(warranty.end_date) : 'N/A'}
                  </p>
                </div>
                {warranty.mileage_limit_km && (
                  <div>
                    <p className="text-xs text-garage-text-muted mb-1">{t('warrantyList.mileageLimit')}</p>
                    <p className="text-sm text-garage-text">{UnitFormatter.formatDistance(parseFloat(String(warranty.mileage_limit_km)), system, showBoth)}</p>
                  </div>
                )}
                {warranty.policy_number && (
                  <div>
                    <p className="text-xs text-garage-text-muted mb-1">{t('warrantyList.policyNumber')}</p>
                    <p className="text-sm text-garage-text">{warranty.policy_number}</p>
                  </div>
                )}
              </div>

              {warranty.coverage_details && (
                <div className="mb-2">
                  <p className="text-xs text-garage-text-muted mb-1">{t('warrantyList.coverageDetails')}</p>
                  <p className="text-sm text-garage-text whitespace-pre-wrap">{warranty.coverage_details}</p>
                </div>
              )}

              {warranty.notes && (
                <div>
                  <p className="text-xs text-garage-text-muted mb-1">{t('warrantyList.notes')}</p>
                  <p className="text-sm text-garage-text whitespace-pre-wrap">{warranty.notes}</p>
                </div>
              )}

              {warranty.end_date && isExpired(warranty.end_date) && (
                <div className="mt-4 text-sm text-danger flex items-center gap-2">
                  <Calendar size={16} />{t('warrantyList.expired')}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
