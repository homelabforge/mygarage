import { useState, useEffect, useCallback } from 'react'
import { Edit, Trash2, Plus, AlertCircle } from 'lucide-react'
import { toast } from 'sonner'
import { formatDateForDisplay } from '../utils/dateUtils'
import type { TaxRecord, TaxRecordListResponse } from '../types/tax'
import TaxRecordForm from './TaxRecordForm'
import api from '../services/api'

interface TaxRecordListProps {
  vin: string
}

export default function TaxRecordList({ vin }: TaxRecordListProps) {
  const [records, setRecords] = useState<TaxRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [editingRecord, setEditingRecord] = useState<TaxRecord | undefined>()
  const [deletingId, setDeletingId] = useState<number | null>(null)

  const fetchRecords = useCallback(async () => {
    try {
      const response = await api.get(`/vehicles/${vin}/tax-records`)
      const data: TaxRecordListResponse = response.data
      setRecords(data.records)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    }
  }, [vin])

  useEffect(() => {
    setLoading(true)
    fetchRecords().finally(() => setLoading(false))
  }, [fetchRecords])

  const handleAdd = () => {
    setEditingRecord(undefined)
    setShowForm(true)
  }

  const handleEdit = (record: TaxRecord) => {
    setEditingRecord(record)
    setShowForm(true)
  }

  const handleDelete = async (id: number) => {
    if (!confirm('Are you sure you want to delete this tax record?')) {
      return
    }

    setDeletingId(id)
    try {
      await api.delete(`/vehicles/${vin}/tax-records/${id}`)

      await fetchRecords()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete tax record')
    } finally {
      setDeletingId(null)
    }
  }

  const handleSuccess = () => {
    fetchRecords()
    setShowForm(false)
  }

  const formatCurrency = (amount: number): string => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(amount)
  }

  const getTotalAmount = (): number => {
    return records.reduce((sum, record) => sum + record.amount, 0)
  }

  if (loading) {
    return (
      <div className="text-center py-8 text-garage-text-muted">
        Loading tax records...
      </div>
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
          <h3 className="text-lg font-semibold text-garage-text">Tax & Registration Records</h3>
          {records.length > 0 && (
            <p className="text-sm text-garage-text-muted">
              {records.length} {records.length === 1 ? 'record' : 'records'} • Total: {formatCurrency(getTotalAmount())}
            </p>
          )}
        </div>
        <button
          onClick={handleAdd}
          className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
        >
          <Plus className="w-4 h-4" />
          <span>Add Record</span>
        </button>
      </div>

      {error && (
        <div className="flex items-start gap-2 p-3 bg-danger/10 border border-danger/20 rounded-md mb-4">
          <AlertCircle className="w-4 h-4 text-danger flex-shrink-0 mt-0.5" />
          <p className="text-sm text-danger">{error}</p>
        </div>
      )}

      {records.length === 0 ? (
        <div className="text-center py-12 bg-garage-surface border border-garage-border rounded-lg">
          <p className="text-garage-text mb-2">No tax or registration records yet</p>
          <p className="text-sm text-garage-text-muted mb-4">
            Track registration fees, inspections, property tax, and tolls
          </p>
          <button
            onClick={handleAdd}
            className="inline-flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>Add Your First Record</span>
          </button>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-garage-border">
                <th className="px-4 py-3 text-left text-sm font-semibold text-garage-text">Date Paid</th>
                <th className="px-4 py-3 text-left text-sm font-semibold text-garage-text">Type</th>
                <th className="px-4 py-3 text-right text-sm font-semibold text-garage-text">Amount</th>
                <th className="px-4 py-3 text-left text-sm font-semibold text-garage-text">Renewal Date</th>
                <th className="px-4 py-3 text-left text-sm font-semibold text-garage-text">Notes</th>
                <th className="px-4 py-3 text-right text-sm font-semibold text-garage-text">Actions</th>
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
                    {formatCurrency(record.amount)}
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
                        aria-label="Edit"
                        title="Edit"
                      >
                        <Edit className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleDelete(record.id)}
                        disabled={deletingId === record.id}
                        className="p-2 text-danger hover:bg-danger/10 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        aria-label="Delete"
                        title="Delete"
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
