import { useState, useEffect, useCallback } from 'react'
import { Edit, Trash2, Plus, AlertCircle, Fuel } from 'lucide-react'
import { toast } from 'sonner'
import { formatDateForDisplay } from '../utils/dateUtils'
import type { FuelRecord } from '../types/fuel'
import PropaneRecordForm from './PropaneRecordForm'
import api from '../services/api'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitConverter, UnitFormatter } from '../utils/units'

interface PropaneRecordListProps {
  vin: string
}

export default function PropaneRecordList({ vin }: PropaneRecordListProps) {
  const [records, setRecords] = useState<FuelRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [editingRecord, setEditingRecord] = useState<FuelRecord | undefined>()
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const { system } = useUnitPreference()

  const fetchRecords = useCallback(async () => {
    try {
      // Get ALL fuel records, then filter for propane-only on frontend
      const response = await api.get(`/vehicles/${vin}/fuel`)
      const allRecords = response.data.records || []

      // Filter to only records with propane_gallons and no regular gallons
      const propaneRecords = allRecords.filter((r: FuelRecord) =>
        r.propane_gallons && r.propane_gallons > 0 && !r.gallons
      )

      setRecords(propaneRecords)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    }
  }, [vin])

  useEffect(() => {
    setLoading(true)
    fetchRecords().finally(() => setLoading(false))
  }, [fetchRecords])

  const handleAdd = () => {
    setEditingRecord(undefined)
    setShowForm(true)
  }

  const handleEdit = (record: FuelRecord) => {
    setEditingRecord(record)
    setShowForm(true)
  }

  const handleDelete = async (id: number) => {
    if (!confirm('Are you sure you want to delete this propane record?')) {
      return
    }

    setDeletingId(id)
    try {
      await api.delete(`/vehicles/${vin}/fuel/${id}`)
      await fetchRecords()
      toast.success('Propane record deleted')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete propane record')
    } finally {
      setDeletingId(null)
    }
  }

  const handleSuccess = () => {
    fetchRecords()
    setShowForm(false)
  }

  const formatCurrency = (amount?: number | string): string => {
    if (!amount) return '-'
    const numAmount = typeof amount === 'string' ? parseFloat(amount) : amount
    if (isNaN(numAmount)) return '-'
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(numAmount)
  }

  const formatVolume = (gallons?: number | string): string => {
    if (!gallons) return '-'
    const numGallons = typeof gallons === 'string' ? parseFloat(gallons) : gallons
    if (isNaN(numGallons)) return '-'
    if (system === 'metric') {
      const liters = UnitConverter.gallonsToLiters(numGallons)
      if (liters === null) return '-'
      return `${liters.toFixed(3)} ${UnitFormatter.getVolumeUnit(system)}`
    }
    return `${numGallons.toFixed(3)} ${UnitFormatter.getVolumeUnit(system)}`
  }

  const extractVendor = (notes?: string): string => {
    if (!notes) return '-'
    const match = notes.match(/^Vendor: (.+?)(?:\n|$)/)
    return match ? match[1] : '-'
  }

  if (loading) {
    return (
      <div className="text-center py-8 text-garage-text-muted">
        Loading propane records...
      </div>
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
          <h3 className="text-lg font-semibold text-garage-text">Propane Records</h3>
          {records.length > 0 && (
            <p className="text-sm text-garage-text-muted">
              {records.length} {records.length === 1 ? 'record' : 'records'} •
              Total Spent: {formatCurrency(records.reduce((sum, r) => {
                const cost = typeof r.cost === 'string' ? parseFloat(r.cost) : (r.cost || 0)
                return sum + (isNaN(cost) ? 0 : cost)
              }, 0))}
            </p>
          )}
        </div>
        <button
          onClick={handleAdd}
          className="flex items-center gap-2 px-4 py-2 bg-gray-700 border border-gray-600 text-white rounded-lg hover:bg-gray-800 transition-colors"
        >
          <Plus className="w-4 h-4" />
          <span>Add Propane</span>
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
          <Fuel className="w-12 h-12 text-garage-text-muted mx-auto mb-3" />
          <p className="text-garage-text mb-2">No propane records yet</p>
          <p className="text-sm text-garage-text-muted mb-4">
            Track propane refills for your fifth wheel
          </p>
          <button
            onClick={handleAdd}
            className="inline-flex items-center gap-2 px-4 py-2 bg-gray-700 border border-gray-600 text-white rounded-lg hover:bg-gray-800 transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>Add Your First Record</span>
          </button>
        </div>
      ) : (
        <div className="bg-garage-surface border border-garage-border rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-garage-bg border-b border-garage-border">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase">Date</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-garage-text-muted uppercase">Gallons</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-garage-text-muted uppercase">Price/Unit</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-garage-text-muted uppercase">Cost</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase">Vendor</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-garage-text-muted uppercase">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-garage-border">
                {records.map((record) => (
                  <tr key={record.id} className="hover:bg-garage-bg transition-colors">
                    <td className="px-4 py-3 text-sm text-garage-text">
                      {formatDateForDisplay(record.date)}
                    </td>
                    <td className="px-4 py-3 text-sm text-garage-text text-right font-medium">
                      {formatVolume(record.propane_gallons)}
                    </td>
                    <td className="px-4 py-3 text-sm text-garage-text text-right">
                      {formatCurrency(record.price_per_unit)}
                    </td>
                    <td className="px-4 py-3 text-sm text-garage-text text-right font-semibold">
                      {formatCurrency(record.cost)}
                    </td>
                    <td className="px-4 py-3 text-sm text-garage-text-muted">
                      {extractVendor(record.notes)}
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
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
