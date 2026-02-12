import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { Fuel, Plus, Edit, Trash2, DollarSign, Calendar, Gauge, TrendingUp, Search, Download, Upload, Truck } from 'lucide-react'
import { toast } from 'sonner'
import type { FuelRecord } from '../types/fuel'
import type { Vehicle } from '../types/vehicle'
import { formatDateForDisplay } from '../utils/dateUtils'
import { formatCurrency } from '../utils/formatUtils'
import api from '../services/api'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitFormatter } from '../utils/units'

interface FuelRecordListProps {
  vin: string
  onAddClick: () => void
  onEditClick: (record: FuelRecord) => void
  onRefresh?: () => void
}

export default function FuelRecordList({ vin, onAddClick, onEditClick, onRefresh }: FuelRecordListProps) {
  const [records, setRecords] = useState<FuelRecord[]>([])
  const [averageMpg, setAverageMpg] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<number | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [includeHauling, setIncludeHauling] = useState(false)
  const [vehicleFuelType, setVehicleFuelType] = useState<string>('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const { system, showBoth } = useUnitPreference()

  const fetchRecords = useCallback(async () => {
    try {
      const response = await api.get(`/vehicles/${vin}/fuel?include_hauling=${includeHauling}`)
      setRecords(response.data.records)
      setAverageMpg(response.data.average_mpg ? parseFloat(response.data.average_mpg) : null)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    }
  }, [vin, includeHauling])

  // Fetch vehicle data to determine fuel type
  useEffect(() => {
    const fetchVehicle = async () => {
      try {
        const response = await api.get(`/vehicles/${vin}`)
        const vehicleData: Vehicle = response.data
        setVehicleFuelType(vehicleData.fuel_type || '')
      } catch {
        // Silent fail - non-critical for display
      }
    }
    fetchVehicle()
  }, [vin])

  useEffect(() => {
    setLoading(true)
    fetchRecords().finally(() => setLoading(false))
  }, [fetchRecords])

  useEffect(() => {
    if (onRefresh) {
      fetchRecords()
    }
  }, [onRefresh, fetchRecords])

  // Filter records based on search query
  const filteredRecords = useMemo(() => {
    if (!searchQuery.trim()) return records

    const query = searchQuery.toLowerCase()
    return records.filter(
      (r) =>
        (r.notes && r.notes.toLowerCase().includes(query))
    )
  }, [records, searchQuery])

  const handleExportCSV = async () => {
    setExporting(true)
    try {
      const response = await api.get(`/export/vehicles/${vin}/fuel/csv`, {
        responseType: 'blob'
      })

      // Get the filename from Content-Disposition header
      const contentDisposition = response.headers['content-disposition']
      const filenameMatch = contentDisposition?.match(/filename="(.+)"/)
      const filename = filenameMatch ? filenameMatch[1] : 'fuel_records.csv'

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
      toast.error(err instanceof Error ? err.message : 'Failed to export data')
    } finally {
      setExporting(false)
    }
  }

  const handleImportClick = () => {
    fileInputRef.current?.click()
  }

  const handleImportCSV = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    setImporting(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('skip_duplicates', 'true')

      const response = await api.post(`/import/vehicles/${vin}/fuel/csv`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      })

      const result = response.data

      // Show results
      const message = `Import completed: ${result.success_count} records imported${result.skipped_count > 0 ? `, ${result.skipped_count} duplicates skipped` : ''}${result.error_count > 0 ? `, ${result.error_count} errors` : ''}`

      if (result.errors && result.errors.length > 0) {
        toast.error(message + ' - Errors: ' + result.errors.join(', '))
      } else {
        toast.success(message)
      }

      // Refresh the list
      await fetchRecords()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to import data')
    } finally {
      setImporting(false)
      // Reset file input
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  const handleDelete = async (recordId: number) => {
    if (!confirm('Are you sure you want to delete this fuel record?')) {
      return
    }

    setDeleting(recordId)
    try {
      await api.delete(`/vehicles/${vin}/fuel/${recordId}`)

      // Refresh the list
      await fetchRecords()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete record')
    } finally {
      setDeleting(null)
    }
  }

  const formatDate = (dateString: string) => {
    return formatDateForDisplay(dateString)
  }

  // Conditional column visibility based on fuel_type
  const isPropane = vehicleFuelType?.toLowerCase().includes('propane')
  const showPropaneColumn = isPropane

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">Loading fuel records...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-danger/10 border border-danger rounded-lg p-4">
        <p className="text-danger">{error}</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-2">
          <Fuel className="w-5 h-5 text-garage-text-muted" />
          <h3 className="text-lg font-semibold text-garage-text">
            Fuel History
          </h3>
          <span className="text-sm text-garage-text-muted">({records.length} records)</span>
        </div>
        <div className="flex items-center gap-2">
          {/* Search */}
          {records.length > 0 && (
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-garage-text-muted" />
              <input
                type="text"
                placeholder="Search notes..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-10 pr-4 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text w-56"
              />
            </div>
          )}
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
            disabled={importing}
            className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50"
            title="Import from CSV"
          >
            <Upload className="w-4 h-4" />
            <span>{importing ? 'Importing...' : 'Import CSV'}</span>
          </button>
          {/* Export button */}
          {records.length > 0 && (
            <button
              onClick={handleExportCSV}
              disabled={exporting}
              className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50"
              title="Export to CSV"
            >
              <Download className="w-4 h-4" />
              <span>{exporting ? 'Exporting...' : 'Export CSV'}</span>
            </button>
          )}
          <button
            onClick={onAddClick}
            className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>Add Fill-up</span>
          </button>
        </div>
      </div>

      {/* Search results count */}
      {searchQuery && (
        <div className="text-sm text-garage-text-muted">
          Showing {filteredRecords.length} of {records.length} record{records.length !== 1 ? 's' : ''}
        </div>
      )}

      {/* Inline Analytics Cards */}
      {records.length > 0 && (() => {
        const totalCost = records.reduce((sum, r) => sum + (r.cost ? parseFloat(String(r.cost)) : 0), 0)
        const totalGallons = records.reduce((sum, r) => sum + (r.gallons ? parseFloat(String(r.gallons)) : 0), 0)
        const avgCostPerGallon = totalGallons > 0 ? totalCost / totalGallons : null
        const mileages = records.filter(r => r.mileage).map(r => r.mileage!)
        const costPer1kMiles = mileages.length >= 2
          ? (totalCost / (Math.max(...mileages) - Math.min(...mileages))) * 1000
          : null

        return (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {averageMpg !== null && (
              <div className="bg-garage-surface border border-garage-border rounded-lg p-3">
                <div className="flex items-center gap-1 text-xs text-garage-text-muted mb-1">
                  <TrendingUp className="w-3 h-3" />
                  <span>Avg Fuel Economy</span>
                </div>
                <div className="text-lg font-semibold text-garage-text">
                  {UnitFormatter.formatFuelEconomy(averageMpg, system, showBoth)}
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <label className="flex items-center gap-1 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={includeHauling}
                      onChange={(e) => setIncludeHauling(e.target.checked)}
                      className="h-3 w-3 text-primary focus:ring-primary border-garage-border rounded bg-garage-bg"
                    />
                    <span className="text-xs text-garage-text-muted">Incl. Towing</span>
                  </label>
                </div>
              </div>
            )}
            {totalCost > 0 && (
              <div className="bg-garage-surface border border-garage-border rounded-lg p-3">
                <div className="flex items-center gap-1 text-xs text-garage-text-muted mb-1">
                  <DollarSign className="w-3 h-3" />
                  <span>Total Spent</span>
                </div>
                <div className="text-lg font-semibold text-garage-text">
                  {formatCurrency(totalCost)}
                </div>
                <p className="text-xs text-garage-text-muted">
                  {totalGallons.toFixed(1)} gal total
                </p>
              </div>
            )}
            {avgCostPerGallon !== null && (
              <div className="bg-garage-surface border border-garage-border rounded-lg p-3">
                <div className="flex items-center gap-1 text-xs text-garage-text-muted mb-1">
                  <Gauge className="w-3 h-3" />
                  <span>Avg Cost/Gal</span>
                </div>
                <div className="text-lg font-semibold text-garage-text">
                  {formatCurrency(avgCostPerGallon)}
                </div>
              </div>
            )}
            {costPer1kMiles !== null && isFinite(costPer1kMiles) && (
              <div className="bg-garage-surface border border-garage-border rounded-lg p-3">
                <div className="flex items-center gap-1 text-xs text-garage-text-muted mb-1">
                  <Truck className="w-3 h-3" />
                  <span>Cost/1k Miles</span>
                </div>
                <div className="text-lg font-semibold text-garage-text">
                  {formatCurrency(costPer1kMiles)}
                </div>
              </div>
            )}
          </div>
        )
      })()}

      {records.length === 0 ? (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-8 text-center">
          <Fuel className="w-12 h-12 text-garage-text-muted opacity-50 mx-auto mb-3" />
          <p className="text-garage-text mb-2">No fuel records yet</p>
          <p className="text-sm text-garage-text-muted mb-4">
            Start tracking your fill-ups and monitor fuel economy
          </p>
          <button
            onClick={onAddClick}
            className="inline-flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>Add First Fill-up</span>
          </button>
        </div>
      ) : (
        <div className="bg-garage-surface shadow rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-garage-border">
              <thead className="bg-garage-bg">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">
                    Date
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">
                    Mileage
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">
                    Volume ({UnitFormatter.getVolumeUnit(system)})
                  </th>
                  {showPropaneColumn && (
                    <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">
                      Propane ({UnitFormatter.getVolumeUnit(system)})
                    </th>
                  )}
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">
                    Price/{UnitFormatter.getVolumeUnit(system)}
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">
                    Total Cost
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">
                    Fuel Economy
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">
                    Full Tank
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">
                    Hauling
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-garage-text-muted uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-garage-surface divide-y divide-garage-border">
                {filteredRecords.length === 0 ? (
                  <tr>
                    <td colSpan={showPropaneColumn ? 10 : 9} className="px-4 py-8 text-center">
                      <Search className="w-8 h-8 text-garage-text-muted opacity-50 mx-auto mb-2" />
                      <p className="text-garage-text-muted">No matching records found</p>
                    </td>
                  </tr>
                ) : (
                  filteredRecords.map((record) => (
                  <tr key={record.id} className="hover:bg-garage-bg">
                    <td className="px-4 py-3 whitespace-nowrap">
                      <div className="flex items-center gap-2 text-sm text-garage-text">
                        <Calendar className="w-4 h-4 text-garage-text-muted" />
                        {formatDate(record.date)}
                      </div>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      {record.mileage ? (
                        <div className="flex items-center gap-2 text-sm text-garage-text">
                          <Gauge className="w-4 h-4 text-garage-text-muted" />
                          {UnitFormatter.formatDistance(record.mileage, system, showBoth)}
                        </div>
                      ) : (
                        <span className="text-sm text-garage-text-muted">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-sm text-garage-text">
                      {record.gallons ? UnitFormatter.formatVolume(parseFloat(record.gallons.toString()), system, showBoth) : '-'}
                    </td>
                    {showPropaneColumn && (
                      <td className="px-4 py-3 whitespace-nowrap text-sm text-garage-text">
                        {record.propane_gallons ? UnitFormatter.formatVolume(parseFloat(record.propane_gallons.toString()), system, showBoth) : '-'}
                      </td>
                    )}
                    <td className="px-4 py-3 whitespace-nowrap text-sm text-garage-text">
                      {record.price_per_unit ? formatCurrency(parseFloat(record.price_per_unit.toString())) : '-'}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      {record.cost ? (
                        <div className="flex items-center gap-2 text-sm text-garage-text">
                          <DollarSign className="w-4 h-4 text-garage-text-muted" />
                          {formatCurrency(parseFloat(record.cost.toString()))}
                        </div>
                      ) : (
                        <span className="text-sm text-garage-text-muted">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      {record.mpg ? (
                        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                          {UnitFormatter.formatFuelEconomy(parseFloat(record.mpg.toString()), system, showBoth)}
                        </span>
                      ) : (
                        <span className="text-sm text-garage-text-muted">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      {record.is_full_tank ? (
                        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                          Full
                        </span>
                      ) : (
                        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium badge-neutral">
                          Partial
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      {record.is_hauling ? (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-800">
                          <Truck className="w-3 h-3" />
                          Towing
                        </span>
                      ) : (
                        <span className="text-sm text-garage-text-muted">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-right text-sm">
                      <div className="flex justify-end gap-2">
                        <button
                          onClick={() => onEditClick(record)}
                          className="text-primary hover:text-primary-dark"
                          title="Edit"
                        >
                          <Edit className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleDelete(record.id)}
                          disabled={deleting === record.id}
                          className="text-danger hover:text-danger/80 disabled:opacity-50"
                          title="Delete"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {records.length > 0 && records.some(r => r.notes) && (
        <div className="bg-garage-bg border border-garage-border rounded-lg p-4">
          <h4 className="text-sm font-medium text-garage-text mb-2">Notes:</h4>
          <div className="space-y-2">
            {records.filter(r => r.notes).map((record) => (
              <div key={record.id} className="text-sm">
                <span className="text-garage-text-muted">{formatDate(record.date)}:</span>
                <span className="text-garage-text ml-2">{record.notes}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
