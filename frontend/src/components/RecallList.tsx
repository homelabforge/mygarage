import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Plus, Trash2, Edit, CheckCircle, RefreshCw, ExternalLink } from 'lucide-react'
import { toast } from 'sonner'
import type { Recall } from '../types/recall'
import type { Vehicle } from '../types/vehicle'
import api from '../services/api'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { isSettingOn } from '../utils/settingSwitch'
import { usePublicSettings } from '../hooks/usePublicSettings'
import { formatDateForDisplay } from '../utils/dateUtils'
import { useDateLocale } from '../hooks/useDateLocale'
import { formatAPITimestamp } from '../utils/parseAPITimestamp'
import { useRecallRecords, useDeleteRecallRecord, useCheckNHTSA, useToggleRecallResolved } from '../hooks/queries/useRecallRecords'
import { useQueryClient } from '@tanstack/react-query'
import { Button, IconButton, EmptyState, Mono, Chip, Select } from './ui'

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
  // Both switches are public, so a non-admin reads them too (/settings is
  // admin-only). NHTSA reads as on until it says otherwise, matching the
  // backend default, so a failed read never disables the button; the
  // backend's 409 is the enforcement.
  const publicSettings = usePublicSettings()
  const nhtsaEnabled = isSettingOn(publicSettings.nhtsa_enabled, true)
  const carComplaintsEnabled = isSettingOn(publicSettings.carcomplaints_enabled)

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

  // Fetch vehicle data for the CarComplaints link
  useEffect(() => {
    const fetchVehicle = async () => {
      try {
        const vehicleResponse = await api.get(`/vehicles/${vin}`)
        setVehicle(vehicleResponse.data)
      } catch {
        // Silent fail - non-critical background operation
      }
    }

    fetchVehicle()
  }, [vin])

  const handleCheckNHTSA = () => {
    nhtsaMutation.mutate(undefined, {
      onSuccess: () => {
        toast.success(t('recallList.nhtsaSuccess'))
      },
      onError: (err) => {
        toast.error(getActionErrorMessage(err, t('recallList.nhtsaCheckAction')))
      },
    })
  }

  const handleDelete = (recallId: number) => {
    if (!confirm(t('recallList.confirmDelete'))) {
      return
    }

    deleteMutation.mutate(recallId, {
      onError: (err) => {
        toast.error(getActionErrorMessage(err, t('recallList.deleteAction')))
      },
    })
  }

  const handleMarkResolved = (recall: Recall) => {
    toggleResolvedMutation.mutate(
      { recallId: recall.id, isResolved: !recall.is_resolved },
      {
        onError: (err) => {
          toast.error(getActionErrorMessage(err, t('recallList.statusAction')))
        },
      }
    )
  }

  const formatDate = (dateString?: string): string => {
    if (!dateString) return t('recallList.notAvailable')
    return formatDateForDisplay(dateString, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    }, dateLocale)
  }

  // resolved_at is a datetime, not a calendar day: it takes the timestamp path.
  const formatTimestamp = (value?: string | null): string =>
    formatAPITimestamp(
      value,
      (d) => d.toLocaleDateString(dateLocale, { year: 'numeric', month: 'short', day: 'numeric' }),
      t('recallList.notAvailable'),
    )

  if (isLoading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-text-mute">{t('recallList.loading')}</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-danger/10 border border-danger rounded-lg p-4">
        <p className="text-danger">{getActionErrorMessage(error, t('recallList.loadAction'))}</p>
      </div>
    )
  }

  return (
    <div>
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
        <div>
          <h2 className="text-2xl font-bold text-text">{t('recallList.title')}</h2>
          <p className="text-sm text-text-mute">{t('recallList.activeCount', { active: stats.active_count, resolved: stats.resolved_count })}</p>
          {!nhtsaEnabled && (
            <p className="mt-1 text-sm text-text-mute">{t('recallList.nhtsaSwitchedOff')}</p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <Select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as 'all' | 'active' | 'resolved')}
            options={[
              { value: 'all', label: t('recallList.allRecalls') },
              { value: 'active', label: t('recallList.activeOnly') },
              { value: 'resolved', label: t('recallList.resolvedOnly') },
            ]}
          />
          <Button variant="secondary" icon={RefreshCw} onClick={handleCheckNHTSA} loading={nhtsaMutation.isPending} disabled={!nhtsaEnabled} title={t('recallList.checkNHTSATitle')}>
            {nhtsaMutation.isPending ? t('recallList.checking') : t('recallList.checkNHTSA')}
          </Button>
          <Button variant="primary" icon={Plus} onClick={onAddClick}>{t('recallList.addRecall')}</Button>
        </div>
      </div>

      {recalls.length === 0 ? (
        <EmptyState
          icon={AlertTriangle}
          title={t('recallList.noRecords')}
          action={
            <div className="flex gap-2 justify-center">
              <Button variant="secondary" icon={RefreshCw} onClick={handleCheckNHTSA} loading={nhtsaMutation.isPending} disabled={!nhtsaEnabled}>
                {nhtsaMutation.isPending ? t('recallList.checking') : t('recallList.checkNHTSA')}
              </Button>
              <Button variant="primary" onClick={onAddClick}>{t('recallList.addManualEntry')}</Button>
            </div>
          }
        />
      ) : (
        <div className="space-y-3">
          {recalls.map((recall) => (
            <div
              key={recall.id}
              className={`rounded-card border bg-surface p-6 ${recall.is_resolved ? 'border-border opacity-75' : 'border-danger/50'}`}
            >
              <div className="flex justify-between items-start mb-4">
                <div className="flex items-start gap-3 flex-1">
                  {recall.is_resolved
                    ? <CheckCircle aria-hidden="true" className="text-success mt-1 flex-shrink-0" size={24} />
                    : <AlertTriangle aria-hidden="true" className="text-danger mt-1 flex-shrink-0" size={24} />}
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="text-lg font-semibold text-text">{recall.component}</h3>
                      {recall.nhtsa_campaign_number && (
                        <Chip tone="muted"><Mono size="xs" tone="inherit">{recall.nhtsa_campaign_number}</Mono></Chip>
                      )}
                    </div>
                    {recall.date_announced && (
                      <p className="text-sm text-text-mute mb-2">{t('recallList.announced')}: <Mono size="sm" tone="muted">{formatDate(recall.date_announced)}</Mono></p>
                    )}
                  </div>
                </div>
                <div className="flex gap-2">
                  <IconButton
                    icon={recall.is_resolved ? AlertTriangle : CheckCircle}
                    label={recall.is_resolved ? t('recallList.markActive') : t('recallList.markResolved')}
                    variant="ghost"
                    size="sm"
                    onClick={() => handleMarkResolved(recall)}
                  />
                  <IconButton icon={Edit} label={t('common:edit')} variant="ghost" size="sm" onClick={() => onEditClick(recall)} />
                  <IconButton
                    icon={Trash2}
                    label={t('common:delete')}
                    variant="danger"
                    size="sm"
                    disabled={deleteMutation.isPending && deleteMutation.variables === recall.id}
                    onClick={() => handleDelete(recall.id)}
                  />
                </div>
              </div>

              <div className="space-y-3 ml-9">
                <div>
                  <p className="text-xs text-text-mute mb-1">{t('recallList.summary')}</p>
                  <p className="text-sm text-text whitespace-pre-wrap">{recall.summary}</p>
                </div>
                {recall.consequence && (
                  <div>
                    <p className="text-xs text-text-mute mb-1">{t('recallList.consequence')}</p>
                    <p className="text-sm text-text whitespace-pre-wrap">{recall.consequence}</p>
                  </div>
                )}
                {recall.remedy && (
                  <div>
                    <p className="text-xs text-text-mute mb-1">{t('recallList.remedy')}</p>
                    <p className="text-sm text-text whitespace-pre-wrap">{recall.remedy}</p>
                  </div>
                )}
                {recall.notes && (
                  <div>
                    <p className="text-xs text-text-mute mb-1">{t('recallList.notes')}</p>
                    <p className="text-sm text-text whitespace-pre-wrap">{recall.notes}</p>
                  </div>
                )}
                {recall.is_resolved && recall.resolved_at && (
                  <div>
                    <p className="text-xs text-text-mute mb-1">{t('recallList.resolved')}</p>
                    <Mono as="p" size="sm" tone="success">{formatTimestamp(recall.resolved_at)}</Mono>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* CarComplaints Integration. Road vehicles only, so a type the app
          doesn't know (null) doesn't get the link. */}
      {carComplaintsEnabled &&
        vehicle &&
        vehicle.make &&
        vehicle.model &&
        vehicle.year &&
        vehicle.vehicle_type != null &&
        ['Car', 'Truck', 'SUV', 'Motorcycle'].includes(vehicle.vehicle_type) && (
        <div className="mt-6 rounded-card border border-(--accent-line) bg-(--accent-soft) p-6">
          <div className="flex items-start gap-3">
            <ExternalLink aria-hidden="true" className="w-5 h-5 text-(--accent-fg) mt-1" />
            <div className="flex-1">
              <h3 className="text-lg font-semibold text-text mb-2">{t('recallList.researchCommonIssues')}</h3>
              <p className="text-sm text-text-mute mb-4">{t('recallList.carComplaintsDesc', { year: vehicle.year, make: vehicle.make, model: vehicle.model })}</p>
              <a
                href={`https://www.carcomplaints.com/${vehicle.make.toLowerCase().replace(/\b\w/g, c => c.toUpperCase()).replace(/\s+/g, '_')}/${vehicle.model.toLowerCase().replace(/\b\w/g, c => c.toUpperCase()).replace(/\s+/g, '_')}/${vehicle.year}/`}
                target="_blank"
                rel="noopener noreferrer"
                className="ui-focus-ring ui-motion inline-flex items-center gap-2 rounded-control h-btn-md px-4 text-sm font-semibold bg-(--accent-solid) text-(--accent-on-solid) ui-hover-solid"
              >
                <ExternalLink aria-hidden="true" className="w-4 h-4" />
                {t('recallList.viewOnCarComplaints')}
              </a>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
