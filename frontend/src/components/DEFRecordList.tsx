import { useState, useEffect, useCallback } from 'react'
import { Edit, Trash2, Plus, AlertCircle, Droplets, TrendingDown, DollarSign } from 'lucide-react'
import { toast } from 'sonner'
import { formatDateForDisplay } from '../utils/dateUtils'
import { formatCurrency } from '../utils/formatUtils'
import type { DEFRecord, DEFAnalytics } from '../types/def'
import DEFRecordForm from './DEFRecordForm'
import api from '../services/api'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitConverter, UnitFormatter } from '../utils/units'

interface DEFRecordListProps {
  vin: string
}

export default function DEFRecordList({ vin }: DEFRecordListProps) {
  const [records, setRecords] = useState<DEFRecord[]>([])
  const [analytics, setAnalytics] = useState<DEFAnalytics | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [editingRecord, setEditingRecord] = useState<DEFRecord | undefined>()
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const { system } = useUnitPreference()

  const fetchData = useCallback(async () => {
    try {
      const [recordsRes, analyticsRes] = await Promise.all([
        api.get(`/vehicles/${vin}/def`),
        api.get(`/vehicles/${vin}/def/analytics`),
      ])
      setRecords(recordsRes.data.records || [])
      setAnalytics(analyticsRes.data)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    }
  }, [vin])

  useEffect(() => {
    setLoading(true)
    fetchData().finally(() => setLoading(false))
  }, [fetchData])

  const handleAdd = () => {
    setEditingRecord(undefined)
    setShowForm(true)
  }

  const handleEdit = (record: DEFRecord) => {
    setEditingRecord(record)
    setShowForm(true)
  }

  const handleDelete = async (id: number) => {
    if (!confirm('Are you sure you want to delete this DEF record?')) {
      return
    }

    setDeletingId(id)
    try {
      await api.delete(`/vehicles/${vin}/def/${id}`)
      await fetchData()
      toast.success('DEF record deleted')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete DEF record')
    } finally {
      setDeletingId(null)
    }
  }

  const handleSuccess = () => {
    fetchData()
    setShowForm(false)
  }

  const parseNum = (val?: number | string | null): number | null => {
    if (val === undefined || val === null) return null
    const num = typeof val === 'string' ? parseFloat(val) : val
    return isNaN(num) ? null : num
  }

  const formatVolume = (gallons?: number | string): string => {
    const num = parseNum(gallons)
    if (num === null) return '-'
    if (system === 'metric') {
      const liters = UnitConverter.gallonsToLiters(num)
      if (liters === null) return '-'
      return `${liters.toFixed(3)} ${UnitFormatter.getVolumeUnit(system)}`
    }
    return `${num.toFixed(3)} ${UnitFormatter.getVolumeUnit(system)}`
  }

  const formatFillLevel = (level?: number | string): string => {
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

  if (loading) {
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
                <span>Est. Miles Left</span>
              </div>
              <div className={`text-lg font-semibold ${milesRemainingColor(analytics.estimated_miles_remaining)}`}>
                {analytics.estimated_miles_remaining.toLocaleString()}
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
                {parseNum(analytics.gallons_per_1000_miles)?.toFixed(1)}
              </div>
              <p className="text-xs text-garage-text-muted">gal/1,000 mi</p>
            </div>
          )}

          {/* Avg Cost/Gallon */}
          {analytics.avg_cost_per_gallon !== null && (
            <div className="bg-garage-surface border border-garage-border rounded-lg p-3">
              <div className="flex items-center gap-1 text-xs text-garage-text-muted mb-1">
                <DollarSign className="w-3 h-3" />
                <span>Avg Cost/Gal</span>
              </div>
              <div className="text-lg font-semibold text-garage-text">
                {formatCurrency(analytics.avg_cost_per_gallon)}
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
                {formatCurrency(analytics.total_cost)}
              </div>
              <p className="text-xs text-garage-text-muted">
                {parseNum(analytics.total_gallons)?.toFixed(1)} gal total
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
          <p className="text-sm text-danger">{error}</p>
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
                        {record.source || '-'}
                      </td>
                      <td className="px-4 py-3 text-sm text-garage-text-muted">
                        {record.brand || '-'}
                      </td>
                      <td className="px-4 py-3 text-sm text-garage-text text-right font-semibold">
                        {formatCurrency(record.cost)}
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
                            disabled={deletingId === record.id}
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
