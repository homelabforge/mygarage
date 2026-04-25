import { useState, useMemo, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Fuel, Plus, Edit, Trash2, Calendar, Gauge, TrendingUp, Search, Download, Upload, Truck } from 'lucide-react'
import { toast } from 'sonner'
import type { FuelRecord } from '../types/fuel'
import type { Vehicle } from '../types/vehicle'
import { formatDateForDisplay } from '../utils/dateUtils'
import { formatCurrency } from '../utils/formatUtils'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'
import api from '../services/api'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitFormatter } from '../utils/units'
import { priceToDisplay } from '../utils/decimalSafe'
import { useFuelRecords, useDeleteFuelRecord, useImportFuelCSV } from '../hooks/queries/useFuelRecords'

interface FuelRecordListProps {
  vin: string
  onAddClick: () => void
  onEditClick: (record: FuelRecord) => void
}

export default function FuelRecordList({ vin, onAddClick, onEditClick }: FuelRecordListProps) {
  const { t } = useTranslation('vehicles')
  const [searchQuery, setSearchQuery] = useState('')
  const [exporting, setExporting] = useState(false)
  const [includeHauling, setIncludeHauling] = useState(false)
  const [vehicleFuelType, setVehicleFuelType] = useState<string>('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const { system, showBoth } = useUnitPreference()
  const { currencyCode, locale } = useCurrencyPreference()

  const { data, isLoading, error } = useFuelRecords(vin, includeHauling)
  const deleteMutation = useDeleteFuelRecord(vin)
  const importMutation = useImportFuelCSV(vin)

  const records = useMemo(() => data?.records ?? [], [data?.records])
  const averageEconomy = data?.average_l_per_100km != null ? parseFloat(String(data.average_l_per_100km)) : null

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
      toast.error(err instanceof Error ? err.message : t('fuelList.exportError'))
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
        const message = `Import completed: ${result.success_count} records imported${result.skipped_count > 0 ? `, ${result.skipped_count} duplicates skipped` : ''}${result.error_count > 0 ? `, ${result.error_count} errors` : ''}`

        if (result.errors && result.errors.length > 0) {
          toast.error(message + ' - Errors: ' + result.errors.join(', '))
        } else {
          toast.success(message)
        }
      },
      onError: (err) => {
        toast.error(err instanceof Error ? err.message : t('fuelList.importError'))
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
    if (!confirm(t('fuelList.confirmDelete'))) {
      return
    }

    deleteMutation.mutate(recordId, {
      onError: (err) => {
        toast.error(err instanceof Error ? err.message : t('fuelList.deleteError'))
      },
    })
  }

  const formatDate = (dateString: string) => {
    return formatDateForDisplay(dateString)
  }

  // Conditional column visibility based on fuel_type
  const isPropane = vehicleFuelType?.toLowerCase().includes('propane')
  const showPropaneColumn = isPropane

  if (isLoading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">{t('fuelList.loading')}</div>
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
          <Fuel className="w-5 h-5 text-garage-text-muted" />
          <h3 className="text-lg font-semibold text-garage-text">
            {t('fuelList.title')}
          </h3>
          <span className="text-sm text-garage-text-muted">({t('fuelList.recordCount', { count: records.length })})</span>
        </div>
        <div className="flex items-center gap-2">
          {/* Search */}
          {records.length > 0 && (
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-garage-text-muted" />
              <input
                type="text"
                placeholder={t('fuelList.searchPlaceholder')}
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
            disabled={importMutation.isPending}
            className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50"
            title={t('fuelList.importFromCSV')}
          >
            <Upload className="w-4 h-4" />
            <span>{importMutation.isPending ? t('fuelList.importing') : t('fuelList.importCSV')}</span>
          </button>
          {/* Export button */}
          {records.length > 0 && (
            <button
              onClick={handleExportCSV}
              disabled={exporting}
              className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50"
              title={t('fuelList.exportToCSV')}>
              <Download className="w-4 h-4" />
              <span>{exporting ? t('fuelList.exporting') : t('fuelList.exportCSV')}</span>
            </button>
          )}
          <button
            onClick={onAddClick}
            className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>{t('fuelList.addFillUp')}</span>
          </button>
        </div>
      </div>

      {/* Search results count */}
      {searchQuery && (
        <div className="text-sm text-garage-text-muted">
          {t('fuelList.showingResults', { shown: filteredRecords.length, total: records.length })}
        </div>
      )}

      {/* Inline Analytics Cards */}
      {records.length > 0 && (() => {
        const totalCost = records.reduce((sum, r) => sum + (r.cost ? parseFloat(String(r.cost)) : 0), 0)
        const totalLiters = records.reduce((sum, r) => sum + (r.liters ? parseFloat(String(r.liters)) : 0), 0)
        const avgCostPerLiter = totalLiters > 0 ? totalCost / totalLiters : null
        const odometers = records
          .map(r => r.odometer_km != null ? parseFloat(String(r.odometer_km)) : null)
          .filter((v): v is number => v != null && !isNaN(v))
        const costPerKm = odometers.length >= 2
          ? totalCost / (Math.max(...odometers) - Math.min(...odometers))
          : null

        return (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {averageEconomy !== null && (
              <div className="bg-garage-surface border border-garage-border rounded-lg p-3">
                <div className="flex items-center gap-1 text-xs text-garage-text-muted mb-1">
                  <TrendingUp className="w-3 h-3" />
                  <span>{t('fuelList.avgFuelEconomy')}</span>
                </div>
                <div className="text-lg font-semibold text-garage-text">
                  {UnitFormatter.formatFuelEconomy(averageEconomy, system, showBoth)}
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <label className="flex items-center gap-1 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={includeHauling}
                      onChange={(e) => setIncludeHauling(e.target.checked)}
                      className="h-3 w-3 text-primary focus:ring-primary border-garage-border rounded bg-garage-bg"
                    />
                    <span className="text-xs text-garage-text-muted">{t('fuelList.inclTowing')}</span>
                  </label>
                </div>
              </div>
            )}
            {totalCost > 0 && (
              <div className="bg-garage-surface border border-garage-border rounded-lg p-3">
                <div className="flex items-center gap-1 text-xs text-garage-text-muted mb-1">
                  <span>{t('fuelList.totalSpent')}</span>
                </div>
                <div className="text-lg font-semibold text-garage-text">
                  {formatCurrency(totalCost, { currencyCode, locale })}
                </div>
                <p className="text-xs text-garage-text-muted">
                  {UnitFormatter.formatVolumeTotal(totalLiters, system)}
                </p>
              </div>
            )}
            {avgCostPerLiter !== null && (
              <div className="bg-garage-surface border border-garage-border rounded-lg p-3">
                <div className="flex items-center gap-1 text-xs text-garage-text-muted mb-1">
                  <Gauge className="w-3 h-3" />
                  <span>{UnitFormatter.getCostPerVolumeLabel(system)}</span>
                </div>
                <div className="text-lg font-semibold text-garage-text">
                  {avgCostPerLiter !== null && UnitFormatter.formatCostPerVolume(avgCostPerLiter, system, currencyCode, locale)}
                </div>
              </div>
            )}
            {costPerKm !== null && isFinite(costPerKm) && (
              <div className="bg-garage-surface border border-garage-border rounded-lg p-3">
                <div className="flex items-center gap-1 text-xs text-garage-text-muted mb-1">
                  <Truck className="w-3 h-3" />
                  <span>{UnitFormatter.getCostPerDistanceLabel(system)}</span>
                </div>
                <div className="text-lg font-semibold text-garage-text">
                  {costPerKm !== null && UnitFormatter.formatCostPerDistance(costPerKm, system, currencyCode, locale)}
                </div>
              </div>
            )}
          </div>
        )
      })()}

      {records.length === 0 ? (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-8 text-center">
          <Fuel className="w-12 h-12 text-garage-text-muted opacity-50 mx-auto mb-3" />
          <p className="text-garage-text mb-2">{t('fuelList.noRecords')}</p>
          <p className="text-sm text-garage-text-muted mb-4">{t('fuelList.noRecordsDesc')}</p>
          <button
            onClick={onAddClick}
            className="inline-flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>{t('fuelList.addFirstFillUp')}</span>
          </button>
        </div>
      ) : (
        <div className="bg-garage-surface shadow rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-garage-border">
              <thead className="bg-garage-bg">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">{t('fuelList.date')}</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">{t('fuelList.mileage')}</th>
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
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">{t('fuelList.totalCost')}</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">{t('fuelList.fuelEconomy')}</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">{t('fuelList.fullTank')}</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">{t('fuelList.hauling')}</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-garage-text-muted uppercase tracking-wider">{t('fuelList.actions')}</th>
                </tr>
              </thead>
              <tbody className="bg-garage-surface divide-y divide-garage-border">
                {filteredRecords.length === 0 ? (
                  <tr>
                    <td colSpan={showPropaneColumn ? 10 : 9} className="px-4 py-8 text-center">
                      <Search className="w-8 h-8 text-garage-text-muted opacity-50 mx-auto mb-2" />
                      <p className="text-garage-text-muted">{t('fuelList.noMatchingRecords')}</p>
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
                      {record.odometer_km != null ? (
                        <div className="flex items-center gap-2 text-sm text-garage-text">
                          <Gauge className="w-4 h-4 text-garage-text-muted" />
                          {UnitFormatter.formatDistance(parseFloat(String(record.odometer_km)), system, showBoth)}
                        </div>
                      ) : (
                        <span className="text-sm text-garage-text-muted">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-sm text-garage-text">
                      {record.liters ? UnitFormatter.formatVolume(parseFloat(record.liters.toString()), system, showBoth) : '-'}
                    </td>
                    {showPropaneColumn && (
                      <td className="px-4 py-3 whitespace-nowrap text-sm text-garage-text">
                        {record.propane_liters ? UnitFormatter.formatVolume(parseFloat(record.propane_liters.toString()), system, showBoth) : '-'}
                      </td>
                    )}
                    <td className="px-4 py-3 whitespace-nowrap text-sm text-garage-text">
                      {record.price_per_unit
                        ? formatCurrency(
                            priceToDisplay(record.price_per_unit, system, record.price_basis) ?? 0,
                            { currencyCode, locale },
                          )
                        : '-'}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      {record.cost ? (
                        <div className="text-sm text-garage-text">
                          {formatCurrency(parseFloat(record.cost.toString()), { currencyCode, locale })}
                        </div>
                      ) : (
                        <span className="text-sm text-garage-text-muted">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      {record.l_per_100km ? (
                        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                          {UnitFormatter.formatFuelEconomy(parseFloat(record.l_per_100km.toString()), system, showBoth)}
                        </span>
                      ) : (
                        <span className="text-sm text-garage-text-muted">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      {record.is_full_tank ? (
                        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">{t('fuelList.full')}</span>
                      ) : (
                        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium badge-neutral">{t('fuelList.partial')}</span>
                      )}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      {record.is_hauling ? (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-800">
                          <Truck className="w-3 h-3" />{t('fuelList.towing')}</span>
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
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {records.length > 0 && records.some(r => r.notes) && (
        <div className="bg-garage-bg border border-garage-border rounded-lg p-4">
          <h4 className="text-sm font-medium text-garage-text mb-2">{t('fuelList.notes')}:</h4>
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
