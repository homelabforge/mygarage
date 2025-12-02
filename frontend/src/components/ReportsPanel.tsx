import { useState } from 'react'
import { FileText, Download, Calendar, FileSpreadsheet } from 'lucide-react'
import { toast } from 'sonner'
import api from '../services/api'

interface ReportsPanelProps {
  vin: string
}

export default function ReportsPanel({ vin }: ReportsPanelProps) {
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [selectedYear, setSelectedYear] = useState(new Date().getFullYear())
  const [isGenerating, setIsGenerating] = useState(false)

  const currentYear = new Date().getFullYear()
  const years = Array.from({ length: 10 }, (_, i) => currentYear - i)

  const handleDownloadPDF = async (reportType: string) => {
    setIsGenerating(true)
    try {
      let url = `/vehicles/${vin}/reports/${reportType}-pdf?`

      if (reportType === 'service-history') {
        if (startDate) url += `start_date=${startDate}&`
        if (endDate) url += `end_date=${endDate}&`
      } else {
        url += `year=${selectedYear}`
      }

      const response = await api.get(url, { responseType: 'blob' })

      const blob = response.data
      const downloadUrl = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = downloadUrl
      a.download = `${reportType}_${vin}_${Date.now()}.pdf`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(downloadUrl)
    } catch (error) {
      console.error('PDF generation error:', error)
      const message = error instanceof Error ? error.message : 'Failed to generate report'
      toast.error(message)
    } finally {
      setIsGenerating(false)
    }
  }

  const handleDownloadCSV = async (reportType: string) => {
    setIsGenerating(true)
    try {
      let url = `/vehicles/${vin}/reports/${reportType}-csv?`

      if (reportType === 'service-history') {
        if (startDate) url += `start_date=${startDate}&`
        if (endDate) url += `end_date=${endDate}&`
      } else if (reportType === 'all-records') {
        url += `year=${selectedYear}`
      }

      const response = await api.get(url, { responseType: 'blob' })

      const blob = response.data
      const downloadUrl = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = downloadUrl
      a.download = `${reportType}_${vin}_${Date.now()}.csv`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(downloadUrl)
    } catch (error) {
      console.error('CSV export error:', error)
      const message = error instanceof Error ? error.message : 'Failed to export data'
      toast.error(message)
    } finally {
      setIsGenerating(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-garage-text">Reports & Export</h2>
      </div>

      {/* Date Range Selector */}
      <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
        <h3 className="text-lg font-semibold text-garage-text mb-4 flex items-center gap-2">
          <Calendar className="w-5 h-5 text-primary-500" />
          Date Range Selection
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-garage-text mb-2">
              Start Date
            </label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-garage-text mb-2">
              End Date
            </label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
          </div>
        </div>
      </div>

      {/* PDF Reports */}
      <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
        <h3 className="text-lg font-semibold text-garage-text mb-4 flex items-center gap-2">
          <FileText className="w-5 h-5 text-danger-500" />
          PDF Reports
        </h3>
        <div className="space-y-4">
          {/* Service History Report */}
          <div className="flex items-center justify-between p-4 bg-garage-bg border border-garage-border rounded-lg hover:border-primary-500 transition-colors">
            <div className="flex-1">
              <h4 className="font-medium text-garage-text">Service History Report</h4>
              <p className="text-sm text-garage-text-muted mt-1">
                Complete service and maintenance history
                {startDate || endDate ? ' (custom date range)' : ' (all records)'}
              </p>
            </div>
            <button
              onClick={() => handleDownloadPDF('service-history')}
              disabled={isGenerating}
              className="ml-4 flex items-center gap-2 px-4 py-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Download className="w-4 h-4" />
              <span className="hidden sm:inline">Download PDF</span>
            </button>
          </div>

          {/* Annual Cost Summary */}
          <div className="flex items-center justify-between p-4 bg-garage-bg border border-garage-border rounded-lg hover:border-primary-500 transition-colors">
            <div className="flex-1">
              <h4 className="font-medium text-garage-text">Annual Cost Summary</h4>
              <p className="text-sm text-garage-text-muted mt-1">
                Breakdown of all expenses by category
              </p>
              <div className="mt-2">
                <select
                  value={selectedYear}
                  onChange={(e) => setSelectedYear(Number(e.target.value))}
                  className="px-3 py-1 bg-garage-surface border border-garage-border rounded text-garage-text text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                >
                  {years.map(year => (
                    <option key={year} value={year}>{year}</option>
                  ))}
                </select>
              </div>
            </div>
            <button
              onClick={() => handleDownloadPDF('cost-summary')}
              disabled={isGenerating}
              className="ml-4 flex items-center gap-2 px-4 py-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Download className="w-4 h-4" />
              <span className="hidden sm:inline">Download PDF</span>
            </button>
          </div>

          {/* Tax Deduction Report */}
          <div className="flex items-center justify-between p-4 bg-garage-bg border border-garage-border rounded-lg hover:border-primary-500 transition-colors">
            <div className="flex-1">
              <h4 className="font-medium text-garage-text">Tax Deduction Report</h4>
              <p className="text-sm text-garage-text-muted mt-1">
                Potentially deductible expenses (consult tax professional)
              </p>
              <div className="mt-2">
                <select
                  value={selectedYear}
                  onChange={(e) => setSelectedYear(Number(e.target.value))}
                  className="px-3 py-1 bg-garage-surface border border-garage-border rounded text-garage-text text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                >
                  {years.map(year => (
                    <option key={year} value={year}>{year}</option>
                  ))}
                </select>
              </div>
            </div>
            <button
              onClick={() => handleDownloadPDF('tax-deduction')}
              disabled={isGenerating}
              className="ml-4 flex items-center gap-2 px-4 py-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Download className="w-4 h-4" />
              <span className="hidden sm:inline">Download PDF</span>
            </button>
          </div>
        </div>
      </div>

      {/* CSV Exports */}
      <div className="bg-garage-surface border border-garage-border rounded-lg p-6">
        <h3 className="text-lg font-semibold text-garage-text mb-4 flex items-center gap-2">
          <FileSpreadsheet className="w-5 h-5 text-success-500" />
          CSV Exports
        </h3>
        <div className="space-y-4">
          {/* Service History CSV */}
          <div className="flex items-center justify-between p-4 bg-garage-bg border border-garage-border rounded-lg hover:border-primary-500 transition-colors">
            <div className="flex-1">
              <h4 className="font-medium text-garage-text">Service History (CSV)</h4>
              <p className="text-sm text-garage-text-muted mt-1">
                Export service records to spreadsheet
                {startDate || endDate ? ' (custom date range)' : ' (all records)'}
              </p>
            </div>
            <button
              onClick={() => handleDownloadCSV('service-history')}
              disabled={isGenerating}
              className="ml-4 flex items-center gap-2 px-4 py-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Download className="w-4 h-4" />
              <span className="hidden sm:inline">Export CSV</span>
            </button>
          </div>

          {/* All Records CSV */}
          <div className="flex items-center justify-between p-4 bg-garage-bg border border-garage-border rounded-lg hover:border-primary-500 transition-colors">
            <div className="flex-1">
              <h4 className="font-medium text-garage-text">All Records (CSV)</h4>
              <p className="text-sm text-garage-text-muted mt-1">
                Export all maintenance records (service, fuel, collisions, upgrades)
              </p>
              <div className="mt-2">
                <select
                  value={selectedYear}
                  onChange={(e) => setSelectedYear(Number(e.target.value))}
                  className="px-3 py-1 bg-garage-surface border border-garage-border rounded text-garage-text text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
                >
                  <option value="">All Years</option>
                  {years.map(year => (
                    <option key={year} value={year}>{year}</option>
                  ))}
                </select>
              </div>
            </div>
            <button
              onClick={() => handleDownloadCSV('all-records')}
              disabled={isGenerating}
              className="ml-4 flex items-center gap-2 px-4 py-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Download className="w-4 h-4" />
              <span className="hidden sm:inline">Export CSV</span>
            </button>
          </div>
        </div>
      </div>

      {isGenerating && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-garage-surface rounded-lg p-6 max-w-sm">
            <div className="flex items-center gap-3">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div>
              <p className="text-garage-text">Generating report...</p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
