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
        return <AlertTriangle className="w-5 h-5 text-red-500" />
      case 'warning':
        return <AlertCircle className="w-5 h-5 text-yellow-500" />
      default:
        return <Info className="w-5 h-5 text-blue-500" />
    }
  }

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'critical':
        return 'border-red-500/30 bg-red-500/10'
      case 'warning':
        return 'border-yellow-500/30 bg-yellow-500/10'
      default:
        return 'border-blue-500/30 bg-blue-500/10'
    }
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
        <RefreshCw className="w-8 h-8 text-primary animate-spin" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Filter Tabs and Summary */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div className="flex gap-2">
          {(['active', 'cleared', 'all'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                filter === f
                  ? 'bg-primary text-white'
                  : 'bg-garage-surface text-garage-text-muted hover:text-garage-text border border-garage-border'
              }`}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
              {f === 'active' && dtcs && (
                <span className="ml-2 px-1.5 py-0.5 bg-white/20 rounded text-xs">
                  {dtcs.active_count}
                </span>
              )}
            </button>
          ))}
        </div>

        {dtcs && dtcs.critical_count > 0 && (
          <div className="flex items-center gap-2 text-red-500">
            <AlertTriangle className="w-4 h-4" />
            <span className="text-sm font-medium">{t('livelink.dtcs.criticalCount', { count: dtcs.critical_count })}</span>
          </div>
        )}
      </div>

      {/* DTC List */}
      {filteredDTCs && filteredDTCs.length > 0 ? (
        <div className="space-y-4">
          {filteredDTCs.map((dtc) => (
            <div
              key={dtc.id}
              className={`rounded-lg border p-4 ${
                dtc.is_active ? getSeverityColor(dtc.severity) : 'border-garage-border bg-garage-surface opacity-75'
              }`}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-start gap-3">
                  {getSeverityIcon(dtc.severity)}
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold text-garage-text">{dtc.code}</span>
                      {!dtc.is_active && (
                        <span className="flex items-center gap-1 text-xs text-green-500">
                          <CheckCircle className="w-3 h-3" />{t('livelink.dtcs.cleared')}</span>
                      )}
                      {dtc.is_emissions_related && (
                        <span className="px-1.5 py-0.5 bg-yellow-500/20 text-yellow-500 text-xs rounded">{t('livelink.dtcs.emissions')}</span>
                      )}
                    </div>
                    <p className="text-garage-text mt-1">
                      {dtc.description || t('livelink.dtcs.unknownCode')}
                    </p>
                    <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-xs text-garage-text-muted">
                      <span>{t('livelink.dtcs.firstSeen')}: {new Date(dtc.first_seen).toLocaleDateString()}</span>
                      <span>{t('livelink.dtcs.lastSeen')}: {new Date(dtc.last_seen).toLocaleDateString()}</span>
                      {dtc.cleared_at && (
                        <span>{t('livelink.dtcs.clearedAt')}: {new Date(dtc.cleared_at).toLocaleDateString()}</span>
                      )}
                      {dtc.category && <span>{t('livelink.dtcs.category')}: {dtc.category}</span>}
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => openExternalSearch(dtc)}
                    className="p-2 text-garage-text-muted hover:text-primary transition-colors"
                    title={t('livelink.dtcs.searchOnline')}
                  >
                    <Search className="w-4 h-4" />
                  </button>
                  {dtc.is_active && (
                    <button
                      onClick={() => handleClearDTC(dtc.id, dtc.code)}
                      className="p-2 text-garage-text-muted hover:text-green-500 transition-colors"
                      title={t('livelink.dtcs.markAsCleared')}
                    >
                      <CheckCircle className="w-4 h-4" />
                    </button>
                  )}
                </div>
              </div>

              {/* User Notes */}
              <div className="mt-3 pt-3 border-t border-garage-border/50">
                {editingNotes === dtc.id ? (
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={notesValue}
                      onChange={(e) => setNotesValue(e.target.value)}
                      placeholder={t('livelink.dtcs.addNotesPlaceholder')}
                      className="flex-1 px-3 py-1.5 bg-garage-bg border border-garage-border rounded text-sm text-garage-text"
                      autoFocus
                    />
                    <button
                      onClick={() => handleSaveNotes(dtc)}
                      className="px-3 py-1.5 bg-primary text-white rounded text-sm"
                    >
                      Save
                    </button>
                    <button
                      onClick={() => setEditingNotes(null)}
                      className="px-3 py-1.5 text-garage-text-muted hover:text-garage-text rounded text-sm"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => {
                      setNotesValue(dtc.user_notes || '')
                      setEditingNotes(dtc.id)
                    }}
                    className="flex items-center gap-2 text-sm text-garage-text-muted hover:text-garage-text"
                  >
                    <FileText className="w-4 h-4" />
                    {dtc.user_notes || t('livelink.dtcs.addNotesPlaceholder')}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="bg-garage-surface rounded-lg border border-garage-border p-8 text-center">
          <CheckCircle className="w-12 h-12 mx-auto mb-3 text-green-500 opacity-50" />
          <p className="text-garage-text">
            {filter === 'active'
              ? t('livelink.dtcs.noActive')
              : filter === 'cleared'
              ? t('livelink.dtcs.noCleared')
              : t('livelink.dtcs.noRecorded')}
          </p>
          <p className="text-sm text-garage-text-muted mt-2">
            {t('livelink.dtcs.willAppear')}
          </p>
        </div>
      )}

      {/* External Search Link */}
      <div className="bg-garage-surface rounded-lg border border-garage-border p-4">
        <div className="flex items-center gap-3">
          <ExternalLink className="w-5 h-5 text-primary" />
          <div>
            <p className="text-sm text-garage-text font-medium">{t('livelink.dtcs.needMoreInfo')}</p>
            <p className="text-xs text-garage-text-muted">
              {t('livelink.dtcs.searchHint')}
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
