import { useState, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { formatDateForDisplay } from '../utils/dateUtils'
import { Gauge, Plus, Edit, Trash2, Download, Upload, Radio } from 'lucide-react'
import { toast } from 'sonner'
import type { OdometerRecord } from '../types/odometer'
import api from '../services/api'
import { useUnitFormat } from '../hooks/useUnitFormat'
import { useOdometerRecords, useDeleteOdometerRecord, useImportOdometerCSV } from '../hooks/queries/useOdometerRecords'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { Button, IconButton, Card, Mono, Badge, DataTable, EmptyState } from './ui'
import type { DataTableColumn } from './ui'

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
  const u = useUnitFormat()

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
      // Export in the units the user actually reads. Storage is
      // metric-canonical, so without this an imperial account got a
      // metric file (#128). The backend stamps a `unit_system` column
      // so re-importing converts back correctly.
      //
      // `units` is deliberately NOT sent. It used to carry `system`, the
      // binary metric/imperial collapse of the account's volume unit, which
      // meant an account with mixed preferences (km with UK gallons, say)
      // asked for a clean preset and never received its own units. Omitting
      // the parameter tells the backend to export in the caller's resolved
      // unit set, which CSV schema v6 spells out per column
      // (`Odometer (km)`, `Volume (gal_uk)`).
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
      toast.error(getActionErrorMessage(err, t('odometerList.exportAction')))
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
        // Show results. Each clause is its own key so translators can inflect
        // the counts independently.
        const parts = [t('odometerRecordList.importImported', { count: result.success_count })]
        if (result.skipped_count > 0) {
          parts.push(t('odometerRecordList.importSkipped', { count: result.skipped_count }))
        }
        if (result.error_count > 0) {
          parts.push(t('odometerRecordList.importErrored', { count: result.error_count }))
        }
        const message = t('odometerRecordList.importCompleted', { summary: parts.join(', ') })

        if (result.errors && result.errors.length > 0) {
          // Backend-supplied error strings are appended verbatim, never
          // routed through t().
          toast.error(`${message} - ${t('odometerRecordList.importErrorsLabel')}: ${result.errors.join(', ')}`)
        } else {
          toast.success(message)
        }
      },
      onError: (err) => {
        toast.error(getActionErrorMessage(err, t('odometerList.importAction')))
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
        toast.error(getActionErrorMessage(err, t('odometerList.deleteAction')))
      },
    })
  }

  const formatDate = (dateString: string) => {
    return formatDateForDisplay(dateString)
  }

  const columns: DataTableColumn<OdometerRecord>[] = [
    { id: 'date', header: t('odometerList.date'), mono: true, render: (r) => formatDate(r.date) },
    {
      id: 'mileage',
      header: t('odometerRecordList.mileageColumn', { unit: u.distance.label }),
      align: 'right',
      render: (r) => (
        <span className="inline-flex items-center justify-end gap-2">
          <Mono>{u.distance.format(parseFloat(String(r.odometer_km)))}</Mono>
          {(r as Record<string, unknown>).source === 'livelink' && (
            <Badge tone="info" icon={Radio}>
              <span className="sr-only">{t('odometerRecordList.autoTrackedByLiveLink')}</span>
            </Badge>
          )}
        </span>
      ),
    },
    { id: 'notes', header: t('odometerList.notes'), render: (r) => (r.notes ? r.notes : <span className="text-text-mute">-</span>) },
    {
      id: 'actions',
      header: t('odometerList.actions'),
      align: 'right',
      render: (r) => (
        <div className="flex justify-end gap-2">
          <IconButton icon={Edit} label={t('common:edit')} variant="ghost" size="sm" onClick={() => onEditClick(r)} />
          <IconButton
            icon={Trash2}
            label={t('common:delete')}
            variant="danger"
            size="sm"
            disabled={deleteMutation.isPending && deleteMutation.variables === r.id}
            onClick={() => handleDelete(r.id)}
          />
        </div>
      ),
    },
  ]

  if (isLoading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-text-mute">{t('odometerList.loading')}</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-danger/10 border border-danger rounded-lg p-4">
        <p className="text-danger">{getActionErrorMessage(error, t('odometerList.loadAction'))}</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-2">
          <Gauge aria-hidden="true" className="w-5 h-5 text-text-mute" />
          <h3 className="text-lg font-semibold text-text">{t('odometerList.title')}</h3>
          <span className="text-sm text-text-mute">({t('odometerList.recordCount', { count: records.length })})</span>
        </div>
        <div className="flex items-center gap-2">
          <input ref={fileInputRef} type="file" accept=".csv" onChange={handleImportCSV} className="hidden" />
          <Button variant="secondary" icon={Upload} onClick={handleImportClick} loading={importMutation.isPending} title={t('odometerList.importFromCSV')}>
            {importMutation.isPending ? t('odometerList.importing') : t('odometerList.importCSV')}
          </Button>
          {records.length > 0 && (
            <Button variant="secondary" icon={Download} onClick={handleExportCSV} loading={exporting} title={t('odometerList.exportToCSV')}>
              {exporting ? t('odometerList.exporting') : t('odometerList.exportCSV')}
            </Button>
          )}
          <Button variant="primary" icon={Plus} onClick={onAddClick}>{t('odometerList.addReading')}</Button>
        </div>
      </div>

      {latestOdometerKm !== null && (
        <Card padding="sm">
          <div className="flex items-center gap-3">
            <div className="rounded-full bg-(--accent-soft) p-3">
              <Gauge aria-hidden="true" className="w-6 h-6 text-(--accent-fg)" />
            </div>
            <div>
              <p className="text-sm text-text-mute">{t('odometerList.latestMileage')}</p>
              <Mono size="2xl" weight="bold">{u.distance.format(latestOdometerKm)}</Mono>
            </div>
          </div>
        </Card>
      )}

      {records.length === 0 ? (
        <EmptyState
          icon={Gauge}
          title={t('odometerList.noRecords')}
          description={t('odometerList.noRecordsDesc')}
          action={<Button variant="primary" icon={Plus} onClick={onAddClick}>{t('odometerList.addFirstReading')}</Button>}
        />
      ) : (
        <Card padding="none">
          <DataTable caption={t('odometerList.tableCaption')} columns={columns} rows={records} rowKey={(r) => String(r.id)} />
        </Card>
      )}
    </div>
  )
}
