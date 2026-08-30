import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Edit, Trash2, Plus, AlertCircle, Droplets, TrendingDown } from 'lucide-react'
import { toast } from 'sonner'
import { formatDateForDisplay } from '../utils/dateUtils'
import { formatCurrency } from '../utils/formatUtils'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'
import type { DEFRecord } from '../types/def'
import DEFRecordForm from './DEFRecordForm'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { useUnitFormat } from '../hooks/useUnitFormat'
import { formatVolumePerDistance, volumePerDistanceLabel } from '../utils/unitFormat'
import { UnitFormatter } from '../utils/units'
import { useDEFRecords, useDEFAnalytics, useDeleteDEFRecord } from '../hooks/queries/useDEFRecords'
import { useQueryClient } from '@tanstack/react-query'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { Button, IconButton, Card, Mono, Chip, DataTable, EmptyState } from './ui'
import type { DataTableColumn } from './ui'

interface DEFRecordListProps {
  vin: string
  /** True when the vehicle isn't diesel — hides add/edit affordances and
   * shows a read-only notice. Delete stays available so bad legacy data can
   * still be removed. */
  readOnly?: boolean
}

export default function DEFRecordList({ vin, readOnly = false }: DEFRecordListProps) {
  const [showForm, setShowForm] = useState(false)
  const [editingRecord, setEditingRecord] = useState<DEFRecord | undefined>()
  const { t } = useTranslation('vehicles')
  const { showBoth, units } = useUnitPreference()
  const u = useUnitFormat()
  const { currencyCode, locale } = useCurrencyPreference()

  const { data: recordsData, isLoading, error } = useDEFRecords(vin)
  const { data: analytics } = useDEFAnalytics(vin)
  const deleteMutation = useDeleteDEFRecord(vin)
  const queryClient = useQueryClient()

  const records = useMemo(() => recordsData?.records ?? [], [recordsData?.records])

  const handleAdd = () => {
    if (readOnly) return
    setEditingRecord(undefined)
    setShowForm(true)
  }

  const handleEdit = (record: DEFRecord) => {
    if (readOnly) return
    setEditingRecord(record)
    setShowForm(true)
  }

  const handleDelete = (id: number) => {
    if (!confirm(t('defList.confirmDelete'))) {
      return
    }

    deleteMutation.mutate(id, {
      onSuccess: () => {
        toast.success(t('defList.deleted'))
      },
      onError: (err) => {
        toast.error(getActionErrorMessage(err, t('defList.deleteAction')))
      },
    })
  }

  const handleSuccess = () => {
    queryClient.invalidateQueries({ queryKey: ['defRecords', vin] })
    queryClient.invalidateQueries({ queryKey: ['defAnalytics', vin] })
    setShowForm(false)
  }

  const parseNum = (val?: number | string | null): number | null => {
    if (val === undefined || val === null) return null
    const num = typeof val === 'string' ? parseFloat(val) : val
    return isNaN(num) ? null : num
  }

  const formatVolume = (liters?: number | string | null): string => {
    const num = parseNum(liters)
    if (num === null) return '-'
    return UnitFormatter.formatVolume(num, units, showBoth)
  }

  const formatFillLevel = (level?: number | string | null): string => {
    const num = parseNum(level)
    if (num === null) return '-'
    return `${Math.round(num * 100)}%`
  }

  const fillLevelColor = (level: number): string => {
    const pct = level * 100
    if (pct > 50) return 'bg-success'
    if (pct > 25) return 'bg-warning'
    return 'bg-danger'
  }

  const remainingTone = (km: number): 'success' | 'warning' | 'danger' =>
    km > 2000 ? 'success' : km > 1000 ? 'warning' : 'danger'

  const columns: DataTableColumn<DEFRecord>[] = [
    { id: 'date', header: t('defList.date'), mono: true, render: (r) => formatDateForDisplay(r.date) },
    { id: 'type', header: t('defList.type'), align: 'left',
      render: (r) => r.entry_type === 'auto_fuel_sync'
        ? <Chip tone="info">{t('defList.auto')}</Chip>
        : <Chip tone="success">{t('defList.purchase')}</Chip> },
    { id: 'mileage', header: t('defList.mileage'), align: 'right', mono: true,
      render: (r) => r.odometer_km != null ? u.distance.format(parseFloat(String(r.odometer_km))) : '-' },
    // B7: unit-aware header — formatVolume yields liters in metric, so the old static
    // `defList.gallons` ("Gallons") lied to metric users. `volumeUnit` interpolates the system unit.
    { id: 'gallons', header: t('defList.volumeUnit', { unit: UnitFormatter.getVolumeUnit(units) }), align: 'right', mono: true, render: (r) => formatVolume(r.liters) },
    { id: 'fillLevel', header: t('defList.fillLevel'), align: 'left',
      render: (r) => {
        const fillLevel = parseNum(r.fill_level)
        return fillLevel !== null ? (
          <div className="flex items-center gap-2">
            <div className="w-16 h-2 rounded-full bg-surface-2 overflow-hidden">
              <div className={`h-full rounded-full ${fillLevelColor(fillLevel)}`} style={{ width: `${fillLevel * 100}%` }} />
            </div>
            <Mono size="sm" tone="muted">{formatFillLevel(r.fill_level)}</Mono>
          </div>
        ) : '-'
      } },
    { id: 'source', header: t('defList.source'), align: 'left', render: (r) => r.entry_type === 'auto_fuel_sync' ? '—' : (r.source || '-') },
    { id: 'brand', header: t('defList.brand'), align: 'left', render: (r) => r.entry_type === 'auto_fuel_sync' ? '—' : (r.brand || '-') },
    { id: 'cost', header: t('defList.cost'), align: 'right', mono: true, render: (r) => formatCurrency(r.cost, { currencyCode, locale }) },
    { id: 'actions', header: t('defList.actions'), align: 'right',
      render: (r) => (
        <div className="flex justify-end gap-1">
          {!readOnly && (
            <IconButton icon={Edit} label={t('common:edit')} variant="ghost" size="sm" onClick={() => handleEdit(r)} />
          )}
          <IconButton
            icon={Trash2}
            label={t('common:delete')}
            variant="danger"
            size="sm"
            disabled={deleteMutation.isPending && deleteMutation.variables === r.id}
            onClick={() => handleDelete(r.id)}
          />
        </div>
      ) },
  ]

  if (isLoading) {
    return <div className="text-center py-8 text-text-mute">{t('defList.loading')}</div>
  }

  return (
    <div>
      {showForm && (
        <DEFRecordForm
          vin={vin}
          record={editingRecord}
          onClose={() => setShowForm(false)}
          onSuccess={handleSuccess}
        />
      )}

      {readOnly && (
        <div className="flex items-start gap-2 p-3 bg-warning/10 border border-warning/20 rounded-md mb-4">
          <AlertCircle aria-hidden="true" className="w-4 h-4 text-warning flex-shrink-0 mt-0.5" />
          <p className="text-sm text-warning">{t('defList.readOnlyNotice')}</p>
        </div>
      )}

      {/* Analytics Cards */}
      {analytics && analytics.record_count > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3 mb-4">
          {analytics.estimated_km_remaining !== null && (
            <Card padding="sm">
              <div className="flex items-center gap-1 text-xs text-text-mute mb-1">
                <TrendingDown aria-hidden="true" className="w-3 h-3" />
                <span>Est. {u.distance.label} Left</span>
              </div>
              <Mono size="2xl" weight="bold" tone={remainingTone(parseNum(analytics.estimated_km_remaining) ?? 0)}>
                {u.distance.toDisplayText(parseNum(analytics.estimated_km_remaining) ?? 0)}
              </Mono>
              {analytics.estimated_days_remaining !== null && (
                <p className="text-xs text-text-mute">{t('defList.estimatedDays', { count: analytics.estimated_days_remaining })}</p>
              )}
            </Card>
          )}

          {analytics.liters_per_1000_km !== null && (
            <Card padding="sm">
              <div className="flex items-center gap-1 text-xs text-text-mute mb-1">
                <Droplets aria-hidden="true" className="w-3 h-3" />
                <span>{t('defList.consumption')}</span>
              </div>
              <Mono size="2xl" weight="bold">{formatVolumePerDistance(units, parseNum(analytics.liters_per_1000_km) ?? 0)}</Mono>
              <p className="text-xs text-text-mute">{volumePerDistanceLabel(units)}</p>
            </Card>
          )}

          {analytics.avg_cost_per_liter !== null && (
            <Card padding="sm">
              <div className="flex items-center gap-1 text-xs text-text-mute mb-1">
                <span>{t('defList.avgCostPerVolume', { unit: UnitFormatter.getVolumeUnit(units) })}</span>
              </div>
              <Mono size="2xl" weight="bold">{UnitFormatter.formatCostPerVolume(parseNum(analytics.avg_cost_per_liter) ?? 0, units, currencyCode, locale)}</Mono>
            </Card>
          )}

          {analytics.total_cost !== null && (
            <Card padding="sm">
              <div className="flex items-center gap-1 text-xs text-text-mute mb-1">
                <span>{t('defList.totalSpent')}</span>
              </div>
              <Mono size="2xl" weight="bold">{formatCurrency(analytics.total_cost, { currencyCode, locale })}</Mono>
              <Mono size="sm" tone="muted" className="mt-1 block">{t('defList.volumeTotal', { value: UnitFormatter.formatVolumeShort(parseNum(analytics.total_liters) ?? 0, units) })}</Mono>
            </Card>
          )}

          {analytics.data_confidence !== 'high' && (
            <Card padding="sm">
              <div className="flex items-center gap-1 text-xs text-text-mute mb-1">
                <AlertCircle aria-hidden="true" className="w-3 h-3" />
                <span>{t('defList.dataQuality')}</span>
              </div>
              <div className="text-sm font-medium text-warning">
                {analytics.data_confidence === 'low' ? t('defList.estimates') : t('defList.needMoreData')}
              </div>
              <p className="text-xs text-text-mute">{t('defList.recordCount', { count: analytics.record_count })}</p>
            </Card>
          )}
        </div>
      )}

      <div className="flex justify-between items-center mb-4">
        <div>
          <h3 className="text-lg font-semibold text-text">{t('defList.title')}</h3>
          {records.length > 0 && (
            <p className="text-sm text-text-mute">{t('defList.recordCount', { count: records.length })}</p>
          )}
        </div>
        {!readOnly && (
          <Button variant="primary" icon={Plus} onClick={handleAdd}>{t('defList.addDEF')}</Button>
        )}
      </div>

      {error && (
        <div className="flex items-start gap-2 p-3 bg-danger/10 border border-danger/20 rounded-md mb-4">
          <AlertCircle aria-hidden="true" className="w-4 h-4 text-danger flex-shrink-0 mt-0.5" />
          <p className="text-sm text-danger">{getActionErrorMessage(error, t('defList.loadAction'))}</p>
        </div>
      )}

      {records.length === 0 ? (
        <EmptyState
          icon={Droplets}
          title={t('defList.noRecords')}
          description={t('defList.noRecordsDesc')}
          action={!readOnly ? <Button variant="primary" icon={Plus} onClick={handleAdd}>{t('defList.addFirstRecord')}</Button> : undefined}
        />
      ) : (
        <Card padding="none">
          <DataTable caption={t('defList.tableCaption')} columns={columns} rows={records} rowKey={(r) => String(r.id)} />
        </Card>
      )}
    </div>
  )
}
