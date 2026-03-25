import { useState, useMemo } from 'react'
import { Edit, Trash2, Plus, AlertCircle, Droplets, TrendingDown, DollarSign } from 'lucide-react'
import { toast } from 'sonner'
import { formatDateForDisplay } from '../utils/dateUtils'
import { formatCurrency } from '../utils/formatUtils'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'
import type { DEFRecord } from '../types/def'
import DEFRecordForm from './DEFRecordForm'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitConverter, UnitFormatter } from '../utils/units'
import { useDEFRecords, useDEFAnalytics, useDeleteDEFRecord } from '../hooks/queries/useDEFRecords'
import { useQueryClient } from '@tanstack/react-query'

interface DEFRecordListProps {
  vin: string
}

export default function DEFRecordList({ vin }: DEFRecordListProps) {
  const [showForm, setShowForm] = useState(false)
  const [editingRecord, setEditingRecord] = useState<DEFRecord | undefined>()
  const { system } = useUnitPreference()
  const { currencyCode, locale } = useCurrencyPreference()

  const { data: recordsData, isLoading, error } = useDEFRecords(vin)
  const { data: analytics } = useDEFAnalytics(vin)
  const deleteMutation = useDeleteDEFRecord(vin)
  const queryClient = useQueryClient()

  const records = useMemo(() => recordsData?.records ?? [], [recordsData?.records])

  const handleAdd = () => {
    setEditingRecord(undefined)
    setShowForm(true)
  }

  const handleEdit = (record: DEFRecord) => {
    setEditingRecord(record)
    setShowForm(true)
  }

  const handleDelete = (id: number) => {
    if (!confirm('Are you sure you want to delete this DEF record?')) {
      return
    }

    deleteMutation.mutate(id, {
      onSuccess: () => {
        toast.success('DEF record deleted')
      },
      onError: (err) => {
        toast.error(err instanceof Error ? err.message : 'Failed to delete DEF record')
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

  const formatVolume = (gallons?: number | string | null): string => {
    const num = parseNum(gallons)
    if (num === null) return '-'
    if (system === 'metric') {
      const liters = UnitConverter.gallonsToLiters(num)
      if (liters === null) return '-'
      return `${liters.toFixed(3)} ${UnitFormatter.getVolumeUnit(system)}`
    }
    return `${num.toFixed(3)} ${UnitFormatter.getVolumeUnit(system)}`
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

  const milesRemainingColor = (miles: number): string => {
    if (miles > 2000) return 'text-success'
    if (miles > 1000) return 'text-warning'
    return 'text-danger'
  }

  if (isLoading) {
    return (
      <div className="text-center py-8 text-garage-text-muted">
        Loading DEF records...
      </div>
    )
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

      {/* Analytics Cards */}
      {analytics && analytics.record_count > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3 mb-4">
          {/* Est Miles Remaining */}
          {analytics.estimated_miles_remaining !== null && (
            <div className="bg-garage-surface border border-garage-border rounded-lg p-3">
              <div className="flex items-center gap-1 text-xs text-garage-text-muted mb-1">
                <TrendingDown className="w-3 h-3" />
                <span>Est. {UnitFormatter.getDistanceUnit(system)} Left</span>
              </div>
              <div className={`text-lg font-semibold ${milesRemainingColor(analytics.estimated_miles_remaining ?? 0)}`}>
                {system === 'metric'
                  ? Math.round(UnitConverter.milesToKm(analytics.estimated_miles_remaining ?? 0) ?? 0).toLocaleString()
                  : (analytics.estimated_miles_remaining ?? 0).toLocaleString()}
              </div>
              {analytics.estimated_days_remaining !== null && (
                <p className="text-xs text-garage-text-muted">
                  ~{analytics.estimated_days_remaining} days
                </p>
              )}
            </div>
          )}

          {/* Consumption Rate */}
          {analytics.gallons_per_1000_miles !== null && (
            <div className="bg-garage-surface border border-garage-border rounded-lg p-3">
              <div className="flex items-center gap-1 text-xs text-garage-text-muted mb-1">
                <Droplets className="w-3 h-3" />
                <span>Consumption</span>
              </div>
              <div className="text-lg font-semibold text-garage-text">
                {analytics.gallons_per_1000_miles !== null &&
                  UnitFormatter.formatVolumePerDistance(parseNum(analytics.gallons_per_1000_miles) ?? 0, system)}
              </div>
              <p className="text-xs text-garage-text-muted">{UnitFormatter.getVolumePerDistanceLabel(system)}</p>
            </div>
          )}

          {/* Avg Cost/Gallon */}
          {analytics.avg_cost_per_gallon !== null && (
            <div className="bg-garage-surface border border-garage-border rounded-lg p-3">
              <div className="flex items-center gap-1 text-xs text-garage-text-muted mb-1">
                <DollarSign className="w-3 h-3" />
                <span>{UnitFormatter.getCostPerVolumeLabel(system)}</span>
              </div>
              <div className="text-lg font-semibold text-garage-text">
                {UnitFormatter.formatCostPerVolume(parseNum(analytics.avg_cost_per_gallon) ?? 0, system, currencyCode, locale)}
              </div>
            </div>
          )}

          {/* Total Spent */}
          {analytics.total_cost !== null && (
            <div className="bg-garage-surface border border-garage-border rounded-lg p-3">
              <div className="flex items-center gap-1 text-xs text-garage-text-muted mb-1">
                <DollarSign className="w-3 h-3" />
                <span>Total Spent</span>
              </div>
              <div className="text-lg font-semibold text-garage-text">
                {formatCurrency(analytics.total_cost, { currencyCode, locale })}
              </div>
              <p className="text-xs text-garage-text-muted">
                {UnitFormatter.formatVolumeTotal(parseNum(analytics.total_gallons) ?? 0, system)}
              </p>
            </div>
          )}

          {/* Confidence Indicator */}
          {analytics.data_confidence !== 'high' && (
            <div className="bg-garage-surface border border-garage-border rounded-lg p-3">
              <div className="flex items-center gap-1 text-xs text-garage-text-muted mb-1">
                <AlertCircle className="w-3 h-3" />
                <span>Data Quality</span>
              </div>
              <div className="text-sm font-medium text-warning">
                {analytics.data_confidence === 'low' ? 'Estimates' : 'Need More Data'}
              </div>
              <p className="text-xs text-garage-text-muted">
                {analytics.record_count} record{analytics.record_count !== 1 ? 's' : ''}
              </p>
            </div>
          )}
        </div>
      )}

      <div className="flex justify-between items-center mb-4">
        <div>
          <h3 className="text-lg font-semibold text-garage-text">DEF Records</h3>
          {records.length > 0 && (
            <p className="text-sm text-garage-text-muted">
              {records.length} {records.length === 1 ? 'record' : 'records'}
            </p>
          )}
        </div>
        <button
          onClick={handleAdd}
          className="flex items-center gap-2 px-4 py-2 bg-gray-700 border border-gray-600 text-white rounded-lg hover:bg-gray-800 transition-colors"
        >
          <Plus className="w-4 h-4" />
          <span>Add DEF</span>
        </button>
      </div>

      {error && (
        <div className="flex items-start gap-2 p-3 bg-danger/10 border border-danger/20 rounded-md mb-4">
          <AlertCircle className="w-4 h-4 text-danger flex-shrink-0 mt-0.5" />
          <p className="text-sm text-danger">{error.message}</p>
        </div>
      )}

      {records.length === 0 ? (
        <div className="text-center py-12 bg-garage-surface border border-garage-border rounded-lg">
          <Droplets className="w-12 h-12 text-garage-text-muted mx-auto mb-3" />
          <p className="text-garage-text mb-2">No DEF records yet</p>
          <p className="text-sm text-garage-text-muted mb-4">
            Track diesel exhaust fluid purchases and fill levels
          </p>
          <button
            onClick={handleAdd}
            className="inline-flex items-center gap-2 px-4 py-2 bg-gray-700 border border-gray-600 text-white rounded-lg hover:bg-gray-800 transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>Add Your First DEF Record</span>
          </button>
        </div>
      ) : (
        <div className="bg-garage-surface border border-garage-border rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-garage-bg border-b border-garage-border">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase">Date</th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-garage-text-muted uppercase">Type</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-garage-text-muted uppercase">Mileage</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-garage-text-muted uppercase">Gallons</th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-garage-text-muted uppercase">Fill Level</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase">Source</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase">Brand</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-garage-text-muted uppercase">Cost</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-garage-text-muted uppercase">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-garage-border">
                {records.map((record) => {
                  const fillLevel = parseNum(record.fill_level)
                  return (
                    <tr key={record.id} className="hover:bg-garage-bg transition-colors">
                      <td className="px-4 py-3 text-sm text-garage-text">
                        {formatDateForDisplay(record.date)}
                      </td>
                      <td className="px-4 py-3 text-sm text-center">
                        {record.entry_type === 'auto_fuel_sync' ? (
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-primary/15 text-primary">
                            Auto
                          </span>
                        ) : (
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-success/15 text-success">
                            Purchase
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm text-garage-text text-right">
                        {record.mileage?.toLocaleString() || '-'}
                      </td>
                      <td className="px-4 py-3 text-sm text-garage-text text-right font-medium">
                        {formatVolume(record.gallons)}
                      </td>
                      <td className="px-4 py-3 text-sm text-center">
                        {fillLevel !== null ? (
                          <div className="flex items-center gap-2 justify-center">
                            <div className="w-16 h-2 bg-garage-bg rounded-full overflow-hidden">
                              <div
                                className={`h-full rounded-full ${fillLevelColor(fillLevel)}`}
                                style={{ width: `${fillLevel * 100}%` }}
                              />
                            </div>
                            <span className="text-xs text-garage-text-muted">
                              {formatFillLevel(record.fill_level)}
                            </span>
                          </div>
                        ) : '-'}
                      </td>
                      <td className="px-4 py-3 text-sm text-garage-text-muted">
                        {record.entry_type === 'auto_fuel_sync' ? '\u2014' : (record.source || '-')}
                      </td>
                      <td className="px-4 py-3 text-sm text-garage-text-muted">
                        {record.entry_type === 'auto_fuel_sync' ? '\u2014' : (record.brand || '-')}
                      </td>
                      <td className="px-4 py-3 text-sm text-garage-text text-right font-semibold">
                        {formatCurrency(record.cost, { currencyCode, locale })}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex gap-1 justify-end">
                          <button
                            onClick={() => handleEdit(record)}
                            className="p-1.5 text-primary hover:bg-primary/10 rounded transition-colors"
                            aria-label="Edit"
                            title="Edit"
                          >
                            <Edit className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => handleDelete(record.id)}
                            disabled={deleteMutation.isPending && deleteMutation.variables === record.id}
                            className="p-1.5 text-danger hover:bg-danger/10 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                            aria-label="Delete"
                            title="Delete"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
