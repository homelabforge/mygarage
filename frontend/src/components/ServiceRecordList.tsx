import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { formatDateForDisplay } from '../utils/dateUtils'
import { Wrench, Plus, Edit, Trash2, DollarSign, Calendar, Gauge, Search, Download, Upload, Paperclip } from 'lucide-react'
import { toast } from 'sonner'
import type { ServiceRecord } from '../types/service'
import AttachmentQuickView from './AttachmentQuickView'
import api from '../services/api'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitFormatter } from '../utils/units'

interface ServiceRecordListProps {
  vin: string
  onAddClick: () => void
  onEditClick: (record: ServiceRecord) => void
  onRefresh?: () => void
}

export default function ServiceRecordList({ vin, onAddClick, onEditClick, onRefresh }: ServiceRecordListProps) {
  const [records, setRecords] = useState<ServiceRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<number | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [quickViewRecordId, setQuickViewRecordId] = useState<number | null>(null)
  const [quickViewPosition, setQuickViewPosition] = useState({ top: 0, left: 0 })
  const { system, showBoth } = useUnitPreference()

  const fetchRecords = useCallback(async () => {
    try {
      const response = await api.get(`/vehicles/${vin}/service`)
      setRecords(response.data.records)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    }
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
        (r.service_category && r.service_category.toLowerCase().includes(query)) ||
        (r.service_type && r.service_type.toLowerCase().includes(query)) ||
        (r.vendor_name && r.vendor_name.toLowerCase().includes(query))
    )
  }, [records, searchQuery])

  const handleExportCSV = async () => {
    setExporting(true)
    try {
      const response = await api.get(`/export/vehicles/${vin}/service/csv`, {
        responseType: 'blob'
      })

      // Get the filename from Content-Disposition header
      const contentDisposition = response.headers['content-disposition']
      const filenameMatch = contentDisposition?.match(/filename="(.+)"/)
      const filename = filenameMatch ? filenameMatch[1] : 'service_records.csv'

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
      toast.error('Export failed', {
        description: err instanceof Error ? err.message : 'Failed to export data'
      })
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

      const response = await api.post(`/import/vehicles/${vin}/service/csv`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      })

      const result = response.data

      // Show results
      const parts = []
      parts.push(`✓ ${result.success_count} records imported`)
      if (result.skipped_count > 0) parts.push(`○ ${result.skipped_count} duplicates skipped`)
      if (result.error_count > 0) parts.push(`✗ ${result.error_count} errors`)

      if (result.errors && result.errors.length > 0) {
        toast.error('Import completed with errors', {
          description: `${parts.join(', ')}. Errors: ${result.errors.join(', ')}`
        })
      } else {
        toast.success('Import completed', {
          description: parts.join(', ')
        })
      }

      // Refresh the list
      await fetchRecords()
    } catch (err) {
      toast.error('Import failed', {
        description: err instanceof Error ? err.message : 'Failed to import data'
      })
    } finally {
      setImporting(false)
      // Reset file input
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  const handleDelete = async (recordId: number) => {
    if (!confirm('Are you sure you want to delete this service record?')) {
      return
    }

    setDeleting(recordId)
    try {
      await api.delete(`/vehicles/${vin}/service/${recordId}`)

      // Refresh the list
      await fetchRecords()
    } catch (err) {
      toast.error('Delete failed', {
        description: err instanceof Error ? err.message : 'Failed to delete record'
      })
    } finally {
      setDeleting(null)
    }
  }

  const formatCurrency = (amount?: number) => {
    if (amount === undefined || amount === null) return '-'
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(amount)
  }

  const formatDate = (dateString: string) => {
    return formatDateForDisplay(dateString)
  }

  const getServiceTypeBadgeColor = (type?: string) => {
    switch (type) {
      case 'Maintenance':
        return 'bg-blue-100 text-blue-800'
      case 'Inspection':
        return 'bg-orange-100 text-orange-800'
      case 'Collision':
        return 'bg-red-100 text-red-800'
      case 'Upgrades':
        return 'bg-purple-100 text-purple-800'
      default:
        return 'badge-neutral'
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">Loading service records...</div>
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
    <>
      {quickViewRecordId && (
        <AttachmentQuickView
          recordId={quickViewRecordId}
          onClose={() => setQuickViewRecordId(null)}
          position={quickViewPosition}
        />
      )}

      <div className="space-y-4">
        <div className="flex justify-between items-center">
        <div className="flex items-center gap-2">
          <Wrench className="w-5 h-5 text-garage-text-muted" />
          <h3 className="text-lg font-semibold text-garage-text">
            Service History
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
                placeholder="Search services..."
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
            <span>Add Service</span>
          </button>
        </div>
      </div>

      {/* Search results count */}
      {searchQuery && (
        <div className="text-sm text-garage-text-muted">
          Showing {filteredRecords.length} of {records.length} record{records.length !== 1 ? 's' : ''}
        </div>
      )}

      {records.length === 0 ? (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-8 text-center">
          <Wrench className="w-12 h-12 text-garage-text-muted opacity-50 mx-auto mb-3" />
          <p className="text-garage-text mb-2">No service records yet</p>
          <p className="text-sm text-garage-text-muted mb-4">
            Start tracking your vehicle's maintenance and repairs
          </p>
          <button
            onClick={onAddClick}
            className="inline-flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>Add First Service Record</span>
          </button>
        </div>
      ) : (
        <div className="bg-garage-surface shadow rounded-lg overflow-hidden border border-garage-border">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-garage-border">
              <thead className="bg-garage-bg">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">
                    Date
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">
                    Category
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">
                    Service Type
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">
                    Mileage ({UnitFormatter.getDistanceUnit(system)})
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">
                    Cost
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-garage-text-muted uppercase tracking-wider">
                    Vendor
                  </th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-garage-text-muted uppercase tracking-wider">
                    Attachments
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-garage-text-muted uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-garage-surface divide-y divide-garage-border">
                {filteredRecords.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center">
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
                      {record.service_category ? (
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getServiceTypeBadgeColor(record.service_category)}`}>
                          {record.service_category}
                        </span>
                      ) : (
                        <span className="text-sm text-garage-text-muted">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="text-sm font-medium text-garage-text">{record.service_type}</div>
                      {record.notes && (
                        <div className="text-xs text-garage-text-muted mt-1">{record.notes}</div>
                      )}
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
                    <td className="px-4 py-3 whitespace-nowrap">
                      {record.cost ? (
                        <div className="flex items-center gap-2 text-sm text-garage-text">
                          <DollarSign className="w-4 h-4 text-garage-text-muted" />
                          {formatCurrency(record.cost)}
                        </div>
                      ) : (
                        <span className="text-sm text-garage-text-muted">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {record.vendor_name ? (
                        <div>
                          <div className="text-sm text-garage-text">{record.vendor_name}</div>
                          {record.vendor_location && (
                            <div className="text-xs text-garage-text-muted">{record.vendor_location}</div>
                          )}
                        </div>
                      ) : (
                        <span className="text-sm text-garage-text-muted">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-center">
                      {record.attachment_count !== undefined && record.attachment_count > 0 ? (
                        <button
                          onClick={(e) => {
                            const rect = e.currentTarget.getBoundingClientRect()
                            setQuickViewPosition({
                              top: rect.bottom + 8,
                              left: rect.left - 150
                            })
                            setQuickViewRecordId(record.id)
                          }}
                          className="flex flex-col items-center gap-0.5 hover:bg-primary/10 p-2 rounded transition-colors"
                          title="View attachments"
                        >
                          <Paperclip className="w-4 h-4 text-primary" />
                          <span className="text-xs font-medium text-garage-text">{record.attachment_count}</span>
                        </button>
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
      </div>
    </>
  )
}
