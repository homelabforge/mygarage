import { useState, useMemo, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Fuel, Plus, Edit, Trash2, TrendingUp, Search, Download, Upload, Truck, Gauge, ChevronLeft, ChevronRight } from 'lucide-react'
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
import { getUsageTracking } from '../utils/usageTracking'
import { useFuelRecords, useDeleteFuelRecord, useImportFuelCSV } from '../hooks/queries/useFuelRecords'
import { Button, IconButton, Card, Mono, DataTable, Badge, SearchField, EmptyState, Checkbox, Select } from './ui'
import type { DataTableColumn } from './ui'

type ImportFormat = 'csv' | 'fuelio' | 'drivvo' | 'tesla' | 'external'

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
  // Task 13 — which usage dimension(s) this vehicle tracks, driving mileage
  // vs. fuel-rate column + stat visibility below. Defaults mirror
  // getUsageTracking's own distance-primary default so the table doesn't
  // flash the wrong columns before the vehicle fetch resolves.
  const [vehicleUsageUnit, setVehicleUsageUnit] = useState<string>('distance')
  const [vehicleSecondaryUsageEnabled, setVehicleSecondaryUsageEnabled] = useState<boolean>(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [importFormat, setImportFormat] = useState<ImportFormat>('csv')
  const { system, showBoth } = useUnitPreference()
  const { currencyCode, locale } = useCurrencyPreference()

  // Phase 3.8 — paginate the fuel-records list. rc1 silently capped
  // at 100 with no indication; surfaced by issue #69. 50 per page is
  // a reasonable default — covers ~6 months for a typical commuter
  // and keeps initial render snappy.
  const PAGE_SIZE = 50
  const [page, setPage] = useState(0)

  const { data, isLoading, error } = useFuelRecords(vin, includeHauling, {
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  })
  const deleteMutation = useDeleteFuelRecord(vin)
  const importMutation = useImportFuelCSV(vin)

  const records = useMemo(() => data?.records ?? [], [data?.records])
  const totalRecords = data?.total ?? records.length
  const totalPages = Math.max(1, Math.ceil(totalRecords / PAGE_SIZE))
  const canPrev = page > 0
  const canNext = page < totalPages - 1

  // Reset to page 0 when the includeHauling toggle changes (the
  // record set changes and the prior page may be empty/out of range).
  useEffect(() => {
    setPage(0)
  }, [includeHauling])
  const averageEconomy = data?.average_l_per_100km != null ? parseFloat(String(data.average_l_per_100km)) : null
  // Task 13 — hours-economy averages (canonical L/hr + currency/hr), null
  // for a pure-distance vehicle (no engine_hours-bearing fuel records).
  const averageFuelRate = data?.average_l_per_hr != null ? parseFloat(String(data.average_l_per_hr)) : null
  const averageCostPerHr = data?.average_cost_per_hr != null ? parseFloat(String(data.average_cost_per_hr)) : null

  // Which usage dimension(s) this vehicle tracks — drives mileage/economy
  // vs. fuel-rate column + stat visibility (a dual vehicle shows both).
  const { tracksDistance, tracksHours } = getUsageTracking({
    usage_unit: vehicleUsageUnit,
    secondary_usage_enabled: vehicleSecondaryUsageEnabled,
  })

  // Fetch vehicle data to determine fuel type
  useEffect(() => {
    const fetchVehicle = async () => {
      try {
        const response = await api.get(`/vehicles/${vin}`)
        const vehicleData: Vehicle = response.data
        setVehicleFuelType(vehicleData.fuel_type || '')
        setVehicleUsageUnit(vehicleData.usage_unit || 'distance')
        setVehicleSecondaryUsageEnabled(!!vehicleData.secondary_usage_enabled)
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
      // Export in the units the user actually reads. Storage is
      // metric-canonical, so without this an imperial account got a
      // metric file (#128). The backend stamps a `unit_system` column
      // so re-importing converts back correctly.
      const response = await api.get(`/export/vehicles/${vin}/fuel/csv`, {
        params: { units: system },
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

    importMutation.mutate(
      { formData, format: importFormat },
      {
        onSuccess: (result) => {
          const message = t('fuelList.importCompleted', {
            success: result.success_count,
            skipped: result.skipped_count,
            errors: result.error_count,
            defaultValue: `Import completed: ${result.success_count} records imported${result.skipped_count > 0 ? `, ${result.skipped_count} duplicates skipped` : ''}${result.error_count > 0 ? `, ${result.error_count} errors` : ''}`,
          })

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
          if (fileInputRef.current) {
            fileInputRef.current.value = ''
          }
        },
      },
    )
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

  const columns: DataTableColumn<FuelRecord>[] = [
    { id: 'date', header: t('fuelList.date'), mono: true, render: (r) => formatDate(r.date) },
    ...(tracksDistance ? [{
      id: 'mileage', header: t('fuelList.mileage'), align: 'right' as const, mono: true,
      render: (r: FuelRecord) => r.odometer_km != null ? UnitFormatter.formatDistance(parseFloat(String(r.odometer_km)), system, showBoth) : '-',
    }] : []),
    { id: 'volume', header: t('fuelList.volumeUnit', { unit: UnitFormatter.getVolumeUnit(system) }), align: 'right', mono: true,
      render: (r) => r.liters ? UnitFormatter.formatVolume(parseFloat(r.liters.toString()), system, showBoth) : '-' },
    ...(showPropaneColumn ? [{
      id: 'propane', header: t('fuelList.propaneUnit', { unit: UnitFormatter.getVolumeUnit(system) }), align: 'right' as const, mono: true,
      render: (r: FuelRecord) => r.propane_liters ? UnitFormatter.formatVolume(parseFloat(r.propane_liters.toString()), system, showBoth) : '-',
    }] : []),
    // B8: generic truthful header — the row value already respects every price_basis
    // via priceToDisplay(…, r.price_basis), so a volume-only "Price/L" heading would
    // lie for per_weight/per_kwh/per_tank rows. "Unit price" is honest across all four.
    { id: 'price', header: t('fuelList.unitPrice'), align: 'right', mono: true,
      render: (r) => r.price_per_unit ? formatCurrency(priceToDisplay(r.price_per_unit, system, r.price_basis) ?? 0, { currencyCode, locale }) : '-' },
    { id: 'cost', header: t('fuelList.totalCost'), align: 'right', mono: true,
      render: (r) => r.cost ? formatCurrency(parseFloat(r.cost.toString()), { currencyCode, locale }) : '-' },
    ...(tracksDistance ? [{
      id: 'economy', header: t('fuelList.fuelEconomy'),
      render: (r: FuelRecord) => r.l_per_100km
        ? <Badge tone="success">{UnitFormatter.formatFuelEconomy(parseFloat(r.l_per_100km.toString()), system, showBoth)}</Badge>
        : <span className="text-sm text-text-mute">-</span>,
    }] : []),
    // Task 13 — engine-hours economy (GPH imperial / L/hr metric display; canonical L/hr storage).
    ...(tracksHours ? [{
      id: 'fuelRate', header: t('fuelList.fuelRate'),
      render: (r: FuelRecord) => r.l_per_hr
        ? <Badge tone="success">{UnitFormatter.formatFuelRate(parseFloat(r.l_per_hr.toString()), system, showBoth)}</Badge>
        : <span className="text-sm text-text-mute">-</span>,
    }] : []),
    { id: 'fullTank', header: t('fuelList.fullTank'),
      render: (r) => r.is_full_tank ? <Badge>{t('fuelList.full')}</Badge> : <Badge tone="muted">{t('fuelList.partial')}</Badge> },
    { id: 'hauling', header: t('fuelList.hauling'),
      render: (r) => r.is_hauling
        ? <Badge tone="warning" icon={Truck}>{t('fuelList.towing')}</Badge>
        : <span className="text-sm text-text-mute">-</span> },
    { id: 'actions', header: t('fuelList.actions'), align: 'right',
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
      ) },
  ]

  if (isLoading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-text-mute">{t('fuelList.loading')}</div>
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
      <div className="flex flex-col gap-3 sm:flex-row sm:justify-between sm:items-center">
        <div className="flex items-center gap-2">
          <Fuel aria-hidden="true" className="w-5 h-5 text-text-mute" />
          <h3 className="text-lg font-semibold text-text">{t('fuelList.title')}</h3>
          <span className="text-sm text-text-mute">
            (
            {totalRecords > PAGE_SIZE
              ? t('fuelList.paginatedCount', { shown: records.length, total: totalRecords })
              : t('fuelList.recordCount', { count: records.length })}
            )
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {records.length > 0 && (
            <SearchField
              label={t('fuelList.searchPlaceholder')}
              placeholder={t('fuelList.searchPlaceholder')}
              value={searchQuery}
              onChange={setSearchQuery}
              className="flex-1 min-w-[10rem] sm:flex-none sm:w-56"
            />
          )}
          <input ref={fileInputRef} type="file" accept=".csv,text/csv" onChange={handleImportCSV} className="hidden" />
          <Select
            id="fuel-import-format"
            aria-label={t('fuelList.importFormat')}
            value={importFormat}
            onChange={(e) => setImportFormat(e.target.value as ImportFormat)}
            options={[
              { value: 'csv', label: t('fuelList.importFormatCsv') },
              { value: 'fuelio', label: t('fuelList.importFormatFuelio') },
              { value: 'drivvo', label: t('fuelList.importFormatDrivvo') },
              { value: 'tesla', label: t('fuelList.importFormatTesla') },
              { value: 'external', label: t('fuelList.importFormatAuto') },
            ]}
            className="w-40"
          />
          <Button variant="secondary" icon={Upload} onClick={handleImportClick} loading={importMutation.isPending} title={t('fuelList.importFromCSV')}>
            {importMutation.isPending ? t('fuelList.importing') : t('fuelList.importCSV')}
          </Button>
          {records.length > 0 && (
            <Button variant="secondary" icon={Download} onClick={handleExportCSV} loading={exporting} title={t('fuelList.exportToCSV')}>
              {exporting ? t('fuelList.exporting') : t('fuelList.exportCSV')}
            </Button>
          )}
          <Button variant="primary" icon={Plus} onClick={onAddClick}>
            {t('fuelList.addFillUp')}
          </Button>
        </div>
      </div>

      {searchQuery && (
        <div className="text-sm text-text-mute">
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
            {tracksDistance && averageEconomy !== null && (
              <Card padding="sm">
                <div className="flex items-center gap-1 text-xs text-text-mute mb-1">
                  <TrendingUp aria-hidden="true" className="w-3 h-3" />
                  <span>{t('fuelList.avgFuelEconomy')}</span>
                </div>
                <Mono size="2xl" weight="bold">{UnitFormatter.formatFuelEconomy(averageEconomy, system, showBoth)}</Mono>
                <div className="mt-1">
                  <Checkbox
                    id="fuel-incl-towing"
                    label={t('fuelList.inclTowing')}
                    checked={includeHauling}
                    onChange={(e) => setIncludeHauling(e.target.checked)}
                  />
                </div>
              </Card>
            )}
            {totalCost > 0 && (
              <Card padding="sm">
                <div className="flex items-center gap-1 text-xs text-text-mute mb-1">
                  <span>{t('fuelList.totalSpent')}</span>
                </div>
                <Mono size="2xl" weight="bold">{formatCurrency(totalCost, { currencyCode, locale })}</Mono>
                <Mono size="sm" tone="muted" className="mt-1 block">{UnitFormatter.formatVolumeTotal(totalLiters, system)}</Mono>
              </Card>
            )}
            {avgCostPerLiter !== null && (
              <Card padding="sm">
                <div className="flex items-center gap-1 text-xs text-text-mute mb-1">
                  <Gauge aria-hidden="true" className="w-3 h-3" />
                  <span>{UnitFormatter.getCostPerVolumeLabel(system)}</span>
                </div>
                <Mono size="2xl" weight="bold">{UnitFormatter.formatCostPerVolume(avgCostPerLiter, system, currencyCode, locale)}</Mono>
              </Card>
            )}
            {tracksDistance && costPerKm !== null && isFinite(costPerKm) && (
              <Card padding="sm">
                <div className="flex items-center gap-1 text-xs text-text-mute mb-1">
                  <Truck aria-hidden="true" className="w-3 h-3" />
                  <span>{UnitFormatter.getCostPerDistanceLabel(system)}</span>
                </div>
                <Mono size="2xl" weight="bold">{UnitFormatter.formatCostPerDistance(costPerKm, system, currencyCode, locale)}</Mono>
              </Card>
            )}
            {/* Task 13 — engine-hours economy stats. */}
            {tracksHours && averageFuelRate !== null && (
              <Card padding="sm">
                <div className="flex items-center gap-1 text-xs text-text-mute mb-1">
                  <Gauge aria-hidden="true" className="w-3 h-3" />
                  <span>{t('fuelList.avgFuelRate', { unit: UnitFormatter.getFuelRateUnit(system) })}</span>
                </div>
                <Mono size="2xl" weight="bold">{UnitFormatter.formatFuelRate(averageFuelRate, system, showBoth)}</Mono>
              </Card>
            )}
            {tracksHours && averageCostPerHr !== null && (
              <Card padding="sm">
                <div className="flex items-center gap-1 text-xs text-text-mute mb-1">
                  <span>{t('fuelList.costPerHour')}</span>
                </div>
                <Mono size="2xl" weight="bold">{formatCurrency(averageCostPerHr, { currencyCode, locale })}</Mono>
              </Card>
            )}
          </div>
        )
      })()}

      {records.length === 0 ? (
        <EmptyState
          icon={Fuel}
          title={t('fuelList.noRecords')}
          description={t('fuelList.noRecordsDesc')}
          action={<Button variant="primary" icon={Plus} onClick={onAddClick}>{t('fuelList.addFirstFillUp')}</Button>}
        />
      ) : (
        <Card padding="none">
          <DataTable
            caption={t('fuelList.tableCaption')}
            columns={columns}
            rows={filteredRecords}
            rowKey={(r) => String(r.id)}
            emptyState={<EmptyState size="sm" icon={Search} title={t('fuelList.noMatchingRecords')} />}
          />
        </Card>
      )}

      {/* Phase 3.8 pagination controls */}
      {totalRecords > PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-text-mute">
            {t('fuelList.pageRange', { start: page * PAGE_SIZE + 1, end: Math.min(totalRecords, (page + 1) * PAGE_SIZE), total: totalRecords })}
          </span>
          <div className="flex items-center gap-2">
            <IconButton icon={ChevronLeft} label={t('common:previous')} variant="surface" size="sm" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={!canPrev} />
            <span className="text-text-mute">{t('fuelList.pageOf', { page: page + 1, total: totalPages })}</span>
            <IconButton icon={ChevronRight} label={t('common:next')} variant="surface" size="sm" onClick={() => setPage((p) => p + 1)} disabled={!canNext} />
          </div>
        </div>
      )}

      {records.length > 0 && records.some((r) => r.notes) && (
        <div className="bg-surface-2 border border-border rounded-lg p-4">
          <h4 className="text-sm font-medium text-text mb-2">{t('fuelList.notes')}:</h4>
          <div className="space-y-2">
            {records.filter((r) => r.notes).map((record) => (
              <div key={record.id} className="text-sm">
                <span className="text-text-mute">{formatDate(record.date)}:</span>
                <span className="text-text ml-2">{record.notes}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
