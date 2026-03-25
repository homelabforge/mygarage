import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { Edit, Trash2, Plus, AlertCircle } from 'lucide-react'
import { toast } from 'sonner'
import { formatDateForDisplay } from '../utils/dateUtils'
import { formatCurrency } from '../utils/formatUtils'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'
import type { TaxRecord } from '../types/tax'
import TaxRecordForm from './TaxRecordForm'
import { useTaxRecords, useDeleteTaxRecord } from '../hooks/queries/useTaxRecords'

interface TaxRecordListProps {
  vin: string
}

export default function TaxRecordList({ vin }: TaxRecordListProps) {
  const queryClient = useQueryClient()
  const { currencyCode, locale } = useCurrencyPreference()
  const { data, isLoading, error } = useTaxRecords(vin)
  const deleteMutation = useDeleteTaxRecord(vin)
  const { t } = useTranslation('vehicles')
  const [showForm, setShowForm] = useState(false)
  const [editingRecord, setEditingRecord] = useState<TaxRecord | undefined>()

  const records = data?.records ?? []

  const handleAdd = () => {
    setEditingRecord(undefined)
    setShowForm(true)
  }

  const handleEdit = (record: TaxRecord) => {
    setEditingRecord(record)
    setShowForm(true)
  }

  const handleDelete = (id: number) => {
    if (!confirm(t('taxList.confirmDelete'))) {
      return
    }

    deleteMutation.mutate(id, {
      onError: (err) => {
        toast.error(err instanceof Error ? err.message : t('taxList.deleteError'))
      },
    })
  }

  const handleSuccess = () => {
    queryClient.invalidateQueries({ queryKey: ['taxRecords', vin] })
    setShowForm(false)
  }

  const getTotalAmount = (): number => {
    return records.reduce((sum, record) => sum + parseFloat(String(record.amount)), 0)
  }

  if (isLoading) {
    return (
      <div className="text-center py-8 text-garage-text-muted">{t('taxList.loading')}</div>
    )
  }

  return (
    <div>
      {showForm && (
        <TaxRecordForm
          vin={vin}
          record={editingRecord}
          onClose={() => setShowForm(false)}
          onSuccess={handleSuccess}
        />
      )}

      <div className="flex justify-between items-center mb-4">
        <div>
          <h3 className="text-lg font-semibold text-garage-text">{t('taxList.title')}</h3>
          {records.length > 0 && (
            <p className="text-sm text-garage-text-muted">
              {t('taxList.recordCount', { count: records.length })} • {t('taxList.total')}: {formatCurrency(getTotalAmount(), { currencyCode, locale })}
            </p>
          )}
        </div>
        <button
          onClick={handleAdd}
          className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
        >
          <Plus className="w-4 h-4" />
          <span>{t('taxList.addRecord')}</span>
        </button>
      </div>

      {error && (
        <div className="flex items-start gap-2 p-3 bg-danger/10 border border-danger/20 rounded-md mb-4">
          <AlertCircle className="w-4 h-4 text-danger flex-shrink-0 mt-0.5" />
          <p className="text-sm text-danger">{error.message}</p>
        </div>
      )}

      {records.length === 0 ? (
        <div className="text-center py-12 bg-garage-surface border border-garage-border rounded-lg">
          <p className="text-garage-text mb-2">{t('taxList.noRecords')}</p>
          <p className="text-sm text-garage-text-muted mb-4">{t('taxList.noRecordsDesc')}</p>
          <button
            onClick={handleAdd}
            className="inline-flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>{t('taxList.addFirstRecord')}</span>
          </button>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-garage-border">
                <th className="px-4 py-3 text-left text-sm font-semibold text-garage-text">{t('taxList.datePaid')}</th>
                <th className="px-4 py-3 text-left text-sm font-semibold text-garage-text">{t('taxList.type')}</th>
                <th className="px-4 py-3 text-right text-sm font-semibold text-garage-text">{t('taxList.amount')}</th>
                <th className="px-4 py-3 text-left text-sm font-semibold text-garage-text">{t('taxList.renewalDate')}</th>
                <th className="px-4 py-3 text-left text-sm font-semibold text-garage-text">{t('taxList.notes')}</th>
                <th className="px-4 py-3 text-right text-sm font-semibold text-garage-text">{t('taxList.actions')}</th>
              </tr>
            </thead>
            <tbody>
              {records.map((record) => (
                <tr
                  key={record.id}
                  className="border-b border-garage-border hover:bg-garage-bg/50 transition-colors"
                >
                  <td className="px-4 py-3 text-sm text-garage-text">
                    {formatDateForDisplay(record.date)}
                  </td>
                  <td className="px-4 py-3 text-sm text-garage-text">
                    {record.tax_type || '-'}
                  </td>
                  <td className="px-4 py-3 text-sm text-garage-text text-right font-medium">
                    {formatCurrency(record.amount, { currencyCode, locale })}
                  </td>
                  <td className="px-4 py-3 text-sm text-garage-text">
                    {record.renewal_date ? formatDateForDisplay(record.renewal_date) : '-'}
                  </td>
                  <td className="px-4 py-3 text-sm text-garage-text-muted">
                    {record.notes ? (
                      <span className="truncate max-w-xs block" title={record.notes}>
                        {record.notes}
                      </span>
                    ) : (
                      '-'
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-right">
                    <div className="flex justify-end gap-2">
                      <button
                        onClick={() => handleEdit(record)}
                        className="p-2 text-primary hover:bg-primary/10 rounded transition-colors"
                        aria-label={t('common:edit')}
                        title={t('common:edit')}
                      >
                        <Edit className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleDelete(record.id)}
                        disabled={deleteMutation.isPending && deleteMutation.variables === record.id}
                        className="p-2 text-danger hover:bg-danger/10 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        aria-label={t('common:delete')}
                        title={t('common:delete')}
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
