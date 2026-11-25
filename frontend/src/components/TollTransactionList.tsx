import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { DollarSign, Plus, Edit, Trash2, MapPin, Calendar, Download, CreditCard } from 'lucide-react'
import { toast } from 'sonner'
import type { TollTransaction, MonthlyTotal } from '../types/toll'
import { formatCurrency } from '../utils/formatUtils'
import { formatDateForDisplay } from '../utils/dateUtils'
import { useDateLocale } from '../hooks/useDateLocale'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'
import { useTollTransactions, useTollTags, useTollTransactionSummary, useDeleteTollTransaction } from '../hooks/queries/useTollRecords'
import api from '../services/api'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { Button, IconButton, Card, Mono, EmptyState, DataTable, Select, useConfirm } from './ui'
import type { DataTableColumn } from './ui'

interface TollTransactionListProps {
  vin: string
  onAddClick: () => void
  onEditClick: (transaction: TollTransaction) => void
}

export default function TollTransactionList({ vin, onAddClick, onEditClick }: TollTransactionListProps) {
  const { t } = useTranslation('vehicles')
  const confirm = useConfirm()
  const queryClient = useQueryClient()
  const dateLocale = useDateLocale()
  const { currencyCode, locale } = useCurrencyPreference()
  const [exporting, setExporting] = useState(false)
  const [selectedTagFilter, setSelectedTagFilter] = useState<number | ''>('')

  const { data: transactionsData, isLoading: loadingTransactions, error: transactionsError } = useTollTransactions(vin)
  const { data: tagsData, isLoading: loadingTags } = useTollTags(vin)
  const { data: summary } = useTollTransactionSummary(vin)
  const deleteMutation = useDeleteTollTransaction(vin)

  const tollTags = tagsData?.toll_tags ?? []

  const transactions = useMemo(() => {
    const all = transactionsData?.transactions ?? []
    if (!selectedTagFilter) return all
    return all.filter(t => t.toll_tag_id === selectedTagFilter)
  }, [transactionsData, selectedTagFilter])

  const loading = loadingTransactions || loadingTags

  const handleDelete = async (transactionId: number): Promise<void> => {
    if (!(await confirm({ message: t('tollList.confirmDelete'), confirmLabel: t('common:delete') }))) {
      return
    }

    deleteMutation.mutate(transactionId, {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: ['tollTransactions', vin] })
        queryClient.invalidateQueries({ queryKey: ['tollTransactionSummary', vin] })
      },
      onError: (err) => {
        toast.error(getActionErrorMessage(err, t('tollList.deleteAction')))
      },
    })
  }

  const handleExportCSV = async (): Promise<void> => {
    setExporting(true)
    try {
      const response = await api.get(`/vehicles/${vin}/toll-transactions/export/csv`, {
        responseType: 'blob'
      })

      const contentDisposition = response.headers['content-disposition']
      const filenameMatch = contentDisposition?.match(/filename="(.+)"/)
      const filename = filenameMatch ? filenameMatch[1] : 'toll_transactions.csv'

      const blob = response.data
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
    } catch (err) {
      toast.error(getActionErrorMessage(err, t('tollList.exportAction')))
    } finally {
      setExporting(false)
    }
  }

  const formatDate = (dateString: string): string => {
    return formatDateForDisplay(dateString, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    }, dateLocale)
  }

  const getTollTagName = (tagId?: number | null): string => {
    if (!tagId) return t('tollTransactionList.noTag')
    const tag = tollTags.find(tollTag => tollTag.id === tagId)
    return tag ? `${tag.toll_system} (${tag.tag_number})` : t('tollTransactionList.unknownTag')
  }

  const monthlyColumns: DataTableColumn<MonthlyTotal>[] = [
    { id: 'month', header: t('tollList.month'), mono: true, render: (m) => formatDateForDisplay(m.month + '-01', { year: 'numeric', month: 'long' }, dateLocale) },
    { id: 'count', header: t('tollList.transactions'), mono: true, align: 'right', render: (m) => m.count },
    { id: 'total', header: t('tollList.total'), mono: true, align: 'right', render: (m) => formatCurrency(m.amount, { currencyCode, locale }) },
  ]

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-text-mute">{t('tollTransactionList.loading')}</div>
      </div>
    )
  }

  if (transactionsError) {
    return (
      <div className="bg-danger/10 border border-danger rounded-lg p-4">
        <p className="text-danger">{getActionErrorMessage(transactionsError, t('tollList.loadAction'))}</p>
      </div>
    )
  }

  return (
    <div>
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
        <div>
          <h2 className="text-2xl font-bold text-text">{t('tollList.title')}</h2>
          <p className="text-sm text-text-mute">{t('tollList.transactionCount', { count: transactions.length })}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Select
            value={selectedTagFilter}
            onChange={(e) => setSelectedTagFilter(e.target.value ? parseInt(e.target.value) : '')}
            placeholder={t('tollList.allTags')}
            options={tollTags.filter(tag => tag.status === 'active').map((tag) => ({ value: String(tag.id), label: `${tag.toll_system} - ${tag.tag_number}` }))}
          />
          <Button variant="secondary" icon={Download} onClick={handleExportCSV} loading={exporting} disabled={transactions.length === 0} title={t('tollTransactionList.exportToCSV')}>
            {exporting ? t('tollList.exporting') : t('tollList.export')}
          </Button>
          <Button variant="primary" icon={Plus} onClick={onAddClick}>{t('tollTransactionList.addTransaction')}</Button>
        </div>
      </div>

      {/* Summary Cards */}
      {summary && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          <Card padding="sm">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-text-mute mb-1">{t('tollList.totalTransactions')}</p>
                <Mono size="2xl" weight="bold">{summary.total_transactions}</Mono>
              </div>
              <Calendar aria-hidden="true" className="text-(--accent-fg)" size={24} />
            </div>
          </Card>
          <Card padding="sm">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-text-mute mb-1">{t('tollList.totalAmount')}</p>
                <Mono size="2xl" weight="bold">{formatCurrency(Number(summary.total_amount), { currencyCode, locale })}</Mono>
              </div>
              <DollarSign aria-hidden="true" className="text-success" size={24} />
            </div>
          </Card>
          <Card padding="sm">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-text-mute mb-1">{t('tollList.averagePerTransaction')}</p>
                <Mono size="2xl" weight="bold">
                  {summary.total_transactions > 0
                    ? formatCurrency(Number(summary.total_amount) / summary.total_transactions, { currencyCode, locale })
                    : formatCurrency(0, { currencyCode, locale, zeroIsValid: true })}
                </Mono>
              </div>
              <CreditCard aria-hidden="true" className="text-(--accent-fg)" size={24} />
            </div>
          </Card>
        </div>
      )}

      {transactions.length === 0 ? (
        <EmptyState
          icon={DollarSign}
          title={t('tollList.noRecords')}
          action={<Button variant="primary" icon={Plus} onClick={onAddClick}>{t('tollList.addFirstTransaction')}</Button>}
        />
      ) : (
        <div className="space-y-3">
          {transactions.map((transaction) => (
            <div
              key={transaction.id}
              className="bg-surface rounded-card p-4 border border-border hover:border-(--accent-line) ui-motion"
            >
              <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
                <div className="flex-1">
                  <div className="flex items-start gap-3 mb-2">
                    <MapPin aria-hidden="true" className="text-(--accent-fg) mt-1" size={18} />
                    <div className="flex-1">
                      <h3 className="text-lg font-semibold text-text">{transaction.location}</h3>
                      <Mono size="sm" className="text-text-mute">{formatDate(transaction.date)}</Mono>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3 ml-9">
                    <div>
                      <p className="text-xs text-text-mute mb-1">{t('tollList.amount')}</p>
                      <Mono size="sm">{formatCurrency(transaction.amount, { currencyCode, locale })}</Mono>
                    </div>
                    <div>
                      <p className="text-xs text-text-mute mb-1">{t('tollList.tollTag')}</p>
                      <p className="text-sm text-text">{getTollTagName(transaction.toll_tag_id)}</p>
                    </div>
                    {transaction.notes && (
                      <div className="col-span-2 md:col-span-1">
                        <p className="text-xs text-text-mute mb-1">{t('tollList.notes')}</p>
                        <p className="text-sm text-text">{transaction.notes}</p>
                      </div>
                    )}
                  </div>
                </div>
                <div className="flex gap-2 ml-9 md:ml-0">
                  <IconButton icon={Edit} label={t('common:edit')} variant="ghost" size="sm" onClick={() => onEditClick(transaction)} />
                  <IconButton
                    icon={Trash2}
                    label={t('common:delete')}
                    variant="danger"
                    size="sm"
                    disabled={deleteMutation.isPending && deleteMutation.variables === transaction.id}
                    onClick={() => void handleDelete(transaction.id)}
                  />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Monthly Breakdown — DataTable, OUTSIDE the transaction card list (LD2) */}
      {summary && summary.monthly_totals.length > 0 && (
        <div className="mt-8">
          <h3 className="text-lg font-semibold text-text mb-4">{t('tollList.monthlyBreakdown')}</h3>
          <Card padding="none">
            <DataTable
              caption={t('tollList.monthlyBreakdownCaption')}
              columns={monthlyColumns}
              rows={summary.monthly_totals as unknown as MonthlyTotal[]}
              rowKey={(m) => m.month}
            />
          </Card>
        </div>
      )}
    </div>
  )
}
