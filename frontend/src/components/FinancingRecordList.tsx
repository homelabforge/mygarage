import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { Edit, Trash2, Plus, AlertCircle, Landmark } from 'lucide-react'
import { toast } from 'sonner'
import { formatDateForDisplay } from '../utils/dateUtils'
import { formatCurrency } from '../utils/formatUtils'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import type { FinancingRecord } from '../types/financing'
import { FINANCING_CATEGORIES } from '../schemas/financing'
import FinancingRecordForm from './FinancingRecordForm'
import { useFinancingRecords, useDeleteFinancingRecord } from '../hooks/queries/useFinancingRecords'
import { Button, IconButton, Card, Mono, EmptyState, DataTable, useConfirm } from './ui'
import type { DataTableColumn } from './ui'

interface FinancingRecordListProps {
  vin: string
}

const CATEGORY_LABEL_KEYS: Record<string, string> = Object.fromEntries(
  FINANCING_CATEGORIES.map((c) => [c.value, c.labelKey])
)

export default function FinancingRecordList({ vin }: FinancingRecordListProps) {
  const queryClient = useQueryClient()
  const { currencyCode, locale } = useCurrencyPreference()
  const { data, isLoading, error } = useFinancingRecords(vin)
  const deleteMutation = useDeleteFinancingRecord(vin)
  const { t } = useTranslation('vehicles')
  const confirm = useConfirm()
  const [showForm, setShowForm] = useState(false)
  const [editingRecord, setEditingRecord] = useState<FinancingRecord | undefined>()

  const records = data?.financing_records ?? []

  const handleAdd = () => {
    setEditingRecord(undefined)
    setShowForm(true)
  }

  const handleEdit = (record: FinancingRecord) => {
    setEditingRecord(record)
    setShowForm(true)
  }

  const handleDelete = async (id: number): Promise<void> => {
    if (!(await confirm({ message: t('financingList.confirmDelete'), confirmLabel: t('common:delete') }))) {
      return
    }

    deleteMutation.mutate(id, {
      onError: (err) => {
        toast.error(getActionErrorMessage(err, t('financingList.deleteAction')))
      },
    })
  }

  const handleSuccess = () => {
    queryClient.invalidateQueries({ queryKey: ['financingRecords', vin] })
    setShowForm(false)
  }

  const getTotalAmount = (): number => {
    return records.reduce((sum, record) => sum + parseFloat(String(record.amount)), 0)
  }

  const columns: DataTableColumn<FinancingRecord>[] = [
    { id: 'date', header: t('financingList.date'), mono: true, render: (r) => formatDateForDisplay(r.date) },
    {
      id: 'category',
      header: t('financingList.category'),
      render: (r) => (CATEGORY_LABEL_KEYS[r.category] ? t(CATEGORY_LABEL_KEYS[r.category]) : r.category),
    },
    { id: 'amount', header: t('financingList.amount'), mono: true, align: 'right', render: (r) => formatCurrency(r.amount, { currencyCode, locale }) },
    {
      id: 'lender',
      header: t('financingList.lender'),
      render: (r) => (r.lender ? r.lender.name : <span className="text-text-mute">-</span>),
    },
    {
      id: 'notes',
      header: t('financingList.notes'),
      render: (r) => (r.notes ? <span className="truncate max-w-xs block" title={r.notes}>{r.notes}</span> : <span className="text-text-mute">-</span>),
    },
    {
      id: 'actions',
      header: t('financingList.actions'),
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
            onClick={() => void handleDelete(r.id)}
          />
        </div>
      ),
    },
  ]

  if (isLoading) {
    return (
      <div className="text-center py-8 text-text-mute">{t('financingList.loading')}</div>
    )
  }

  return (
    <div>
      {showForm && (
        <FinancingRecordForm
          vin={vin}
          record={editingRecord}
          onClose={() => setShowForm(false)}
          onSuccess={handleSuccess}
        />
      )}

      <div className="flex flex-wrap justify-between items-center gap-3 mb-4">
        <div>
          <h3 className="text-lg font-semibold text-text">{t('financingList.title')}</h3>
          {records.length > 0 && (
            <p className="text-sm text-text-mute">
              {t('financingList.recordCount', { count: records.length })} • {t('financingList.total')}:{' '}
              <Mono size="sm">{formatCurrency(getTotalAmount(), { currencyCode, locale })}</Mono>
            </p>
          )}
        </div>
        <Button variant="primary" icon={Plus} onClick={handleAdd}>{t('financingList.addRecord')}</Button>
      </div>

      {error && (
        <div className="flex items-start gap-2 p-3 bg-danger/10 border border-danger/20 rounded-md mb-4">
          <AlertCircle aria-hidden="true" className="w-4 h-4 text-danger flex-shrink-0 mt-0.5" />
          <p className="text-sm text-danger">{getActionErrorMessage(error, t('financingList.loadAction'))}</p>
        </div>
      )}

      {records.length === 0 ? (
        <EmptyState
          icon={Landmark}
          title={t('financingList.noRecords')}
          description={t('financingList.noRecordsDesc')}
          action={<Button variant="primary" icon={Plus} onClick={handleAdd}>{t('financingList.addFirstRecord')}</Button>}
        />
      ) : (
        <Card padding="none">
          <DataTable
            caption={t('financingList.tableCaption')}
            columns={columns}
            rows={records}
            rowKey={(r) => String(r.id)}
          />
        </Card>
      )}
    </div>
  )
}
