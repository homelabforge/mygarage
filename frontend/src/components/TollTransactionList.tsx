import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { DollarSign, Plus, Edit, Trash2, MapPin, Calendar, Download, CreditCard } from 'lucide-react'
import { toast } from 'sonner'
import type { TollTransaction } from '../types/toll'
import { formatCurrency } from '../utils/formatUtils'
import { formatDateForDisplay } from '../utils/dateUtils'
import { useDateLocale } from '../hooks/useDateLocale'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'
import { useTollTransactions, useTollTags, useTollTransactionSummary, useDeleteTollTransaction } from '../hooks/queries/useTollRecords'
import api from '../services/api'

interface TollTransactionListProps {
  vin: string
  onAddClick: () => void
  onEditClick: (transaction: TollTransaction) => void
}

export default function TollTransactionList({ vin, onAddClick, onEditClick }: TollTransactionListProps) {
  const { t } = useTranslation('vehicles')
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
    if (!confirm(t('tollList.confirmDelete'))) {
      return
    }

    deleteMutation.mutate(transactionId, {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: ['tollTransactions', vin] })
        queryClient.invalidateQueries({ queryKey: ['tollTransactionSummary', vin] })
      },
      onError: (err) => {
        toast.error(err instanceof Error ? err.message : t('tollList.deleteError'))
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
      toast.error(err instanceof Error ? err.message : t('tollList.exportError'))
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
    if (!tagId) return 'N/A'
    const tag = tollTags.find(t => t.id === tagId)
    return tag ? `${tag.toll_system} (${tag.tag_number})` : 'Unknown Tag'
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">Loading toll transactions...</div>
      </div>
    )
  }

  if (transactionsError) {
    return (
      <div className="bg-danger/10 border border-danger rounded-lg p-4">
        <p className="text-danger">{transactionsError instanceof Error ? transactionsError.message : t('tollList.error')}</p>
      </div>
    )
  }

  return (
    <div>
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
        <div>
          <h2 className="text-2xl font-bold text-garage-text">{t('tollList.title')}</h2>
          <p className="text-sm text-garage-text-muted">
            {t('tollList.transactionCount', { count: transactions.length })}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <select
            value={selectedTagFilter}
            onChange={(e) => setSelectedTagFilter(e.target.value ? parseInt(e.target.value) : '')}
            className="px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text text-sm"
          >
            <option value="">{t('tollList.allTags')}</option>
            {tollTags.filter(t => t.status === 'active').map((tag) => (
              <option key={tag.id} value={tag.id}>{tag.toll_system} - {tag.tag_number}</option>
            ))}
          </select>
          <button
            onClick={handleExportCSV}
            disabled={exporting || transactions.length === 0}
            className="flex items-center gap-2 px-4 py-2 bg-gray-700 border border-gray-600 text-white rounded-lg hover:bg-gray-800 transition-colors disabled:opacity-50"
            title="Export to CSV"
          >
            <Download className="w-4 h-4" />
            <span>{exporting ? t('tollList.exporting') : t('tollList.export')}</span>
          </button>
          <button
            onClick={onAddClick}
            className="flex items-center gap-2 px-4 py-2 bg-gray-700 border border-gray-600 text-white rounded-lg hover:bg-gray-800 transition-colors"
          >
            <Plus size={20} />
            Add Transaction
          </button>
        </div>
      </div>

      {/* Summary Cards */}
      {summary && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          <div className="bg-garage-surface rounded-lg p-4 border border-garage-border">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-garage-text-muted mb-1">{t('tollList.totalTransactions')}</p>
                <p className="text-2xl font-bold text-garage-text">{summary.total_transactions}</p>
              </div>
              <Calendar className="text-primary" size={24} />
            </div>
          </div>
          <div className="bg-garage-surface rounded-lg p-4 border border-garage-border">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-garage-text-muted mb-1">{t('tollList.totalAmount')}</p>
                <p className="text-2xl font-bold text-garage-text">{formatCurrency(Number(summary.total_amount), { currencyCode, locale })}</p>
              </div>
              <DollarSign className="text-success" size={24} />
            </div>
          </div>
          <div className="bg-garage-surface rounded-lg p-4 border border-garage-border">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-garage-text-muted mb-1">{t('tollList.averagePerTransaction')}</p>
                <p className="text-2xl font-bold text-garage-text">
                  {summary.total_transactions > 0
                    ? formatCurrency(Number(summary.total_amount) / summary.total_transactions, { currencyCode, locale })
                    : formatCurrency(0, { currencyCode, locale, zeroIsValid: true })}
                </p>
              </div>
              <CreditCard className="text-primary" size={24} />
            </div>
          </div>
        </div>
      )}

      {transactions.length === 0 ? (
        <div className="text-center py-12 bg-garage-surface rounded-lg border border-garage-border">
          <DollarSign size={48} className="mx-auto text-garage-text-muted mb-4" />
          <p className="text-garage-text-muted mb-4">{t('tollList.noRecords')}</p>
          <button onClick={onAddClick} className="inline-flex items-center gap-2 px-4 py-2 bg-gray-700 border border-gray-600 text-white rounded-lg hover:bg-gray-800 transition-colors">
            {t('tollList.addFirstTransaction')}
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {transactions.map((transaction) => (
            <div
              key={transaction.id}
              className="bg-garage-surface rounded-lg p-4 border border-garage-border hover:border-primary/50 transition-colors"
            >
              <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
                <div className="flex-1">
                  <div className="flex items-start gap-3 mb-2">
                    <MapPin className="text-primary mt-1" size={18} />
                    <div className="flex-1">
                      <h3 className="text-lg font-semibold text-garage-text">{transaction.location}</h3>
                      <p className="text-sm text-garage-text-muted">{formatDate(transaction.date)}</p>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3 ml-9">
                    <div>
                      <p className="text-xs text-garage-text-muted mb-1">{t('tollList.amount')}</p>
                      <p className="text-sm font-semibold text-garage-text">{formatCurrency(transaction.amount, { currencyCode, locale })}</p>
                    </div>
                    <div>
                      <p className="text-xs text-garage-text-muted mb-1">{t('tollList.tollTag')}</p>
                      <p className="text-sm text-garage-text">{getTollTagName(transaction.toll_tag_id)}</p>
                    </div>
                    {transaction.notes && (
                      <div className="col-span-2 md:col-span-1">
                        <p className="text-xs text-garage-text-muted mb-1">{t('tollList.notes')}</p>
                        <p className="text-sm text-garage-text">{transaction.notes}</p>
                      </div>
                    )}
                  </div>
                </div>
                <div className="flex gap-2 ml-9 md:ml-0">
                  <button
                    onClick={() => onEditClick(transaction)}
                    className="btn btn-ghost btn-sm"
                    title={t('common:edit')}
                  >
                    <Edit size={16} />
                  </button>
                  <button
                    onClick={() => handleDelete(transaction.id)}
                    className="btn btn-ghost btn-sm text-danger"
                    disabled={deleteMutation.isPending && deleteMutation.variables === transaction.id}
                    title={t('common:delete')}
                  >
                    {deleteMutation.isPending && deleteMutation.variables === transaction.id ? '...' : <Trash2 size={16} />}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Monthly Breakdown */}
      {summary && summary.monthly_totals.length > 0 && (
        <div className="mt-8">
          <h3 className="text-lg font-semibold text-garage-text mb-4">{t('tollList.monthlyBreakdown')}</h3>
          <div className="bg-garage-surface rounded-lg border border-garage-border overflow-hidden">
            <table className="w-full">
              <thead className="bg-garage-bg">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">{t('tollList.month')}</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">{t('tollList.transactions')}</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">{t('tollList.total')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-garage-border">
                {summary.monthly_totals.map((monthly) => {
                  const m = monthly as { month: string; count: number; amount: number }
                  return (
                  <tr key={m.month} className="hover:bg-garage-bg/50">
                    <td className="px-4 py-3 text-sm text-garage-text">
                      {formatDateForDisplay(m.month + '-01', { year: 'numeric', month: 'long' }, dateLocale)}
                    </td>
                    <td className="px-4 py-3 text-sm text-garage-text">{m.count}</td>
                    <td className="px-4 py-3 text-sm font-semibold text-garage-text">{formatCurrency(m.amount, { currencyCode, locale })}</td>
                  </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
