import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Edit, Trash2, Plus, AlertCircle, Fuel, Droplets } from 'lucide-react'
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

interface PropaneRecordListProps {
  vin: string
}

export default function PropaneRecordList({ vin }: PropaneRecordListProps) {
  const [showForm, setShowForm] = useState(false)
  const [editingRecord, setEditingRecord] = useState<FuelRecord | undefined>()
  const { t } = useTranslation('vehicles')
  const { system } = useUnitPreference()
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
        toast.error(err instanceof Error ? err.message : t('propaneList.deleteError'))
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
    return UnitFormatter.formatVolume(num, system, false)
  }

  const extractVendor = (notes?: string): string => {
    if (!notes) return '-'
    const match = notes.match(/^Vendor: (.+?)(?:\n|$)/)
    return match ? match[1] : '-'
  }

  if (isLoading) {
    return (
      <div className="text-center py-8 text-garage-text-muted">{t('propaneList.loading')}</div>
    )
  }

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
          <h3 className="text-lg font-semibold text-garage-text">{t('propaneList.title')}</h3>
          {records.length > 0 && (
            <p className="text-sm text-garage-text-muted">
              {t('propaneList.recordCount', { count: records.length })}
            </p>
          )}
        </div>
        <button
          onClick={handleAdd}
          className="flex items-center gap-2 px-4 py-2 bg-gray-700 border border-gray-600 text-white rounded-lg hover:bg-gray-800 transition-colors"
        >
          <Plus className="w-4 h-4" />
          <span>{t('propaneList.addPropane')}</span>
        </button>
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
            <div className="bg-garage-surface border border-garage-border rounded-lg p-3">
              <div className="flex items-center gap-1 text-xs text-garage-text-muted mb-1">
                <span>{t('propaneList.totalSpent')}</span>
              </div>
              <div className="text-lg font-semibold text-garage-text">
                {formatCurrency(totalCost, { currencyCode, locale })}
              </div>
            </div>
            <div className="bg-garage-surface border border-garage-border rounded-lg p-3">
              <div className="flex items-center gap-1 text-xs text-garage-text-muted mb-1">
                <Droplets className="w-3 h-3" />
                <span>{system === 'metric' ? t('propaneList.totalLiters') : t('propaneList.totalGallons')}</span>
              </div>
              <div className="text-lg font-semibold text-garage-text">
                {UnitFormatter.formatVolumeTotal(totalLiters, system).replace(' total', '')}
              </div>
            </div>
            {avgCostPerLiter !== null && (
              <div className="bg-garage-surface border border-garage-border rounded-lg p-3">
                <div className="flex items-center gap-1 text-xs text-garage-text-muted mb-1">
                  <span>{UnitFormatter.getCostPerVolumeLabel(system)}</span>
                </div>
                <div className="text-lg font-semibold text-garage-text">
                  {avgCostPerLiter !== null && UnitFormatter.formatCostPerVolume(avgCostPerLiter, system, currencyCode, locale)}
                </div>
              </div>
            )}
          </div>
        )
      })()}

      {error && (
        <div className="flex items-start gap-2 p-3 bg-danger/10 border border-danger/20 rounded-md mb-4">
          <AlertCircle className="w-4 h-4 text-danger flex-shrink-0 mt-0.5" />
          <p className="text-sm text-danger">{error.message}</p>
        </div>
      )}

      {records.length === 0 ? (
        <div className="text-center py-12 bg-garage-surface border border-garage-border rounded-lg">
          <Fuel className="w-12 h-12 text-garage-text-muted mx-auto mb-3" />
          <p className="text-garage-text mb-2">{t('propaneList.noRecords')}</p>
          <p className="text-sm text-garage-text-muted mb-4">{t('propaneList.noRecordsDesc')}</p>
          <button
            onClick={handleAdd}
            className="inline-flex items-center gap-2 px-4 py-2 bg-gray-700 border border-gray-600 text-white rounded-lg hover:bg-gray-800 transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>{t('propaneList.addFirstRecord')}</span>
          </button>
        </div>
      ) : (
        <div className="bg-garage-surface border border-garage-border rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-garage-bg border-b border-garage-border">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase">{t('propaneList.date')}</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-garage-text-muted uppercase">{t('propaneList.gallons')}</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-garage-text-muted uppercase">{t('propaneList.pricePerUnit')}</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-garage-text-muted uppercase">{t('propaneList.cost')}</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase">{t('propaneList.vendor')}</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-garage-text-muted uppercase">{t('propaneList.actions')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-garage-border">
                {records.map((record) => (
                  <tr key={record.id} className="hover:bg-garage-bg transition-colors">
                    <td className="px-4 py-3 text-sm text-garage-text">
                      {formatDateForDisplay(record.date)}
                    </td>
                    <td className="px-4 py-3 text-sm text-garage-text text-right font-medium">
                      {formatVolume(record.propane_liters ?? undefined)}
                    </td>
                    <td className="px-4 py-3 text-sm text-garage-text text-right">
                      {record.price_per_unit
                        ? formatCurrency(
                            priceToDisplay(record.price_per_unit, system, record.price_basis ?? 'per_volume') ?? 0,
                            { currencyCode, locale },
                          )
                        : '-'}
                    </td>
                    <td className="px-4 py-3 text-sm text-garage-text text-right font-semibold">
                      {formatCurrency(record.cost, { currencyCode, locale })}
                    </td>
                    <td className="px-4 py-3 text-sm text-garage-text-muted">
                      {extractVendor(record.notes ?? undefined)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex gap-1 justify-end">
                        <button
                          onClick={() => handleEdit(record)}
                          className="p-1.5 text-primary hover:bg-primary/10 rounded transition-colors"
                          aria-label={t('common:edit')}
                          title={t('common:edit')}
                        >
                          <Edit className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleDelete(record.id)}
                          disabled={deleteMutation.isPending && deleteMutation.variables === record.id}
                          className="p-1.5 text-danger hover:bg-danger/10 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                          aria-label={t('common:delete')}
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
