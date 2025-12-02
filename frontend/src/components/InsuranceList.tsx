import { useState, useEffect, useCallback } from 'react'
import { Shield, Plus, Trash2, Edit3, Calendar } from 'lucide-react'
import { toast } from 'sonner'
import api from '../services/api'
import type { InsurancePolicy } from '../types/insurance'

interface InsuranceListProps {
  vin: string
  onAddClick: () => void
  onEditClick: (policy: InsurancePolicy) => void
}

export default function InsuranceList({ vin, onAddClick, onEditClick }: InsuranceListProps) {
  const [policies, setPolicies] = useState<InsurancePolicy[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)

  const fetchPolicies = useCallback(async () => {
    try {
      const response = await api.get(`/vehicles/${vin}/insurance`)
      setPolicies(response.data)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    }
  }, [vin])

  useEffect(() => {
    setLoading(true)
    fetchPolicies().finally(() => setLoading(false))
  }, [fetchPolicies])

  const handleDelete = async (policyId: number) => {
    if (!confirm('Are you sure you want to delete this insurance policy?')) {
      return
    }

    setDeletingId(policyId)
    try {
      await api.delete(`/vehicles/${vin}/insurance/${policyId}`)
      await fetchPolicies()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete insurance policy')
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

  const isExpired = (endDate: string): boolean => {
    return new Date(endDate) < new Date()
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">Loading insurance policies...</div>
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
          <h2 className="text-2xl font-bold text-garage-text">Insurance Policies</h2>
          <p className="text-sm text-garage-text-muted">
            {policies.length} {policies.length === 1 ? 'policy' : 'policies'} tracked
          </p>
        </div>
        <button
          onClick={onAddClick}
          className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
        >
          <Plus size={20} />
          Add Insurance Policy
        </button>
      </div>

      {policies.length === 0 ? (
        <div className="text-center py-12 bg-garage-surface rounded-lg">
          <Shield size={48} className="mx-auto text-garage-text-muted mb-4" />
          <p className="text-garage-text-muted mb-4">No insurance policies recorded yet</p>
          <button onClick={onAddClick} className="inline-flex items-center gap-2 btn btn-primary rounded-lg transition-colors">
            Add Your First Insurance Policy
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          {policies.map((policy) => (
            <div
              key={policy.id}
              className={`bg-garage-surface rounded-lg p-6 border ${
                isExpired(policy.end_date)
                  ? 'border-danger/30'
                  : 'border-garage-border'
              }`}
            >
              <div className="flex justify-between items-start mb-4">
                <div className="flex items-start gap-3">
                  <Shield
                    className={
                      isExpired(policy.end_date)
                        ? 'text-danger mt-1'
                        : 'text-primary mt-1'
                    }
                    size={20}
                  />
                  <div>
                    <h3 className="text-lg font-semibold text-garage-text">{policy.provider}</h3>
                    <p className="text-sm text-garage-text-muted">{policy.policy_type}</p>
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => onEditClick(policy)}
                    className="btn btn-ghost btn-sm"
                    title="Edit"
                  >
                    <Edit3 size={16} />
                  </button>
                  <button
                    onClick={() => handleDelete(policy.id)}
                    className="btn btn-ghost btn-sm text-danger"
                    disabled={deletingId === policy.id}
                    title="Delete"
                  >
                    {deletingId === policy.id ? '...' : <Trash2 size={16} />}
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                <div>
                  <p className="text-xs text-garage-text-muted mb-1">Policy Number</p>
                  <p className="text-sm text-garage-text">{policy.policy_number}</p>
                </div>
                <div>
                  <p className="text-xs text-garage-text-muted mb-1">Start Date</p>
                  <p className="text-sm text-garage-text">{formatDate(policy.start_date)}</p>
                </div>
                <div>
                  <p className="text-xs text-garage-text-muted mb-1">End Date</p>
                  <p className="text-sm text-garage-text">{formatDate(policy.end_date)}</p>
                </div>
                {policy.premium_amount && (
                  <div>
                    <p className="text-xs text-garage-text-muted mb-1">Premium Amount</p>
                    <p className="text-sm text-garage-text">
                      ${parseFloat(policy.premium_amount).toLocaleString()}
                      {policy.premium_frequency && ` / ${policy.premium_frequency}`}
                    </p>
                  </div>
                )}
              </div>

              {policy.deductible && (
                <div className="mb-2">
                  <p className="text-xs text-garage-text-muted mb-1">Deductible</p>
                  <p className="text-sm text-garage-text">${parseFloat(policy.deductible).toLocaleString()}</p>
                </div>
              )}

              {policy.coverage_limits && (
                <div className="mb-2">
                  <p className="text-xs text-garage-text-muted mb-1">Coverage Limits</p>
                  <p className="text-sm text-garage-text whitespace-pre-wrap">{policy.coverage_limits}</p>
                </div>
              )}

              {policy.notes && (
                <div>
                  <p className="text-xs text-garage-text-muted mb-1">Notes</p>
                  <p className="text-sm text-garage-text whitespace-pre-wrap">{policy.notes}</p>
                </div>
              )}

              {isExpired(policy.end_date) && (
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
