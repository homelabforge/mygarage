import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Edit, Trash2, Plus, Fuel, Droplets } from 'lucide-react'
import { toast } from 'sonner'
import { formatDateForDisplay } from '../utils/dateUtils'
import { formatCurrency } from '../utils/formatUtils'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'
import type { FuelRecord } from '../types/fuel'
import PropaneRecordForm from './PropaneRecordForm'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitFormatter } from '../utils/units'
import { priceToDisplay } from '../utils/decimalSafe'
import { usePropaneRecords, useDeletePropaneRecord } from '../hooks/queries/usePropaneRecords'
import { useQueryClient } from '@tanstack/react-query'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { Button, IconButton, Card, Mono, DataTable, EmptyState } from './ui'
import type { DataTableColumn } from './ui'

interface PropaneRecordListProps {
  vin: string
}

export default function PropaneRecordList({ vin }: PropaneRecordListProps) {
  const [showForm, setShowForm] = useState(false)
  const [editingRecord, setEditingRecord] = useState<FuelRecord | undefined>()
  const { t } = useTranslation('vehicles')
  const { units } = useUnitPreference()
  const { currencyCode, locale } = useCurrencyPreference()

  const { data, isLoading, error } = usePropaneRecords(vin)
  const deleteMutation = useDeletePropaneRecord(vin)
  const queryClient = useQueryClient()

  const records = useMemo(() => data?.records ?? [], [data?.records])

  const handleAdd = () => {
    setEditingRecord(undefined)
    setShowForm(true)
  }

  const handleEdit = (record: FuelRecord) => {
    setEditingRecord(record)
    setShowForm(true)
  }

  const handleDelete = (id: number) => {
    if (!confirm(t('propaneList.confirmDelete'))) {
      return
    }

    deleteMutation.mutate(id, {
      onSuccess: () => {
        toast.success(t('propaneList.deleted'))
      },
      onError: (err) => {
        toast.error(getActionErrorMessage(err, t('propaneList.deleteAction')))
      },
    })
  }

  const handleSuccess = () => {
    queryClient.invalidateQueries({ queryKey: ['propaneRecords', vin] })
    queryClient.invalidateQueries({ queryKey: ['fuelRecords', vin] })
    setShowForm(false)
  }

  const formatVolume = (liters?: number | string): string => {
    if (!liters) return '-'
    const num = typeof liters === 'string' ? parseFloat(liters) : liters
    if (isNaN(num)) return '-'
    return UnitFormatter.formatVolume(num, units, false)
  }

  const extractVendor = (notes?: string): string => {
    if (!notes) return '-'
    const match = notes.match(/^Vendor: (.+?)(?:\n|$)/)
    return match ? match[1] : '-'
  }

  if (isLoading) {
    return <div className="text-center py-8 text-text-mute">{t('propaneList.loading')}</div>
  }

  const columns: DataTableColumn<FuelRecord>[] = [
    { id: 'date', header: t('propaneList.date'), mono: true, render: (r) => formatDateForDisplay(r.date) },
    // B7: unit-aware header — formatVolume yields liters in metric, so the old static
    // `propaneList.gallons` ("Gallons") lied to metric users. `volumeUnit` interpolates the system unit.
    { id: 'gallons', header: t('propaneList.volumeUnit', { unit: UnitFormatter.getVolumeUnit(units) }), align: 'right', mono: true, render: (r) => formatVolume(r.propane_liters ?? undefined) },
    { id: 'price', header: t('propaneList.pricePerUnit'), align: 'right', mono: true,
      render: (r) => r.price_per_unit
        ? formatCurrency(priceToDisplay(r.price_per_unit, units, r.price_basis ?? 'per_volume') ?? 0, { currencyCode, locale })
        : '-' },
    { id: 'cost', header: t('propaneList.cost'), align: 'right', mono: true, render: (r) => formatCurrency(r.cost, { currencyCode, locale }) },
    { id: 'vendor', header: t('propaneList.vendor'), align: 'left', render: (r) => extractVendor(r.notes ?? undefined) },
    { id: 'actions', header: t('propaneList.actions'), align: 'right',
      render: (r) => (
        <div className="flex justify-end gap-1">
          <IconButton icon={Edit} label={t('common:edit')} variant="ghost" size="sm" onClick={() => handleEdit(r)} />
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

  return (
    <div>
      {showForm && (
        <PropaneRecordForm
          vin={vin}
          record={editingRecord}
          onClose={() => setShowForm(false)}
          onSuccess={handleSuccess}
        />
      )}

      <div className="flex justify-between items-center mb-4">
        <div>
          <h3 className="text-lg font-semibold text-text">{t('propaneList.title')}</h3>
          {records.length > 0 && (
            <p className="text-sm text-text-mute">{t('propaneList.recordCount', { count: records.length })}</p>
          )}
        </div>
        <Button variant="primary" icon={Plus} onClick={handleAdd}>{t('propaneList.addPropane')}</Button>
      </div>

      {/* Inline Analytics Cards */}
      {records.length > 0 && (() => {
        const totalCost = records.reduce((sum, r) => {
          const cost = typeof r.cost === 'string' ? parseFloat(r.cost) : (r.cost || 0)
          return sum + (isNaN(cost) ? 0 : cost)
        }, 0)
        const totalLiters = records.reduce((sum, r) => {
          const l = typeof r.propane_liters === 'string' ? parseFloat(r.propane_liters) : (r.propane_liters || 0)
          return sum + (isNaN(l) ? 0 : l)
        }, 0)
        const avgCostPerLiter = totalLiters > 0 ? totalCost / totalLiters : null

        return (
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-4">
            <Card padding="sm">
              <div className="flex items-center gap-1 text-xs text-text-mute mb-1">
                <span>{t('propaneList.totalSpent')}</span>
              </div>
              <Mono size="2xl" weight="bold">{formatCurrency(totalCost, { currencyCode, locale })}</Mono>
            </Card>
            <Card padding="sm">
              <div className="flex items-center gap-1 text-xs text-text-mute mb-1">
                <Droplets aria-hidden="true" className="w-3 h-3" />
                <span>{t('propaneList.totalVolume', { unit: UnitFormatter.getVolumeUnit(units) })}</span>
              </div>
              <Mono size="2xl" weight="bold">{UnitFormatter.formatVolumeShort(totalLiters, units)}</Mono>
            </Card>
            {avgCostPerLiter !== null && (
              <Card padding="sm">
                <div className="flex items-center gap-1 text-xs text-text-mute mb-1">
                  <span>{t('propaneList.avgCostPerVolume', { unit: UnitFormatter.getVolumeUnit(units) })}</span>
                </div>
                <Mono size="2xl" weight="bold">{UnitFormatter.formatCostPerVolume(avgCostPerLiter, units, currencyCode, locale)}</Mono>
              </Card>
            )}
          </div>
        )
      })()}

      {error && (
        <div className="p-3 bg-danger/10 border border-danger/20 rounded-md mb-4">
          <p className="text-sm text-danger">{getActionErrorMessage(error, t('propaneList.loadAction'))}</p>
        </div>
      )}

      {records.length === 0 ? (
        <EmptyState
          icon={Fuel}
          title={t('propaneList.noRecords')}
          description={t('propaneList.noRecordsDesc')}
          action={<Button variant="primary" icon={Plus} onClick={handleAdd}>{t('propaneList.addFirstRecord')}</Button>}
        />
      ) : (
        <Card padding="none">
          <DataTable caption={t('propaneList.tableCaption')} columns={columns} rows={records} rowKey={(r) => String(r.id)} />
        </Card>
      )}
    </div>
  )
}
