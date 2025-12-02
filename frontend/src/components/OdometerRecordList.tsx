import { useState, useEffect, useRef, useCallback } from 'react'
import { formatDateForDisplay } from '../utils/dateUtils'
import { Gauge, Plus, Edit, Trash2, Calendar, Download, Upload } from 'lucide-react'
import { toast } from 'sonner'
import type { OdometerRecord } from '../types/odometer'
import api from '../services/api'

interface OdometerRecordListProps {
  vin: string
  onAddClick: () => void
  onEditClick: (record: OdometerRecord) => void
  onRefresh?: () => void
}

export default function OdometerRecordList({ vin, onAddClick, onEditClick, onRefresh }: OdometerRecordListProps) {
  const [records, setRecords] = useState<OdometerRecord[]>([])
  const [latestMileage, setLatestMileage] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<number | null>(null)
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const fetchRecords = useCallback(async () => {
    try {
      const response = await api.get(`/vehicles/${vin}/odometer`)
      setRecords(response.data.records)
      setLatestMileage(response.data.latest_mileage)
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

  const handleExportCSV = async () => {
    setExporting(true)
    try {
      const response = await api.get(`/export/vehicles/${vin}/odometer/csv`, {
        responseType: 'blob'
      })

      // Get the filename from Content-Disposition header
      const contentDisposition = response.headers['content-disposition']
      const filenameMatch = contentDisposition?.match(/filename="(.+)"/)
      const filename = filenameMatch ? filenameMatch[1] : 'odometer_records.csv'

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

      const response = await api.post(`/import/vehicles/${vin}/odometer/csv`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      })

      const result = response.data

      // Show results
      const message = `Import completed:\n✓ ${result.success_count} records imported\n${result.skipped_count > 0 ? `○ ${result.skipped_count} duplicates skipped\n` : ''}${result.error_count > 0 ? `✗ ${result.error_count} errors\n` : ''}`

      if (result.errors && result.errors.length > 0) {
        toast.error(message + '\nErrors:\n' + result.errors.join('\n'))
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
    if (!confirm('Are you sure you want to delete this odometer record?')) {
      return
    }

    setDeleting(recordId)
    try {
      await api.delete(`/vehicles/${vin}/odometer/${recordId}`)

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

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">Loading odometer records...</div>
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
          <Gauge className="w-5 h-5 text-garage-text-muted" />
          <h3 className="text-lg font-semibold text-garage-text">
            Odometer Readings
          </h3>
          <span className="text-sm text-garage-text-muted">({records.length} records)</span>
        </div>
        <div className="flex items-center gap-2">
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
            <span>Add Reading</span>
          </button>
        </div>
      </div>

      {latestMileage !== null && (
        <div className="bg-primary/10 border border-primary rounded-lg p-4">
          <div className="flex items-center gap-3">
            <div className="bg-primary/20 rounded-full p-3">
              <Gauge className="w-6 h-6 text-primary" />
            </div>
            <div>
              <p className="text-sm text-garage-text-muted">Latest Mileage</p>
              <p className="text-2xl font-bold text-garage-text">
                {latestMileage.toLocaleString()} miles
              </p>
            </div>
          </div>
        </div>
      )}

      {records.length === 0 ? (
        <div className="bg-garage-surface border border-garage-border rounded-lg p-8 text-center">
          <Gauge className="w-12 h-12 text-garage-text-muted opacity-50 mx-auto mb-3" />
          <p className="text-garage-text mb-2">No odometer records yet</p>
          <p className="text-sm text-garage-text-muted mb-4">
            Track your vehicle's mileage over time
          </p>
          <button
            onClick={onAddClick}
            className="inline-flex items-center gap-2 btn btn-primary rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>Add First Reading</span>
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
                    Notes
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-garage-text-muted uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-garage-surface divide-y divide-garage-border">
                {records.map((record) => (
                  <tr key={record.id} className="hover:bg-garage-bg">
                    <td className="px-4 py-3 whitespace-nowrap">
                      <div className="flex items-center gap-2 text-sm text-garage-text">
                        <Calendar className="w-4 h-4 text-garage-text-muted" />
                        {formatDate(record.date)}
                      </div>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <div className="flex items-center gap-2 text-sm font-medium text-garage-text">
                        <Gauge className="w-4 h-4 text-garage-text-muted" />
                        {record.mileage.toLocaleString()} miles
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      {record.notes ? (
                        <div className="text-sm text-garage-text">{record.notes}</div>
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
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
