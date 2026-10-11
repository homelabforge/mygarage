import { useTranslation } from 'react-i18next'
import { formatDateForDisplay } from '../utils/dateUtils'
import { formatHours } from '../utils/hoursFormat'
import { Clock, Plus, Edit, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import type { HoursRecord, HoursSource } from '../types/hours'
import { useHoursRecords, useDeleteHoursRecord } from '../hooks/queries/useHoursRecords'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { Button, IconButton, Card, Mono, DataTable, EmptyState } from './ui'
import type { DataTableColumn } from './ui'

interface HoursRecordListProps {
  vin: string
  onAddClick: () => void
  onEditClick: (record: HoursRecord) => void
}

/**
 * Engine-hours analog of OdometerRecordList. Engine hours are dimensionless
 * -- no UnitFormatter/UnitPreference conversion anywhere, unlike odometer_km
 * -- so values are formatted directly as "{n} hr" (same fixed, untranslated
 * unit symbol convention as FuelRecordForm/ServiceVisitList's engine_hours
 * fields). No CSV import/export -- out of scope for this task.
 */
export default function HoursRecordList({ vin, onAddClick, onEditClick }: HoursRecordListProps) {
  const { t } = useTranslation('vehicles')

  const { data, isLoading, error } = useHoursRecords(vin)
  const deleteMutation = useDeleteHoursRecord(vin)

  const records = data?.records ?? []
  const latestEngineHours = data?.latest_engine_hours != null
    ? (typeof data.latest_engine_hours === 'string' ? parseFloat(data.latest_engine_hours) : data.latest_engine_hours)
    : null

  const handleDelete = (recordId: number) => {
    if (!confirm(t('hoursList.confirmDelete'))) {
      return
    }

    deleteMutation.mutate(recordId, {
      onError: (err) => {
        toast.error(getActionErrorMessage(err, t('hoursList.deleteAction')))
      },
    })
  }

  const formatDate = (dateString: string) => {
    return formatDateForDisplay(dateString)
  }

  const sourceLabel = (source: string): string => {
    // Tire events publish under their own sources (#217).
    if (source.startsWith('tire')) return t('hoursList.sourceTire')
    switch (source as HoursSource) {
      case 'fuel':
        return t('hoursList.sourceFuel')
      case 'service_visit':
        return t('hoursList.sourceServiceVisit')
      case 'manual':
      default:
        return t('hoursList.sourceManual')
    }
  }

  const columns: DataTableColumn<HoursRecord>[] = [
    { id: 'date', header: t('hoursList.date'), mono: true, render: (r) => formatDate(r.date) },
    {
      id: 'engine_hours',
      header: t('common:engineHours'),
      align: 'right',
      render: (r) => <Mono>{formatHours(r.engine_hours)}</Mono>,
    },
    { id: 'notes', header: t('hoursList.notes'), render: (r) => (r.notes ? r.notes : <span className="text-text-mute">-</span>) },
    { id: 'source', header: t('hoursList.source'), render: (r) => sourceLabel(r.source) },
    {
      id: 'actions',
      header: t('hoursList.actions'),
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
        <div className="text-text-mute">{t('hoursList.loading')}</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-danger/10 border border-danger rounded-lg p-4">
        <p className="text-danger">{getActionErrorMessage(error, t('hoursList.loadAction'))}</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-2">
          <Clock aria-hidden="true" className="w-5 h-5 text-text-mute" />
          <h3 className="text-lg font-semibold text-text">{t('hoursList.title')}</h3>
          <span className="text-sm text-text-mute">({t('hoursList.recordCount', { count: records.length })})</span>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="primary" icon={Plus} onClick={onAddClick}>{t('hoursList.addReading')}</Button>
        </div>
      </div>

      {latestEngineHours !== null && (
        <Card padding="sm">
          <div className="flex items-center gap-3">
            <div className="rounded-full bg-(--accent-soft) p-3">
              <Clock aria-hidden="true" className="w-6 h-6 text-(--accent-fg)" />
            </div>
            <div>
              <p className="text-sm text-text-mute">{t('hoursList.latestReading')}</p>
              <Mono size="2xl" weight="bold">{formatHours(latestEngineHours)}</Mono>
            </div>
          </div>
        </Card>
      )}

      {records.length === 0 ? (
        <EmptyState
          icon={Clock}
          title={t('hoursList.noRecords')}
          description={t('hoursList.noRecordsDesc')}
          action={<Button variant="primary" icon={Plus} onClick={onAddClick}>{t('hoursList.addFirstReading')}</Button>}
        />
      ) : (
        <Card padding="none">
          <DataTable caption={t('hoursList.tableCaption')} columns={columns} rows={records} rowKey={(r) => String(r.id)} />
        </Card>
      )}
    </div>
  )
}
