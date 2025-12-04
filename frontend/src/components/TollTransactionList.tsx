import { useState, useEffect, useCallback } from 'react'
import { DollarSign, Plus, Edit, Trash2, MapPin, Calendar, Download, CreditCard } from 'lucide-react'
import { toast } from 'sonner'
import type { TollTransaction, TollTag, TollTransactionSummary } from '../types/toll'
import api from '../services/api'

interface TollTransactionListProps {
  vin: string
  tollTags: TollTag[]
  onAddClick: () => void
  onEditClick: (transaction: TollTransaction) => void
  onRefresh?: () => void
}

export default function TollTransactionList({ vin, tollTags, onAddClick, onEditClick, onRefresh }: TollTransactionListProps) {
  const [transactions, setTransactions] = useState<TollTransaction[]>([])
  const [summary, setSummary] = useState<TollTransactionSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<number | null>(null)
  const [exporting, setExporting] = useState(false)
  const [selectedTagFilter, setSelectedTagFilter] = useState<number | ''>('')

  const fetchTransactions = useCallback(async () => {
    try {
      const params = selectedTagFilter ? `?toll_tag_id=${selectedTagFilter}` : ''
      const response = await api.get(`/vehicles/${vin}/toll-transactions${params}`)
      setTransactions(response.data.transactions || [])
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    }
  }, [selectedTagFilter, vin])

  const fetchSummary = useCallback(async () => {
    try {
      const response = await api.get(`/vehicles/${vin}/toll-transactions/summary/statistics`)
      setSummary(response.data)
    } catch {
      // Removed console.error
    }
  }, [vin])

  useEffect(() => {
    setLoading(true)
    fetchTransactions().finally(() => setLoading(false))
    fetchSummary()
  }, [fetchTransactions, fetchSummary])

  useEffect(() => {
    if (onRefresh) {
      fetchTransactions()
      fetchSummary()
    }
  }, [onRefresh, fetchTransactions, fetchSummary])

  const handleDelete = async (transactionId: number) => {
    if (!confirm('Are you sure you want to delete this toll transaction?')) {
      return
    }

    setDeleting(transactionId)
    try {
      await api.delete(`/vehicles/${vin}/toll-transactions/${transactionId}`)
      await fetchTransactions()
      await fetchSummary()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete toll transaction')
    } finally {
      setDeleting(null)
    }
  }

  const handleExportCSV = async () => {
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
      toast.error(err instanceof Error ? err.message : 'Failed to export data')
    } finally {
      setExporting(false)
    }
  }

  const formatDate = (dateString: string): string => {
    const date = new Date(dateString + 'T00:00:00')
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  }

  const formatCurrency = (amount: number): string => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(amount)
  }

  const getTollTagName = (tagId?: number): string => {
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

  if (error) {
    return (
      <div className="bg-danger/10 border border-danger rounded-lg p-4">
        <p className="text-danger">{error}</p>
      </div>
    )
  }

  return (
    <div>
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
        <div>
          <h2 className="text-2xl font-bold text-garage-text">Toll Transactions</h2>
          <p className="text-sm text-garage-text-muted">
            {transactions.length} {transactions.length === 1 ? 'transaction' : 'transactions'} recorded
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <select
            value={selectedTagFilter}
            onChange={(e) => setSelectedTagFilter(e.target.value ? parseInt(e.target.value) : '')}
            className="px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text text-sm"
          >
            <option value="">All Tags</option>
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
            <span>{exporting ? 'Exporting...' : 'Export'}</span>
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
                <p className="text-xs text-garage-text-muted mb-1">Total Transactions</p>
                <p className="text-2xl font-bold text-garage-text">{summary.total_transactions}</p>
              </div>
              <Calendar className="text-primary" size={24} />
            </div>
          </div>
          <div className="bg-garage-surface rounded-lg p-4 border border-garage-border">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-garage-text-muted mb-1">Total Amount</p>
                <p className="text-2xl font-bold text-garage-text">{formatCurrency(summary.total_amount)}</p>
              </div>
              <DollarSign className="text-success" size={24} />
            </div>
          </div>
          <div className="bg-garage-surface rounded-lg p-4 border border-garage-border">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-garage-text-muted mb-1">Average per Transaction</p>
                <p className="text-2xl font-bold text-garage-text">
                  {summary.total_transactions > 0
                    ? formatCurrency(summary.total_amount / summary.total_transactions)
                    : '$0.00'}
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
          <p className="text-garage-text-muted mb-4">No toll transactions recorded yet</p>
          <button onClick={onAddClick} className="inline-flex items-center gap-2 px-4 py-2 bg-gray-700 border border-gray-600 text-white rounded-lg hover:bg-gray-800 transition-colors">
            Add Your First Transaction
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
                      <p className="text-sm text-garage-text-muted">{formatDate(transaction.transaction_date)}</p>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3 ml-9">
                    <div>
                      <p className="text-xs text-garage-text-muted mb-1">Amount</p>
                      <p className="text-sm font-semibold text-garage-text">{formatCurrency(transaction.amount)}</p>
                    </div>
                    <div>
                      <p className="text-xs text-garage-text-muted mb-1">Toll Tag</p>
                      <p className="text-sm text-garage-text">{getTollTagName(transaction.toll_tag_id)}</p>
                    </div>
                    {transaction.notes && (
                      <div className="col-span-2 md:col-span-1">
                        <p className="text-xs text-garage-text-muted mb-1">Notes</p>
                        <p className="text-sm text-garage-text">{transaction.notes}</p>
                      </div>
                    )}
                  </div>
                </div>
                <div className="flex gap-2 ml-9 md:ml-0">
                  <button
                    onClick={() => onEditClick(transaction)}
                    className="btn btn-ghost btn-sm"
                    title="Edit"
                  >
                    <Edit size={16} />
                  </button>
                  <button
                    onClick={() => handleDelete(transaction.id)}
                    className="btn btn-ghost btn-sm text-danger"
                    disabled={deleting === transaction.id}
                    title="Delete"
                  >
                    {deleting === transaction.id ? '...' : <Trash2 size={16} />}
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
          <h3 className="text-lg font-semibold text-garage-text mb-4">Monthly Breakdown</h3>
          <div className="bg-garage-surface rounded-lg border border-garage-border overflow-hidden">
            <table className="w-full">
              <thead className="bg-garage-bg">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">
                    Month
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">
                    Transactions
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">
                    Total
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-garage-border">
                {summary.monthly_totals.map((monthly) => (
                  <tr key={monthly.month} className="hover:bg-garage-bg/50">
                    <td className="px-4 py-3 text-sm text-garage-text">
                      {new Date(monthly.month + '-01').toLocaleDateString('en-US', { year: 'numeric', month: 'long' })}
                    </td>
                    <td className="px-4 py-3 text-sm text-garage-text">{monthly.count}</td>
                    <td className="px-4 py-3 text-sm font-semibold text-garage-text">{formatCurrency(monthly.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
