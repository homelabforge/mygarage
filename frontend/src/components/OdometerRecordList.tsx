import { useState, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { formatDateForDisplay } from '../utils/dateUtils'
import { Gauge, Plus, Edit, Trash2, Calendar, Download, Upload, Radio } from 'lucide-react'
import { toast } from 'sonner'
import type { OdometerRecord } from '../types/odometer'
import api from '../services/api'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitFormatter } from '../utils/units'
import { useOdometerRecords, useDeleteOdometerRecord, useImportOdometerCSV } from '../hooks/queries/useOdometerRecords'

interface OdometerRecordListProps {
  vin: string
  onAddClick: () => void
  onEditClick: (record: OdometerRecord) => void
  onRefresh?: () => void
}

export default function OdometerRecordList({ vin, onAddClick, onEditClick }: OdometerRecordListProps) {
  const { t } = useTranslation('vehicles')
  const [exporting, setExporting] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const { system, showBoth } = useUnitPreference()

  const { data, isLoading, error } = useOdometerRecords(vin)
  const deleteMutation = useDeleteOdometerRecord(vin)
  const importMutation = useImportOdometerCSV(vin)

  const records = data?.records ?? []
  const latestOdometerKm = data?.latest_odometer_km != null
    ? (typeof data.latest_odometer_km === 'string' ? parseFloat(data.latest_odometer_km) : data.latest_odometer_km)
    : null

  const handleExportCSV = async () => {
    setExporting(true)
    try {
      const response = await api.get(`/export/vehicles/${vin}/odometer/csv`, {
        responseType: 'blob'
      })

      // Get the filename from Content-Disposition header
      const contentDisposition = response.headers['content-disposition']
      const filenameMatch = contentDisposition?.match(/filename="(.+)"/)
      const filename = filenameMatch ? filenameMatch[1] : 'odometer_records.csv'

      // Download the file
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
      toast.error(err instanceof Error ? err.message : t('odometerList.exportError'))
    } finally {
      setExporting(false)
    }
  }

  const handleImportClick = () => {
    fileInputRef.current?.click()
  }

  const handleImportCSV = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    const formData = new FormData()
    formData.append('file', file)
    formData.append('skip_duplicates', 'true')

    importMutation.mutate(formData, {
      onSuccess: (result) => {
        // Show results
        const message = `Import completed: ${result.success_count} records imported${result.skipped_count > 0 ? `, ${result.skipped_count} duplicates skipped` : ''}${result.error_count > 0 ? `, ${result.error_count} errors` : ''}`

        if (result.errors && result.errors.length > 0) {
          toast.error(message + ' - Errors: ' + result.errors.join(', '))
        } else {
          toast.success(message)
        }
      },
      onError: (err) => {
        toast.error(err instanceof Error ? err.message : t('odometerList.importError'))
      },
      onSettled: () => {
        // Reset file input
        if (fileInputRef.current) {
          fileInputRef.current.value = ''
        }
      },
    })
  }

  const handleDelete = (recordId: number) => {
    if (!confirm(t('odometerList.confirmDelete'))) {
      return
    }

    deleteMutation.mutate(recordId, {
      onError: (err) => {
        toast.error(err instanceof Error ? err.message : t('odometerList.deleteError'))
      },
    })
  }

  const formatDate = (dateString: string) => {
    return formatDateForDisplay(dateString)
  }

  if (isLoading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">{t('odometerList.loading')}</div>
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
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-2">
          <Gauge className="w-5 h-5 text-garage-text-muted" />
          <h3 className="text-lg font-semibold text-garage-text">{t('odometerList.title')}</h3>
          <span className="text-sm text-garage-text-muted">({t('odometerList.recordCount', { count: records.length })})</span>
        </div>
        <div className="flex items-center gap-2">
          {/* Import button */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            onChange={handleImportCSV}
            className="hidden"
          />
          <button
            onClick={handleImportClick}
            disabled={importMutation.isPending}
            className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50"
            title={t('odometerList.importFromCSV')}
          >
            <Upload className="w-4 h-4" />
            <span>{importMutation.isPending ? t('odometerList.importing') : t('odometerList.importCSV')}</span>
          </button>
          {/* Export button */}
          {records.length > 0 && (
            <button
              onClick={handleExportCSV}
              disabled={exporting}
              className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50"
              title={t('odometerList.exportToCSV')}
            >
              <Download className="w-4 h-4" />
              <span>{exporting ? t('odometerList.exporting') : t('odometerList.exportCSV')}</span>
            </button>
          )}
          <button
            onClick={onAddClick}
            className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>{t('odometerList.addReading')}</span>
          </button>
        </div>
      </div>

      {latestOdometerKm !== null && (
        <div className="bg-primary/10 border border-primary rounded-lg p-4">
          <div className="flex items-center gap-3">
            <div className="bg-primary/20 rounded-full p-3">
              <Gauge className="w-6 h-6 text-primary" />
            </div>
            <div>
              <p className="text-sm text-garage-text-muted">{t('odometerList.latestMileage')}</p>
              <p className="text-2xl font-bold text-garage-text">
                {UnitFormatter.formatDistance(latestOdometerKm, system, showBoth)}
              </p>
            </div>
          </div>
        </div>
      )}

      {records.length === 0 ? (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-8 text-center">
          <Gauge className="w-12 h-12 text-garage-text-muted opacity-50 mx-auto mb-3" />
          <p className="text-garage-text mb-2">{t('odometerList.noRecords')}</p>
          <p className="text-sm text-garage-text-muted mb-4">{t('odometerList.noRecordsDesc')}</p>
          <button
            onClick={onAddClick}
            className="inline-flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>{t('odometerList.addFirstReading')}</span>
          </button>
        </div>
      ) : (
        <div className="bg-garage-surface shadow rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-garage-border">
              <thead className="bg-garage-bg">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">{t('odometerList.date')}</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">
                    Mileage ({UnitFormatter.getDistanceUnit(system)})
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">{t('odometerList.notes')}</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-garage-text-muted uppercase tracking-wider">{t('odometerList.actions')}</th>
                </tr>
              </thead>
              <tbody className="bg-garage-surface divide-y divide-garage-border">
                {records.map((record) => (
                  <tr key={record.id} className="hover:bg-garage-bg">
                    <td className="px-4 py-3 whitespace-nowrap">
                      <div className="flex items-center gap-2 text-sm text-garage-text">
                        <Calendar className="w-4 h-4 text-garage-text-muted" />
                        {formatDate(record.date)}
                      </div>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <div className="flex items-center gap-2 text-sm font-medium text-garage-text">
                        <Gauge className="w-4 h-4 text-garage-text-muted" />
                        {UnitFormatter.formatDistance(parseFloat(String(record.odometer_km)), system, showBoth)}
                        {(record as Record<string, unknown>).source === 'livelink' && (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-primary/10 text-primary" title="Auto-tracked by LiveLink">
                            <Radio className="w-3 h-3" />
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      {record.notes ? (
                        <div className="text-sm text-garage-text">{record.notes}</div>
                      ) : (
                        <span className="text-sm text-garage-text-muted">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-right text-sm">
                      <div className="flex justify-end gap-2">
                        <button
                          onClick={() => onEditClick(record)}
                          className="text-primary hover:text-primary-dark"
                          title={t('common:edit')}
                        >
                          <Edit className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleDelete(record.id)}
                          disabled={deleteMutation.isPending && deleteMutation.variables === record.id}
                          className="text-danger hover:text-danger/80 disabled:opacity-50"
                          title={t('common:delete')}
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
        </div>
      )}
    </div>
  )
}
