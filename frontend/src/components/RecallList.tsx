import { useState, useEffect, useCallback } from 'react'
import { AlertTriangle, Plus, Trash2, Edit, CheckCircle, RefreshCw, ExternalLink } from 'lucide-react'
import { toast } from 'sonner'
import type { Recall, RecallListResponse } from '../types/recall'
import type { Vehicle } from '../types/vehicle'
import api from '../services/api'

interface RecallListProps {
  vin: string
  onAddClick: () => void
  onEditClick: (recall: Recall) => void
  onRefresh?: () => void
}

export default function RecallList({ vin, onAddClick, onEditClick, onRefresh }: RecallListProps) {
  const [recalls, setRecalls] = useState<Recall[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [checkingNHTSA, setCheckingNHTSA] = useState(false)
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'resolved'>('all')
  const [stats, setStats] = useState({ total: 0, active_count: 0, resolved_count: 0 })
  const [vehicle, setVehicle] = useState<Vehicle | null>(null)
  const [carComplaintsEnabled, setCarComplaintsEnabled] = useState(false)

  const fetchRecalls = useCallback(async () => {
    try {
      const params = statusFilter !== 'all' ? `?status=${statusFilter}` : ''
      const response = await api.get(`/vehicles/${vin}/recalls${params}`)
      const data: RecallListResponse = response.data
      setRecalls(data.recalls || [])
      setStats({
        total: data.total,
        active_count: data.active_count,
        resolved_count: data.resolved_count
      })
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    }
  }, [statusFilter, vin])

  useEffect(() => {
    setLoading(true)
    fetchRecalls().finally(() => setLoading(false))
  }, [fetchRecalls])

  useEffect(() => {
    if (onRefresh) {
      const refreshHandler = () => fetchRecalls()
      window.addEventListener('recalls-refresh', refreshHandler)
      return () => window.removeEventListener('recalls-refresh', refreshHandler)
    }
  }, [onRefresh, fetchRecalls])

  // Fetch vehicle data and settings for CarComplaints integration
  useEffect(() => {
    const fetchVehicleAndSettings = async () => {
      try {
        // Fetch vehicle data
        const vehicleResponse = await api.get(`/vehicles/${vin}`)
        setVehicle(vehicleResponse.data)

        // Fetch settings
        const settingsResponse = await api.get('/settings')
        const carComplaintsSetting = settingsResponse.data.settings.find((s: { key: string }) => s.key === 'carcomplaints_enabled')
        setCarComplaintsEnabled(carComplaintsSetting?.value === 'true')
      } catch {
        // Silent fail - non-critical background operation
      }
    }

    fetchVehicleAndSettings()
  }, [vin])

  const handleCheckNHTSA = async () => {
    setCheckingNHTSA(true)
    try {
      await api.post(`/vehicles/${vin}/recalls/check-nhtsa`)
      await fetchRecalls()
      toast.success('Successfully checked NHTSA for recalls')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to check NHTSA')
    } finally {
      setCheckingNHTSA(false)
    }
  }

  const handleDelete = async (recallId: number) => {
    if (!confirm('Are you sure you want to delete this recall?')) {
      return
    }

    setDeletingId(recallId)
    try {
      await api.delete(`/vehicles/${vin}/recalls/${recallId}`)
      await fetchRecalls()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete recall')
    } finally {
      setDeletingId(null)
    }
  }

  const handleMarkResolved = async (recall: Recall) => {
    try {
      await api.put(`/vehicles/${vin}/recalls/${recall.id}`, {
        is_resolved: !recall.is_resolved,
      })
      await fetchRecalls()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update recall status')
    }
  }

  const formatDate = (dateString?: string): string => {
    if (!dateString) return 'N/A'
    const date = new Date(dateString + "T00:00:00")
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">Loading recalls...</div>
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
          <h2 className="text-2xl font-bold text-garage-text">Safety Recalls</h2>
          <p className="text-sm text-garage-text-muted">
            {stats.active_count} active, {stats.resolved_count} resolved
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as 'all' | 'active' | 'resolved')}
            className="px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text text-sm"
          >
            <option value="all">All Recalls</option>
            <option value="active">Active Only</option>
            <option value="resolved">Resolved Only</option>
          </select>
          <button
            onClick={handleCheckNHTSA}
            disabled={checkingNHTSA}
            className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50"
            title="Check NHTSA for recalls"
          >
            <RefreshCw size={16} className={checkingNHTSA ? 'animate-spin' : ''} />
            {checkingNHTSA ? 'Checking...' : 'Check NHTSA'}
          </button>
          <button
            onClick={onAddClick}
            className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
          >
            <Plus size={20} />
            Add Recall
          </button>
        </div>
      </div>

      {recalls.length === 0 ? (
        <div className="text-center py-12 bg-garage-surface rounded-lg border border-garage-border">
          <AlertTriangle size={48} className="mx-auto text-garage-text-muted mb-4" />
          <p className="text-garage-text-muted mb-4">No recalls found</p>
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
        <div className="space-y-3">
          {recalls.map((recall) => (
            <div
              key={recall.id}
              className={`bg-garage-surface rounded-lg p-6 border ${
                recall.is_resolved
                  ? 'border-garage-border opacity-75'
                  : 'border-danger-500/50'
              }`}
            >
              <div className="flex justify-between items-start mb-4">
                <div className="flex items-start gap-3 flex-1">
                  {recall.is_resolved ? (
                    <CheckCircle className="text-success-500 mt-1 flex-shrink-0" size={24} />
                  ) : (
                    <AlertTriangle className="text-danger-500 mt-1 flex-shrink-0" size={24} />
                  )}
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="text-lg font-semibold text-garage-text">{recall.component}</h3>
                      {recall.nhtsa_campaign_number && (
                        <span className="text-xs px-2 py-1 bg-garage-bg rounded text-garage-text-muted font-mono">
                          {recall.nhtsa_campaign_number}
                        </span>
                      )}
                    </div>
                    {recall.date_announced && (
                      <p className="text-sm text-garage-text-muted mb-2">
                        Announced: {formatDate(recall.date_announced)}
                      </p>
                    )}
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => handleMarkResolved(recall)}
                    className="btn btn-ghost btn-sm"
                    title={recall.is_resolved ? 'Mark as active' : 'Mark as resolved'}
                  >
                    {recall.is_resolved ? (
                      <AlertTriangle size={16} />
                    ) : (
                      <CheckCircle size={16} />
                    )}
                  </button>
                  <button
                    onClick={() => onEditClick(recall)}
                    className="btn btn-ghost btn-sm"
                    title="Edit"
                  >
                    <Edit size={16} />
                  </button>
                  <button
                    onClick={() => handleDelete(recall.id)}
                    className="btn btn-ghost btn-sm text-danger"
                    disabled={deletingId === recall.id}
                    title="Delete"
                  >
                    {deletingId === recall.id ? '...' : <Trash2 size={16} />}
                  </button>
                </div>
              </div>

              <div className="space-y-3 ml-9">
                <div>
                  <p className="text-xs text-garage-text-muted mb-1">Summary</p>
                  <p className="text-sm text-garage-text whitespace-pre-wrap">{recall.summary}</p>
                </div>

                {recall.consequence && (
                  <div>
                    <p className="text-xs text-garage-text-muted mb-1">Consequence</p>
                    <p className="text-sm text-garage-text whitespace-pre-wrap">{recall.consequence}</p>
                  </div>
                )}

                {recall.remedy && (
                  <div>
                    <p className="text-xs text-garage-text-muted mb-1">Remedy</p>
                    <p className="text-sm text-garage-text whitespace-pre-wrap">{recall.remedy}</p>
                  </div>
                )}

                {recall.notes && (
                  <div>
                    <p className="text-xs text-garage-text-muted mb-1">Notes</p>
                    <p className="text-sm text-garage-text whitespace-pre-wrap">{recall.notes}</p>
                  </div>
                )}

                {recall.is_resolved && recall.resolved_at && (
                  <div>
                    <p className="text-xs text-garage-text-muted mb-1">Resolved</p>
                    <p className="text-sm text-success-500">{formatDate(recall.resolved_at)}</p>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* CarComplaints Integration */}
      {carComplaintsEnabled &&
        vehicle &&
        vehicle.make &&
        vehicle.model &&
        vehicle.year &&
        ['Car', 'Truck', 'SUV', 'Motorcycle'].includes(vehicle.vehicle_type) && (
        <div className="mt-6 bg-garage-surface rounded-lg border border-garage-border p-6">
          <div className="flex items-start gap-3">
            <ExternalLink className="w-5 h-5 text-primary mt-1" />
            <div className="flex-1">
              <h3 className="text-lg font-semibold text-garage-text mb-2">
                Research Common Issues
              </h3>
              <p className="text-sm text-garage-text-muted mb-4">
                Check CarComplaints.com for known issues, complaints, and problem trends for your {vehicle.year} {vehicle.make} {vehicle.model}.
              </p>
              <a
                href={`https://www.carcomplaints.com/${vehicle.make.toLowerCase().replace(/\b\w/g, c => c.toUpperCase()).replace(/\s+/g, '_')}/${vehicle.model.toLowerCase().replace(/\b\w/g, c => c.toUpperCase()).replace(/\s+/g, '_')}/${vehicle.year}/`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
              >
                <ExternalLink className="w-4 h-4" />
                View on CarComplaints.com
              </a>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
