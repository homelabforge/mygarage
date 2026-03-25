import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Plus, Trash2, Edit, CheckCircle, RefreshCw, ExternalLink } from 'lucide-react'
import { toast } from 'sonner'
import type { Recall } from '../types/recall'
import type { Vehicle } from '../types/vehicle'
import api from '../services/api'
import { formatDateForDisplay } from '../utils/dateUtils'
import { useDateLocale } from '../hooks/useDateLocale'
import { useRecallRecords, useDeleteRecallRecord, useCheckNHTSA, useToggleRecallResolved } from '../hooks/queries/useRecallRecords'
import { useQueryClient } from '@tanstack/react-query'

interface RecallListProps {
  vin: string
  onAddClick: () => void
  onEditClick: (recall: Recall) => void
  onRefresh?: () => void
}

export default function RecallList({ vin, onAddClick, onEditClick, onRefresh }: RecallListProps) {
  const { t } = useTranslation('vehicles')
  const dateLocale = useDateLocale()
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'resolved'>('all')
  const [vehicle, setVehicle] = useState<Vehicle | null>(null)
  const [carComplaintsEnabled, setCarComplaintsEnabled] = useState(false)

  const { data, isLoading, error } = useRecallRecords(vin, statusFilter)
  const deleteMutation = useDeleteRecallRecord(vin)
  const nhtsaMutation = useCheckNHTSA(vin)
  const toggleResolvedMutation = useToggleRecallResolved(vin)
  const queryClient = useQueryClient()

  const recalls = data?.recalls ?? []
  const stats = {
    total: data?.total ?? 0,
    active_count: data?.active_count ?? 0,
    resolved_count: data?.resolved_count ?? 0,
  }

  // Listen for external refresh events
  useEffect(() => {
    if (onRefresh) {
      const refreshHandler = () => {
        queryClient.invalidateQueries({ queryKey: ['recalls', vin] })
      }
      window.addEventListener('recalls-refresh', refreshHandler)
      return () => window.removeEventListener('recalls-refresh', refreshHandler)
    }
  }, [onRefresh, vin, queryClient])

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

  const handleCheckNHTSA = () => {
    nhtsaMutation.mutate(undefined, {
      onSuccess: () => {
        toast.success(t('recallList.nhtsaSuccess'))
      },
      onError: (err) => {
        toast.error(err instanceof Error ? err.message : t('recallList.nhtsaError'))
      },
    })
  }

  const handleDelete = (recallId: number) => {
    if (!confirm(t('recallList.confirmDelete'))) {
      return
    }

    deleteMutation.mutate(recallId, {
      onError: (err) => {
        toast.error(err instanceof Error ? err.message : t('recallList.deleteError'))
      },
    })
  }

  const handleMarkResolved = (recall: Recall) => {
    toggleResolvedMutation.mutate(
      { recallId: recall.id, isResolved: !recall.is_resolved },
      {
        onError: (err) => {
          toast.error(err instanceof Error ? err.message : t('recallList.statusError'))
        },
      }
    )
  }

  const formatDate = (dateString?: string): string => {
    if (!dateString) return 'N/A'
    return formatDateForDisplay(dateString, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    }, dateLocale)
  }

  if (isLoading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">{t('recallList.loading')}</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-danger/10 border border-danger rounded-lg p-4">
        <p className="text-danger">{error.message}</p>
      </div>
    )
  }

  return (
    <div>
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
        <div>
          <h2 className="text-2xl font-bold text-garage-text">{t('recallList.title')}</h2>
          <p className="text-sm text-garage-text-muted">
            {t('recallList.activeCount', { active: stats.active_count, resolved: stats.resolved_count })}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as 'all' | 'active' | 'resolved')}
            className="px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text text-sm"
          >
            <option value="all">{t('recallList.allRecalls')}</option>
            <option value="active">{t('recallList.activeOnly')}</option>
            <option value="resolved">{t('recallList.resolvedOnly')}</option>
          </select>
          <button
            onClick={handleCheckNHTSA}
            disabled={nhtsaMutation.isPending}
            className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50"
            title="Check NHTSA for recalls"
          >
            <RefreshCw size={16} className={nhtsaMutation.isPending ? 'animate-spin' : ''} />
            {nhtsaMutation.isPending ? t('recallList.checking') : t('recallList.checkNHTSA')}
          </button>
          <button
            onClick={onAddClick}
            className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
          >
            <Plus size={20} />
            {t('recallList.addRecall')}
          </button>
        </div>
      </div>

      {recalls.length === 0 ? (
        <div className="text-center py-12 bg-garage-surface rounded-lg border border-garage-border">
          <AlertTriangle size={48} className="mx-auto text-garage-text-muted mb-4" />
          <p className="text-garage-text-muted mb-4">{t('recallList.noRecords')}</p>
          <div className="flex gap-2 justify-center">
            <button
              onClick={handleCheckNHTSA}
              disabled={nhtsaMutation.isPending}
              className="inline-flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50"
            >
              <RefreshCw size={16} className={nhtsaMutation.isPending ? 'animate-spin' : ''} />
              {nhtsaMutation.isPending ? t('recallList.checking') : t('recallList.checkNHTSA')}
            </button>
            <button
              onClick={onAddClick}
              className="inline-flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
            >
              {t('recallList.addManualEntry')}
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
                        {t('recallList.announced')}: {formatDate(recall.date_announced)}
                      </p>
                    )}
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => handleMarkResolved(recall)}
                    className="btn btn-ghost btn-sm"
                    title={recall.is_resolved ? t('recallList.markActive') : t('recallList.markResolved')}
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
                    title={t('common:edit')}
                  >
                    <Edit size={16} />
                  </button>
                  <button
                    onClick={() => handleDelete(recall.id)}
                    className="btn btn-ghost btn-sm text-danger"
                    disabled={deleteMutation.isPending && deleteMutation.variables === recall.id}
                    title={t('common:delete')}
                  >
                    {deleteMutation.isPending && deleteMutation.variables === recall.id ? '...' : <Trash2 size={16} />}
                  </button>
                </div>
              </div>

              <div className="space-y-3 ml-9">
                <div>
                  <p className="text-xs text-garage-text-muted mb-1">{t('recallList.summary')}</p>
                  <p className="text-sm text-garage-text whitespace-pre-wrap">{recall.summary}</p>
                </div>

                {recall.consequence && (
                  <div>
                    <p className="text-xs text-garage-text-muted mb-1">{t('recallList.consequence')}</p>
                    <p className="text-sm text-garage-text whitespace-pre-wrap">{recall.consequence}</p>
                  </div>
                )}

                {recall.remedy && (
                  <div>
                    <p className="text-xs text-garage-text-muted mb-1">{t('recallList.remedy')}</p>
                    <p className="text-sm text-garage-text whitespace-pre-wrap">{recall.remedy}</p>
                  </div>
                )}

                {recall.notes && (
                  <div>
                    <p className="text-xs text-garage-text-muted mb-1">{t('recallList.notes')}</p>
                    <p className="text-sm text-garage-text whitespace-pre-wrap">{recall.notes}</p>
                  </div>
                )}

                {recall.is_resolved && recall.resolved_at && (
                  <div>
                    <p className="text-xs text-garage-text-muted mb-1">{t('recallList.resolved')}</p>
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
              <h3 className="text-lg font-semibold text-garage-text mb-2">{t('recallList.researchCommonIssues')}</h3>
              <p className="text-sm text-garage-text-muted mb-4">
                {t('recallList.carComplaintsDesc', { year: vehicle.year, make: vehicle.make, model: vehicle.model })}
              </p>
              <a
                href={`https://www.carcomplaints.com/${vehicle.make.toLowerCase().replace(/\b\w/g, c => c.toUpperCase()).replace(/\s+/g, '_')}/${vehicle.model.toLowerCase().replace(/\b\w/g, c => c.toUpperCase()).replace(/\s+/g, '_')}/${vehicle.year}/`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
              >
                <ExternalLink className="w-4 h-4" />
                {t('recallList.viewOnCarComplaints')}
              </a>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
