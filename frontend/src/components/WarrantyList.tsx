import { useState, useEffect, useCallback } from 'react'
import { Shield, Plus, Trash2, Edit3, Calendar } from 'lucide-react'
import { toast } from 'sonner'
import type { WarrantyRecord } from '../types/warranty'
import api from '../services/api'

interface WarrantyListProps {
  vin: string
  onAddClick: () => void
  onEditClick: (warranty: WarrantyRecord) => void
}

export default function WarrantyList({ vin, onAddClick, onEditClick }: WarrantyListProps) {
  const [warranties, setWarranties] = useState<WarrantyRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)

  const fetchWarranties = useCallback(async () => {
    try {
      const response = await api.get(`/vehicles/${vin}/warranties`)
      setWarranties(response.data)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    }
  }, [vin])

  useEffect(() => {
    setLoading(true)
    fetchWarranties().finally(() => setLoading(false))
  }, [fetchWarranties])

  const handleDelete = async (warrantyId: number) => {
    if (!confirm('Are you sure you want to delete this warranty?')) {
      return
    }

    setDeletingId(warrantyId)
    try {
      await api.delete(`/vehicles/${vin}/warranties/${warrantyId}`)
      await fetchWarranties()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete warranty')
    } finally {
      setDeletingId(null)
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

  const isExpired = (endDate: string | null): boolean => {
    if (!endDate) return false
    return new Date(endDate) < new Date()
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">Loading warranties...</div>
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
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-2xl font-bold text-garage-text">Warranties</h2>
          <p className="text-sm text-garage-text-muted">
            {warranties.length} {warranties.length === 1 ? 'warranty' : 'warranties'} tracked
          </p>
        </div>
        <button
          onClick={onAddClick}
          className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
        >
          <Plus size={20} />
          Add Warranty
        </button>
      </div>

      {warranties.length === 0 ? (
        <div className="text-center py-12 bg-garage-surface rounded-lg">
          <Shield size={48} className="mx-auto text-garage-text-muted mb-4" />
          <p className="text-garage-text-muted mb-4">No warranties recorded yet</p>
          <button onClick={onAddClick} className="inline-flex items-center gap-2 btn btn-primary rounded-lg transition-colors">
            Add Your First Warranty
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
                    title="Edit"
                  >
                    <Edit3 size={16} />
                  </button>
                  <button
                    onClick={() => handleDelete(warranty.id)}
                    className="btn btn-ghost btn-sm text-danger"
                    disabled={deletingId === warranty.id}
                    title="Delete"
                  >
                    {deletingId === warranty.id ? '...' : <Trash2 size={16} />}
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                <div>
                  <p className="text-xs text-garage-text-muted mb-1">Start Date</p>
                  <p className="text-sm text-garage-text">{formatDate(warranty.start_date)}</p>
                </div>
                <div>
                  <p className="text-xs text-garage-text-muted mb-1">End Date</p>
                  <p className="text-sm text-garage-text">
                    {warranty.end_date ? formatDate(warranty.end_date) : 'N/A'}
                  </p>
                </div>
                {warranty.mileage_limit && (
                  <div>
                    <p className="text-xs text-garage-text-muted mb-1">Mileage Limit</p>
                    <p className="text-sm text-garage-text">{warranty.mileage_limit.toLocaleString()} mi</p>
                  </div>
                )}
                {warranty.policy_number && (
                  <div>
                    <p className="text-xs text-garage-text-muted mb-1">Policy Number</p>
                    <p className="text-sm text-garage-text">{warranty.policy_number}</p>
                  </div>
                )}
              </div>

              {warranty.coverage_details && (
                <div className="mb-2">
                  <p className="text-xs text-garage-text-muted mb-1">Coverage Details</p>
                  <p className="text-sm text-garage-text whitespace-pre-wrap">{warranty.coverage_details}</p>
                </div>
              )}

              {warranty.notes && (
                <div>
                  <p className="text-xs text-garage-text-muted mb-1">Notes</p>
                  <p className="text-sm text-garage-text whitespace-pre-wrap">{warranty.notes}</p>
                </div>
              )}

              {warranty.end_date && isExpired(warranty.end_date) && (
                <div className="mt-4 text-sm text-danger flex items-center gap-2">
                  <Calendar size={16} />
                  Expired
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
