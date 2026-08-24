/**
 * LiveLink DTCs Tab - Diagnostic Trouble Codes management
 */

import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import {
  AlertTriangle,
  AlertCircle,
  Info,
  CheckCircle,
  Search,
  ExternalLink,
  FileText,
  RefreshCw,
} from 'lucide-react'
import { livelinkService } from '@/services/livelinkService'
import type { VehicleDTC, VehicleDTCListResponse } from '@/types/livelink'
import { formatAPITimestamp } from '@/utils/parseAPITimestamp'
import { Card, Chip, IconButton, Button, Input, Mono, EmptyState } from '../ui'

interface LiveLinkDTCsTabProps {
  vin: string
}

type FilterType = 'all' | 'active' | 'cleared'

export default function LiveLinkDTCsTab({ vin }: LiveLinkDTCsTabProps) {
  const { t } = useTranslation('vehicles')
  const [dtcs, setDtcs] = useState<VehicleDTCListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<FilterType>('active')
  const [editingNotes, setEditingNotes] = useState<number | null>(null)
  const [notesValue, setNotesValue] = useState('')

  const fetchDTCs = useCallback(async () => {
    setLoading(true)
    try {
      const data = await livelinkService.getVehicleDTCs(vin, filter === 'active')
      setDtcs(data)
    } catch (err) {
      console.error('Failed to fetch DTCs:', err)
      toast.error(t('livelink.dtcs.loadError'))
    } finally {
      setLoading(false)
    }
  }, [vin, filter, t])

  useEffect(() => {
    fetchDTCs()
  }, [fetchDTCs])

  const handleClearDTC = async (dtcId: number, code: string) => {
    if (!confirm(t('livelink.dtcs.confirmClear', { code }))) {
      return
    }

    try {
      await livelinkService.clearVehicleDTC(vin, dtcId)
      toast.success(t('livelink.dtcs.markedCleared', { code }))
      fetchDTCs()
    } catch (err) {
      console.error('Failed to clear DTC:', err)
      toast.error(t('livelink.dtcs.clearError'))
    }
  }

  const handleSaveNotes = async (dtc: VehicleDTC) => {
    try {
      await livelinkService.updateVehicleDTC(vin, dtc.id, { user_notes: notesValue || null })
      toast.success(t('livelink.dtcs.notesSaved'))
      setEditingNotes(null)
      fetchDTCs()
    } catch (err) {
      console.error('Failed to save notes:', err)
      toast.error(t('livelink.dtcs.notesSaveError'))
    }
  }

  const getSeverityIcon = (severity: string) => {
    switch (severity) {
      case 'critical':
        return <AlertTriangle aria-hidden="true" className="w-5 h-5 text-danger" />
      case 'warning':
        return <AlertCircle aria-hidden="true" className="w-5 h-5 text-warning" />
      default:
        return <Info aria-hidden="true" className="w-5 h-5 text-info" />
    }
  }

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'critical':
        return 'border-danger/30 bg-danger/10'
      case 'warning':
        return 'border-warning/30 bg-warning/10'
      default:
        return 'border-info/30 bg-info/10'
    }
  }

  const filterLabels: Record<FilterType, string> = {
    all: t('livelinkDtcs.filterAll'),
    active: t('livelinkDtcs.filterActive'),
    cleared: t('livelinkDtcs.filterCleared'),
  }

  const filteredDTCs = dtcs?.dtcs.filter((dtc) => {
    if (filter === 'all') return true
    if (filter === 'active') return dtc.is_active
    if (filter === 'cleared') return !dtc.is_active
    return true
  })

  const openExternalSearch = (dtc: VehicleDTC) => {
    const query = encodeURIComponent(`${dtc.code} ${dtc.description || ''}`)
    window.open(`https://www.google.com/search?q=${query}`, '_blank')
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <RefreshCw aria-hidden="true" className="w-8 h-8 text-text-mute animate-spin" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Filter Tabs and Summary */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div className="flex gap-2">
          {(['active', 'cleared', 'all'] as const).map((f) => (
            <Chip key={f} onClick={() => setFilter(f)} selected={filter === f}>
              {filterLabels[f]}
              {f === 'active' && dtcs && (
                <span className="ml-1 rounded bg-(--accent-soft) px-1.5 py-0.5 text-[10px]">{dtcs.active_count}</span>
              )}
            </Chip>
          ))}
        </div>

        {dtcs && dtcs.critical_count > 0 && (
          <Chip tone="danger" icon={AlertTriangle}>
            {t('livelink.dtcs.criticalCount', { count: dtcs.critical_count })}
          </Chip>
        )}
      </div>

      {/* DTC List */}
      {filteredDTCs && filteredDTCs.length > 0 ? (
        <div className="space-y-4">
          {filteredDTCs.map((dtc) => (
            <div
              key={dtc.id}
              className={`rounded-card border p-4 ${
                dtc.is_active ? getSeverityColor(dtc.severity) : 'border-border bg-surface opacity-75'
              }`}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-start gap-3">
                  {getSeverityIcon(dtc.severity)}
                  <div>
                    <div className="flex items-center gap-2">
                      <Mono weight="bold">{dtc.code}</Mono>
                      {!dtc.is_active && (
                        <Chip tone="success" icon={CheckCircle}>{t('livelink.dtcs.cleared')}</Chip>
                      )}
                      {dtc.is_emissions_related && (
                        <Chip tone="warning">{t('livelink.dtcs.emissions')}</Chip>
                      )}
                    </div>
                    <p className="text-text mt-1">{dtc.description || t('livelink.dtcs.unknownCode')}</p>
                    <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-xs text-text-mute">
                      <span>
                        {t('livelink.dtcs.firstSeen')}:{' '}
                        <Mono size="xs">{formatAPITimestamp(dtc.first_seen, (d) => d.toLocaleDateString())}</Mono>
                      </span>
                      <span>
                        {t('livelink.dtcs.lastSeen')}:{' '}
                        <Mono size="xs">{formatAPITimestamp(dtc.last_seen, (d) => d.toLocaleDateString())}</Mono>
                      </span>
                      {dtc.cleared_at && (
                        <span>
                          {t('livelink.dtcs.clearedAt')}:{' '}
                          <Mono size="xs">{formatAPITimestamp(dtc.cleared_at, (d) => d.toLocaleDateString())}</Mono>
                        </span>
                      )}
                      {dtc.category && <span>{t('livelink.dtcs.category')}: {dtc.category}</span>}
                    </div>
                    {(dtc.common_causes?.length || dtc.symptoms?.length || dtc.fix_guidance) && (
                      <div className="mt-3 space-y-2 text-sm">
                        {dtc.common_causes && dtc.common_causes.length > 0 && (
                          <div>
                            <p className="text-xs font-medium text-text-mute uppercase tracking-wide">
                              {t('livelink.dtcs.commonCauses')}
                            </p>
                            <ul className="mt-1 list-disc list-inside text-text-mid space-y-0.5">
                              {dtc.common_causes.map((cause) => (
                                <li key={cause}>{cause}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {dtc.symptoms && dtc.symptoms.length > 0 && (
                          <div>
                            <p className="text-xs font-medium text-text-mute uppercase tracking-wide">
                              {t('livelink.dtcs.symptoms')}
                            </p>
                            <ul className="mt-1 list-disc list-inside text-text-mid space-y-0.5">
                              {dtc.symptoms.map((symptom) => (
                                <li key={symptom}>{symptom}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {dtc.fix_guidance && (
                          <div>
                            <p className="text-xs font-medium text-text-mute uppercase tracking-wide">
                              {t('livelink.dtcs.fixGuidance')}
                            </p>
                            <p className="mt-1 text-text-mid">{dtc.fix_guidance}</p>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <IconButton icon={Search} label={t('livelink.dtcs.searchOnline')} onClick={() => openExternalSearch(dtc)} />
                  {dtc.is_active && (
                    <IconButton
                      icon={CheckCircle}
                      label={t('livelink.dtcs.markAsCleared')}
                      onClick={() => handleClearDTC(dtc.id, dtc.code)}
                    />
                  )}
                </div>
              </div>

              {/* User Notes */}
              <div className="mt-3 pt-3 border-t border-border">
                {editingNotes === dtc.id ? (
                  <div className="flex gap-2">
                    <Input
                      type="text"
                      value={notesValue}
                      onChange={(e) => setNotesValue(e.target.value)}
                      placeholder={t('livelink.dtcs.addNotesPlaceholder')}
                      autoFocus
                      className="flex-1"
                    />
                    <Button size="sm" onClick={() => handleSaveNotes(dtc)}>{t('livelinkDtcs.saveNotes')}</Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditingNotes(null)}>
                      {t('livelinkDtcs.cancelNotes')}
                    </Button>
                  </div>
                ) : (
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={FileText}
                    onClick={() => {
                      setNotesValue(dtc.user_notes || '')
                      setEditingNotes(dtc.id)
                    }}
                  >
                    {dtc.user_notes || t('livelink.dtcs.addNotesPlaceholder')}
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState
          icon={CheckCircle}
          title={
            filter === 'active'
              ? t('livelink.dtcs.noActive')
              : filter === 'cleared'
                ? t('livelink.dtcs.noCleared')
                : t('livelink.dtcs.noRecorded')
          }
          description={t('livelink.dtcs.willAppear')}
        />
      )}

      {/* External Search Link */}
      <Card padding="sm">
        <div className="flex items-center gap-3">
          <ExternalLink aria-hidden="true" className="w-5 h-5 text-text-mute" />
          <div>
            <p className="text-sm text-text font-medium">{t('livelink.dtcs.needMoreInfo')}</p>
            <p className="text-xs text-text-mute">{t('livelink.dtcs.searchHint')}</p>
          </div>
        </div>
      </Card>
    </div>
  )
}
