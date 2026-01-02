import { useState, useEffect, useCallback } from 'react'
import { FileText, Plus, Trash2, Edit, CheckCircle, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import type { TSB, TSBListResponse } from '../types/tsb'
import api from '../services/api'

interface TSBListProps {
  vin: string
  onAddClick: () => void
  onEditClick: (tsb: TSB) => void
  onRefresh?: () => void
}

export default function TSBList({ vin, onAddClick, onEditClick, onRefresh }: TSBListProps) {
  const [tsbs, setTsbs] = useState<TSB[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [checkingNHTSA, setCheckingNHTSA] = useState(false)
  const [statusFilter, setStatusFilter] = useState<'all' | 'pending' | 'applied'>('all')

  const fetchTSBs = useCallback(async () => {
    try {
      const response = await api.get(`/tsbs/vehicles/${vin}`)
      const data: TSBListResponse = response.data
      setTsbs(data.tsbs || [])
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    }
  }, [vin])

  useEffect(() => {
    setLoading(true)
    fetchTSBs().finally(() => setLoading(false))
  }, [fetchTSBs])

  useEffect(() => {
    if (onRefresh) {
      const refreshHandler = () => fetchTSBs()
      window.addEventListener('tsbs-refresh', refreshHandler)
      return () => window.removeEventListener('tsbs-refresh', refreshHandler)
    }
  }, [onRefresh, fetchTSBs])

  const handleCheckNHTSA = async () => {
    setCheckingNHTSA(true)
    try {
      const response = await api.get(`/tsbs/vehicles/${vin}/check-nhtsa`)
      const data = response.data

      if (data.found && data.count > 0) {
        toast.success(`Found ${data.count} TSB(s) from NHTSA`)
        // Note: TSBs from NHTSA are shown but not automatically saved
        // User can manually add them if needed
      } else {
        toast.info('No TSBs found from NHTSA')
      }

      await fetchTSBs()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to check NHTSA')
    } finally {
      setCheckingNHTSA(false)
    }
  }

  const handleDelete = async (tsbId: number) => {
    if (!confirm('Are you sure you want to delete this TSB?')) {
      return
    }

    setDeletingId(tsbId)
    try {
      await api.delete(`/tsbs/${tsbId}`)
      await fetchTSBs()
      toast.success('TSB deleted successfully')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete TSB')
    } finally {
      setDeletingId(null)
    }
  }

  const handleMarkApplied = async (tsb: TSB) => {
    try {
      const newStatus = tsb.status === 'applied' ? 'acknowledged' : 'applied'
      await api.put(`/tsbs/${tsb.id}`, {
        status: newStatus,
        applied_at: newStatus === 'applied' ? new Date().toISOString() : null,
      })
      await fetchTSBs()
      toast.success(`TSB marked as ${newStatus}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update TSB status')
    }
  }

  const formatDate = (dateString?: string): string => {
    if (!dateString) return 'N/A'
    const date = new Date(dateString)
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  }

  const getStatusBadge = (status: TSB['status']) => {
    const statusConfig = {
      pending: { bg: 'bg-yellow-900/30', text: 'text-yellow-400', label: 'Pending' },
      acknowledged: { bg: 'bg-blue-900/30', text: 'text-blue-400', label: 'Acknowledged' },
      applied: { bg: 'bg-green-900/30', text: 'text-green-400', label: 'Applied' },
      not_applicable: { bg: 'bg-gray-900/30', text: 'text-gray-400', label: 'N/A' },
      ignored: { bg: 'bg-gray-900/30', text: 'text-gray-500', label: 'Ignored' },
    }

    const config = statusConfig[status]
    return (
      <span className={`px-2 py-1 text-xs font-medium rounded ${config.bg} ${config.text}`}>
        {config.label}
      </span>
    )
  }

  const filteredTSBs = tsbs.filter(tsb => {
    if (statusFilter === 'all') return true
    if (statusFilter === 'pending') return tsb.status === 'pending' || tsb.status === 'acknowledged'
    if (statusFilter === 'applied') return tsb.status === 'applied'
    return true
  })

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">Loading TSBs...</div>
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
          <h2 className="text-2xl font-bold text-garage-text">Technical Service Bulletins</h2>
          <p className="text-sm text-garage-text-muted">
            {filteredTSBs.length} TSB{filteredTSBs.length !== 1 ? 's' : ''} found
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}
            className="px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text text-sm"
          >
            <option value="all">All TSBs</option>
            <option value="pending">Pending</option>
            <option value="applied">Applied</option>
          </select>
          <button
            onClick={handleCheckNHTSA}
            disabled={checkingNHTSA}
            className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50"
            title="Check NHTSA for TSBs"
          >
            <RefreshCw size={16} className={checkingNHTSA ? 'animate-spin' : ''} />
            {checkingNHTSA ? 'Checking...' : 'Check NHTSA'}
          </button>
          <button
            onClick={onAddClick}
            className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
          >
            <Plus size={20} />
            Add TSB
          </button>
        </div>
      </div>

      {filteredTSBs.length === 0 ? (
        <div className="text-center py-12 bg-garage-surface rounded-lg border border-garage-border">
          <FileText size={48} className="mx-auto text-garage-text-muted mb-4" />
          <p className="text-garage-text-muted mb-4">No TSBs found</p>
          <div className="flex gap-2 justify-center">
            <button
              onClick={handleCheckNHTSA}
              disabled={checkingNHTSA}
              className="inline-flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50"
            >
              <RefreshCw size={16} className={checkingNHTSA ? 'animate-spin' : ''} />
              {checkingNHTSA ? 'Checking...' : 'Check NHTSA'}
            </button>
            <button
              onClick={onAddClick}
              className="inline-flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
            >
              Add Manual Entry
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          {filteredTSBs.map((tsb) => (
            <div
              key={tsb.id}
              className="bg-garage-surface border border-garage-border rounded-lg p-4 hover:border-primary transition-colors"
            >
              <div className="flex justify-between items-start mb-3">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-2">
                    {tsb.tsb_number && (
                      <span className="font-mono text-sm px-2 py-1 bg-garage-bg rounded text-garage-text">
                        {tsb.tsb_number}
                      </span>
                    )}
                    {getStatusBadge(tsb.status)}
                    {tsb.source === 'nhtsa' && (
                      <span className="text-xs px-2 py-1 bg-blue-900/20 text-blue-400 rounded">
                        NHTSA
                      </span>
                    )}
                  </div>
                  <h3 className="text-lg font-semibold text-garage-text mb-1">
                    {tsb.component}
                  </h3>
                  <p className="text-sm text-garage-text-muted mb-2">{tsb.summary}</p>
                  <div className="flex flex-wrap gap-4 text-xs text-garage-text-muted">
                    <span>Created: {formatDate(tsb.created_at)}</span>
                    {tsb.applied_at && (
                      <span>Applied: {formatDate(tsb.applied_at)}</span>
                    )}
                  </div>
                </div>
                <div className="flex gap-2 ml-4">
                  <button
                    onClick={() => handleMarkApplied(tsb)}
                    className="p-2 hover:bg-garage-bg rounded transition-colors"
                    title={tsb.status === 'applied' ? 'Mark as acknowledged' : 'Mark as applied'}
                  >
                    <CheckCircle
                      size={20}
                      className={tsb.status === 'applied' ? 'text-green-400' : 'text-garage-text-muted'}
                    />
                  </button>
                  <button
                    onClick={() => onEditClick(tsb)}
                    className="p-2 hover:bg-garage-bg rounded transition-colors"
                    title="Edit TSB"
                  >
                    <Edit size={20} className="text-garage-text-muted hover:text-garage-text" />
                  </button>
                  <button
                    onClick={() => handleDelete(tsb.id)}
                    disabled={deletingId === tsb.id}
                    className="p-2 hover:bg-danger/10 rounded transition-colors disabled:opacity-50"
                    title="Delete TSB"
                  >
                    <Trash2
                      size={20}
                      className={deletingId === tsb.id ? 'text-danger animate-pulse' : 'text-danger'}
                    />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
