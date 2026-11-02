import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { Edit, Trash2, Plus, AlertCircle, FileText } from 'lucide-react'
import { toast } from 'sonner'
import { formatDateForDisplay } from '../utils/dateUtils'
import { formatCurrency } from '../utils/formatUtils'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import type { TaxRecord } from '../types/tax'
import { taxTypeLabel } from '../schemas/tax'
import TaxRecordForm from './TaxRecordForm'
import { useTaxRecords, useDeleteTaxRecord } from '../hooks/queries/useTaxRecords'
import { Button, IconButton, Card, Mono, EmptyState, DataTable } from './ui'
import type { DataTableColumn } from './ui'

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
        toast.error(getActionErrorMessage(err, t('taxList.deleteAction')))
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

  const columns: DataTableColumn<TaxRecord>[] = [
    { id: 'datePaid', header: t('taxList.datePaid'), mono: true, render: (r) => formatDateForDisplay(r.date) },
    // #211 — the code's translated label; a pre-146 display string reads as its code.
    { id: 'type', header: t('taxList.type'), render: (r) => taxTypeLabel(r.tax_type, t) || '-' },
    { id: 'amount', header: t('taxList.amount'), mono: true, align: 'right', render: (r) => formatCurrency(r.amount, { currencyCode, locale }) },
    { id: 'renewalDate', header: t('taxList.renewalDate'), mono: true, render: (r) => (r.renewal_date ? formatDateForDisplay(r.renewal_date) : '-') },
    {
      id: 'notes',
      header: t('taxList.notes'),
      render: (r) => (r.notes ? <span className="truncate max-w-xs block" title={r.notes}>{r.notes}</span> : <span className="text-text-mute">-</span>),
    },
    {
      id: 'actions',
      header: t('taxList.actions'),
      align: 'right',
      render: (r) => (
        <div className="flex justify-end gap-2">
          <IconButton icon={Edit} label={t('common:edit')} variant="ghost" size="sm" onClick={() => handleEdit(r)} />
          <IconButton
            icon={Trash2}
            label={t('common:delete')}
            variant="danger"
            size="sm"
            disabled={deleteMutation.isPending && deleteMutation.variables === r.id}
            onClick={() => handleDelete(r.id)}
          />
        </div>
      ),
    },
  ]

  if (isLoading) {
    return (
      <div className="text-center py-8 text-text-mute">{t('taxList.loading')}</div>
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
          <h3 className="text-lg font-semibold text-text">{t('taxList.title')}</h3>
          {records.length > 0 && (
            <p className="text-sm text-text-mute">
              {t('taxList.recordCount', { count: records.length })} • {t('taxList.total')}:{' '}
              <Mono size="sm">{formatCurrency(getTotalAmount(), { currencyCode, locale })}</Mono>
            </p>
          )}
        </div>
        <Button variant="primary" icon={Plus} onClick={handleAdd}>{t('taxList.addRecord')}</Button>
      </div>

      {error && (
        <div className="flex items-start gap-2 p-3 bg-danger/10 border border-danger/20 rounded-md mb-4">
          <AlertCircle aria-hidden="true" className="w-4 h-4 text-danger flex-shrink-0 mt-0.5" />
          <p className="text-sm text-danger">{getActionErrorMessage(error, t('taxList.loadAction'))}</p>
        </div>
      )}

      {records.length === 0 ? (
        <EmptyState
          icon={FileText}
          title={t('taxList.noRecords')}
          description={t('taxList.noRecordsDesc')}
          action={<Button variant="primary" icon={Plus} onClick={handleAdd}>{t('taxList.addFirstRecord')}</Button>}
        />
      ) : (
        <Card padding="none">
          <DataTable
            caption={t('taxList.tableCaption')}
            columns={columns}
            rows={records}
            rowKey={(r) => String(r.id)}
          />
        </Card>
      )}
    </div>
  )
}
