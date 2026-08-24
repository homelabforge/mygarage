/**
 * ArchivedVehiclesList Component
 *
 * Displays a list of archived vehicles with actions to:
 * - Toggle visibility (eye icon)
 * - Restore to active
 * - Bulk delete selected vehicles
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Eye, EyeOff, RotateCcw, Trash2, AlertTriangle, Download } from 'lucide-react'
import api from '@/services/api'
import { toast } from 'sonner'
import { formatAPITimestamp } from '@/utils/parseAPITimestamp'
import type { Vehicle, VehicleListResponse } from '@/types/vehicle'

export default function ArchivedVehiclesList() {
  const { t } = useTranslation('vehicles')
  const [archivedVehicles, setArchivedVehicles] = useState<Vehicle[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedVins, setSelectedVins] = useState<Set<string>>(new Set())
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [exporting, setExporting] = useState(false)

  // `t` is used only for an error toast, so it must not sit in the deps below:
  // a new identity on language switch would re-run the effect and refetch the
  // list. Same shape as the mid-edit reset bug fixed in VehicleEdit.
  const tRef = useRef(t)
  tRef.current = t

  // Load archived vehicles
  const loadArchivedVehicles = useCallback(async () => {
    setLoading(true)
    try {
      const response = await api.get<VehicleListResponse>('/vehicles/archived/list')
      setArchivedVehicles(response.data.vehicles)
    } catch (error) {
      toast.error(tRef.current('archivedList.loadError'))
      console.error('Failed to load archived vehicles:', error)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadArchivedVehicles()
  }, [loadArchivedVehicles])

  // Toggle visibility of archived vehicle
  const handleToggleVisibility = async (vin: string, currentlyVisible: boolean) => {
    try {
      await api.patch(`/vehicles/${vin}/archive/visibility?visible=${!currentlyVisible}`)
      toast.success(currentlyVisible ? t('archivedList.vehicleHidden') : t('archivedList.vehicleShown'))
      await loadArchivedVehicles()
    } catch (error) {
      toast.error(t('archivedList.visibilityError'))
      console.error('Failed to toggle visibility:', error)
    }
  }

  // Restore archived vehicle to active
  const handleRestore = async (vin: string, nickname: string) => {
    try {
      await api.post(`/vehicles/${vin}/unarchive`)
      toast.success(t('archivedList.vehicleRestored', { name: nickname }))
      await loadArchivedVehicles()
    } catch (error) {
      toast.error(t('archivedList.restoreError'))
      console.error('Failed to restore vehicle:', error)
    }
  }

  // Toggle selection for bulk delete
  const handleToggleSelection = (vin: string) => {
    const newSelected = new Set(selectedVins)
    if (newSelected.has(vin)) {
      newSelected.delete(vin)
    } else {
      newSelected.add(vin)
    }
    setSelectedVins(newSelected)
  }

  const downloadReportPdf = async (vin: string, reportType: 'sale-history' | 'service-history') => {
    const response = await api.get(`/vehicles/${vin}/reports/${reportType}-pdf`, {
      responseType: 'blob',
    })
    const downloadUrl = window.URL.createObjectURL(response.data)
    const a = document.createElement('a')
    a.href = downloadUrl
    a.download = `${reportType}_${vin}_${Date.now()}.pdf`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(downloadUrl)
  }

  const handleExportBeforeDelete = async (reportType: 'sale-history' | 'service-history') => {
    if (selectedVins.size === 0) {
      toast.error(t('archivedList.noVehiclesSelected'))
      return
    }
    setExporting(true)
    try {
      for (const vin of selectedVins) {
        await downloadReportPdf(vin, reportType)
      }
      toast.success(t('archivedList.exportSuccess', { count: selectedVins.size }))
    } catch (error) {
      toast.error(t('archivedList.exportError'))
      console.error('Export before delete failed:', error)
    } finally {
      setExporting(false)
    }
  }

  // Bulk delete selected vehicles
  const handleBulkDelete = async () => {
    if (selectedVins.size === 0) {
      toast.error(t('archivedList.noVehiclesSelected'))
      return
    }

    try {
      const deletePromises = Array.from(selectedVins).map(vin =>
        api.delete(`/vehicles/${vin}`)
      )
      await Promise.all(deletePromises)
      toast.success(t('archivedList.vehiclesDeleted', { count: selectedVins.size }))
      setSelectedVins(new Set())
      setConfirmDelete(false)
      await loadArchivedVehicles()
    } catch (error) {
      toast.error(t('archivedList.deleteError'))
      console.error('Bulk delete failed:', error)
    }
  }

  if (loading) {
    return (
      <div className="text-center py-8 text-garage-text-muted">
        {t('archivedList.loading')}
      </div>
    )
  }

  if (archivedVehicles.length === 0) {
    return (
      <div className="text-center py-8 text-garage-text-muted">
        {t('archivedList.noRecords')}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Bulk Actions */}
      {selectedVins.size > 0 && (
        <div className="p-4 bg-danger/10 border border-danger/30 rounded-lg flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-5 h-5 text-danger" />
            <span className="text-sm font-medium text-garage-text">
              {t('archivedList.selectedCount', { count: selectedVins.size })}
            </span>
          </div>
          {!confirmDelete ? (
            <button
              onClick={() => setConfirmDelete(true)}
              className="px-4 py-2 bg-danger text-white rounded-lg hover:bg-danger/90 transition-colors flex items-center gap-2"
            >
              <Trash2 className="w-4 h-4" />
              {t('archivedVehiclesList.deleteSelected')}
            </button>
          ) : (
            <div className="flex flex-col sm:flex-row gap-2 items-stretch sm:items-center">
              <button
                type="button"
                onClick={() => handleExportBeforeDelete('sale-history')}
                disabled={exporting}
                className="px-4 py-2 bg-garage-surface border border-garage-border text-garage-text rounded-lg hover:bg-garage-bg transition-colors flex items-center gap-2 disabled:opacity-50"
              >
                <Download className="w-4 h-4" />
                {t('archivedList.exportSaleHistory')}
              </button>
              <button
                type="button"
                onClick={() => handleExportBeforeDelete('service-history')}
                disabled={exporting}
                className="px-4 py-2 bg-garage-surface border border-garage-border text-garage-text rounded-lg hover:bg-garage-bg transition-colors flex items-center gap-2 disabled:opacity-50"
              >
                <Download className="w-4 h-4" />
                {t('archivedList.exportBeforeDelete')}
              </button>
              <button
                onClick={() => setConfirmDelete(false)}
                className="px-4 py-2 bg-garage-surface border border-garage-border text-garage-text rounded-lg hover:bg-garage-bg transition-colors"
              >
                {t('archivedVehiclesList.cancel')}
              </button>
              <button
                onClick={handleBulkDelete}
                className="px-4 py-2 bg-danger text-white rounded-lg hover:bg-danger/90 transition-colors flex items-center gap-2"
              >
                <Trash2 className="w-4 h-4" />
                {t('archivedVehiclesList.confirmDelete')}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Archived Vehicles Table */}
      <div className="border border-garage-border rounded-lg overflow-hidden">
        <table className="w-full">
          <thead className="bg-garage-surface border-b border-garage-border">
            <tr>
              <th className="px-4 py-3 text-left">
                <input
                  type="checkbox"
                  checked={selectedVins.size === archivedVehicles.length}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setSelectedVins(new Set(archivedVehicles.map(v => v.vin)))
                    } else {
                      setSelectedVins(new Set())
                    }
                  }}
                  className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2"
                />
              </th>
              <th className="px-4 py-3 text-left text-sm font-medium text-garage-text">{t('archivedList.vin')}</th>
              <th className="px-4 py-3 text-left text-sm font-medium text-garage-text">{t('archivedList.vehicle')}</th>
              <th className="px-4 py-3 text-left text-sm font-medium text-garage-text">{t('archivedList.reason')}</th>
              <th className="px-4 py-3 text-left text-sm font-medium text-garage-text">{t('archivedList.archived')}</th>
              <th className="px-4 py-3 text-right text-sm font-medium text-garage-text">{t('archivedList.actions')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-garage-border">
            {archivedVehicles.map((vehicle) => (
              <tr key={vehicle.vin} className="hover:bg-garage-surface transition-colors">
                <td className="px-4 py-3">
                  <input
                    type="checkbox"
                    checked={selectedVins.has(vehicle.vin)}
                    onChange={() => handleToggleSelection(vehicle.vin)}
                    className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2"
                  />
                </td>
                <td className="px-4 py-3 text-sm text-garage-text-muted font-mono">
                  {vehicle.vin.slice(-8)}
                </td>
                <td className="px-4 py-3">
                  <div className="text-sm font-medium text-garage-text">{vehicle.nickname}</div>
                  <div className="text-xs text-garage-text-muted">
                    {vehicle.year} {vehicle.make} {vehicle.model}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-1 text-xs rounded-full ${
                    vehicle.archive_reason === 'Sold' ? 'bg-success/20 text-success' :
                    vehicle.archive_reason === 'Totaled' ? 'bg-danger/20 text-danger' :
                    vehicle.archive_reason === 'Gifted' ? 'bg-primary/20 text-primary' :
                    vehicle.archive_reason === 'Trade-in' ? 'bg-warning/20 text-warning' :
                    'bg-garage-surface text-garage-text-muted'
                  }`}>
                    {vehicle.archive_reason || t('archivedList.unknown')}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-garage-text-muted">
                  {formatAPITimestamp(
                    vehicle.archived_at,
                    (d) => d.toLocaleDateString(),
                    'N/A',
                  )}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-2">
                    {/* Toggle Visibility */}
                    <button
                      onClick={() => handleToggleVisibility(vehicle.vin, vehicle.archived_visible ?? true)}
                      className="p-2 text-garage-text-muted hover:text-primary transition-colors"
                      title={vehicle.archived_visible ? t('archivedList.hideInMainList') : t('archivedList.showInMainList')}
                    >
                      {vehicle.archived_visible ? (
                        <Eye className="w-4 h-4" />
                      ) : (
                        <EyeOff className="w-4 h-4" />
                      )}
                    </button>

                    {/* Restore */}
                    <button
                      onClick={() => handleRestore(vehicle.vin, vehicle.nickname)}
                      className="p-2 text-garage-text-muted hover:text-success transition-colors"
                      title={t('archivedList.restoreToActive')}
                    >
                      <RotateCcw className="w-4 h-4" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Info Text */}
      <p className="text-xs text-garage-text-muted">
        {t('archivedList.tip')}
      </p>
    </div>
  )
}
