import { Shield, Plus, Trash2, Edit3, Calendar } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import type { WarrantyRecord } from '../types/warranty'
import { useWarrantyRecords, useDeleteWarrantyRecord } from '../hooks/queries/useWarrantyRecords'
import { formatDateForDisplay, formatDateForInput } from '../utils/dateUtils'
import { useDateLocale } from '../hooks/useDateLocale'
import { useUnitFormat } from '../hooks/useUnitFormat'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { Button, IconButton, Mono, EmptyState } from './ui'

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
  const u = useUnitFormat()

  const handleDelete = (warrantyId: number) => {
    if (!confirm(t('warrantyList.confirmDelete'))) {
      return
    }

    deleteMutation.mutate(warrantyId, {
      onError: (err) => {
        toast.error(getActionErrorMessage(err, t('warrantyList.deleteAction')))
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
        <div className="text-text-mute">{t('warrantyList.loading')}</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-danger/10 border border-danger rounded-lg p-4">
        <p className="text-danger">{getActionErrorMessage(error, t('warrantyList.loadAction'))}</p>
      </div>
    )
  }

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-2xl font-bold text-text">{t('warrantyList.title')}</h2>
          <p className="text-sm text-text-mute">{t('warrantyList.warrantyCount', { count: warranties.length })}</p>
        </div>
        <Button variant="primary" icon={Plus} onClick={onAddClick}>{t('warrantyList.addWarranty')}</Button>
      </div>

      {warranties.length === 0 ? (
        <EmptyState
          icon={Shield}
          title={t('warrantyList.noRecords')}
          action={<Button variant="primary" icon={Plus} onClick={onAddClick}>{t('warrantyList.addFirstWarranty')}</Button>}
        />
      ) : (
        <div className="space-y-4">
          {warranties.map((warranty) => (
            <div
              key={warranty.id}
              className={`bg-surface rounded-card p-6 border ${
                warranty.end_date && isExpired(warranty.end_date) ? 'border-danger/30' : 'border-border'
              }`}
            >
              <div className="flex justify-between items-start mb-4">
                <div className="flex items-start gap-3">
                  <Shield
                    aria-hidden="true"
                    size={20}
                    className={warranty.end_date && isExpired(warranty.end_date) ? 'text-danger mt-1' : 'text-(--accent-fg) mt-1'}
                  />
                  <div>
                    <h3 className="text-lg font-semibold text-text">{warranty.warranty_type}</h3>
                    {warranty.provider && <p className="text-sm text-text-mute">{warranty.provider}</p>}
                  </div>
                </div>
                <div className="flex gap-2">
                  <IconButton icon={Edit3} label={t('common:edit')} variant="ghost" size="sm" onClick={() => onEditClick(warranty)} />
                  <IconButton
                    icon={Trash2}
                    label={t('common:delete')}
                    variant="danger"
                    size="sm"
                    disabled={deleteMutation.isPending && deleteMutation.variables === warranty.id}
                    onClick={() => handleDelete(warranty.id)}
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                <div>
                  <p className="text-xs text-text-mute mb-1">{t('warrantyList.startDate')}</p>
                  <Mono size="sm" className="text-text">{formatDate(warranty.start_date)}</Mono>
                </div>
                <div>
                  <p className="text-xs text-text-mute mb-1">{t('warrantyList.endDate')}</p>
                  <Mono size="sm" className="text-text">{warranty.end_date ? formatDate(warranty.end_date) : 'N/A'}</Mono>
                </div>
                {warranty.mileage_limit_km && (
                  <div>
                    <p className="text-xs text-text-mute mb-1">{t('warrantyList.mileageLimit')}</p>
                    <Mono size="sm" className="text-text">{u.distance.format(parseFloat(String(warranty.mileage_limit_km)))}</Mono>
                  </div>
                )}
                {warranty.policy_number && (
                  <div>
                    <p className="text-xs text-text-mute mb-1">{t('warrantyList.policyNumber')}</p>
                    <Mono size="sm" tabular={false} className="text-text">{warranty.policy_number}</Mono>
                  </div>
                )}
              </div>

              {warranty.coverage_details && (
                <div className="mb-2">
                  <p className="text-xs text-text-mute mb-1">{t('warrantyList.coverageDetails')}</p>
                  <p className="text-sm text-text whitespace-pre-wrap">{warranty.coverage_details}</p>
                </div>
              )}

              {warranty.notes && (
                <div>
                  <p className="text-xs text-text-mute mb-1">{t('warrantyList.notes')}</p>
                  <p className="text-sm text-text whitespace-pre-wrap">{warranty.notes}</p>
                </div>
              )}

              {warranty.end_date && isExpired(warranty.end_date) && (
                <div className="mt-4 text-sm text-danger flex items-center gap-2">
                  <Calendar aria-hidden="true" size={16} />{t('warrantyList.expired')}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
