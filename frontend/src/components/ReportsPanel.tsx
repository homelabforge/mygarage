import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FileText, Download, Calendar, FileSpreadsheet } from 'lucide-react'
import { toast } from 'sonner'
import api from '../services/api'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'
import { Button, Field, Input, Select, Card } from './ui'

interface ReportsPanelProps {
  vin: string
}

export default function ReportsPanel({ vin }: ReportsPanelProps) {
  const { t } = useTranslation('analytics')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [selectedYear, setSelectedYear] = useState(new Date().getFullYear())
  const [isGenerating, setIsGenerating] = useState(false)
  const { currencyCode, locale } = useCurrencyPreference()

  const currentYear = new Date().getFullYear()
  const years = Array.from({ length: 10 }, (_, i) => currentYear - i)

  const handleDownloadPDF = async (reportType: string) => {
    setIsGenerating(true)
    try {
      let url: string
      if (reportType === 'sale-history') {
        url = `/vehicles/${vin}/reports/sale-history-pdf`
      } else {
        const params = new URLSearchParams()
        if (reportType === 'service-history') {
          if (startDate) params.set('start_date', startDate)
          if (endDate) params.set('end_date', endDate)
        } else {
          params.set('year', String(selectedYear))
        }
        params.set('currency_code', currencyCode)
        params.set('locale', locale)
        url = `/vehicles/${vin}/reports/${reportType}-pdf?${params.toString()}`
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
      const message = error instanceof Error ? error.message : t('reports.pdfError')
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
      const message = error instanceof Error ? error.message : t('reports.csvError')
      toast.error(message)
    } finally {
      setIsGenerating(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-text">{t('reports.title')}</h2>
      </div>

      {/* Date Range Selector */}
      <Card>
        <h3 className="text-lg font-semibold text-text mb-4 flex items-center gap-2">
          <Calendar aria-hidden="true" className="w-5 h-5 text-(--accent-fg)" />
          {t('reports.dateRangeTitle')}
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field id="report-start-date" label={t('reports.startDate')}>
            <Input id="report-start-date" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </Field>
          <Field id="report-end-date" label={t('reports.endDate')}>
            <Input id="report-end-date" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </Field>
        </div>
      </Card>

      {/* PDF Reports */}
      <Card>
        <h3 className="text-lg font-semibold text-text mb-4 flex items-center gap-2">
          <FileText aria-hidden="true" className="w-5 h-5 text-danger" />
          {t('reports.pdfReports')}
        </h3>
        <div className="space-y-4">
          {/* Service History Report */}
          <div className="flex items-center justify-between p-4 bg-surface-2 border border-border rounded-lg hover:border-(--accent-line) transition-colors">
            <div className="flex-1">
              <h4 className="font-medium text-text">{t('reports.serviceHistoryTitle')}</h4>
              <p className="text-sm text-text-mute mt-1">
                {t('reports.serviceHistoryDesc')}{' '}
                {startDate || endDate ? t('reports.rangeCustom') : t('reports.rangeAll')}
              </p>
            </div>
            <Button variant="primary" icon={Download} onClick={() => handleDownloadPDF('service-history')} disabled={isGenerating} aria-label={t('reports.downloadPdf')} className="ml-4">
              <span className="hidden sm:inline">{t('reports.downloadPdf')}</span>
            </Button>
          </div>

          {/* Annual Cost Summary */}
          <div className="flex items-center justify-between p-4 bg-surface-2 border border-border rounded-lg hover:border-(--accent-line) transition-colors">
            <div className="flex-1">
              <h4 className="font-medium text-text">{t('reports.annualCostTitle')}</h4>
              <p className="text-sm text-text-mute mt-1">
                {t('reports.annualCostDesc')}
              </p>
              <div className="mt-2">
                <Select
                  value={selectedYear}
                  onChange={(e) => setSelectedYear(Number(e.target.value))}
                  aria-label={t('reports.selectYear')}
                  options={years.map((year) => ({ value: String(year), label: String(year) }))}
                />
              </div>
            </div>
            <Button variant="primary" icon={Download} onClick={() => handleDownloadPDF('cost-summary')} disabled={isGenerating} aria-label={t('reports.downloadPdf')} className="ml-4">
              <span className="hidden sm:inline">{t('reports.downloadPdf')}</span>
            </Button>
          </div>

          {/* Tax Deduction Report */}
          <div className="flex items-center justify-between p-4 bg-surface-2 border border-border rounded-lg hover:border-(--accent-line) transition-colors">
            <div className="flex-1">
              <h4 className="font-medium text-text">{t('reports.taxDeductionTitle')}</h4>
              <p className="text-sm text-text-mute mt-1">
                {t('reports.taxDeductionDesc')}
              </p>
              <div className="mt-2">
                <Select
                  value={selectedYear}
                  onChange={(e) => setSelectedYear(Number(e.target.value))}
                  aria-label={t('reports.selectYear')}
                  options={years.map((year) => ({ value: String(year), label: String(year) }))}
                />
              </div>
            </div>
            <Button variant="primary" icon={Download} onClick={() => handleDownloadPDF('tax-deduction')} disabled={isGenerating} aria-label={t('reports.downloadPdf')} className="ml-4">
              <span className="hidden sm:inline">{t('reports.downloadPdf')}</span>
            </Button>
          </div>

          {/* Sale History (sanitized) */}
          <div className="flex items-center justify-between p-4 bg-surface-2 border border-border rounded-lg hover:border-(--accent-line) transition-colors">
            <div className="flex-1">
              <h4 className="font-medium text-text">{t('reports.saleHistoryTitle')}</h4>
              <p className="text-sm text-text-mute mt-1">
                {t('reports.saleHistoryDesc')}
              </p>
            </div>
            <Button
              variant="primary"
              icon={Download}
              onClick={() => handleDownloadPDF('sale-history')}
              disabled={isGenerating}
              aria-label={t('reports.saleHistoryTitle')}
              className="ml-4"
            >
              <span className="hidden sm:inline">{t('reports.downloadPdf')}</span>
            </Button>
          </div>
        </div>
      </Card>

      {/* CSV Exports */}
      <Card>
        <h3 className="text-lg font-semibold text-text mb-4 flex items-center gap-2">
          <FileSpreadsheet aria-hidden="true" className="w-5 h-5 text-success" />
          {t('reports.csvExports')}
        </h3>
        <div className="space-y-4">
          {/* Service History CSV */}
          <div className="flex items-center justify-between p-4 bg-surface-2 border border-border rounded-lg hover:border-(--accent-line) transition-colors">
            <div className="flex-1">
              <h4 className="font-medium text-text">{t('reports.serviceHistoryCsvTitle')}</h4>
              <p className="text-sm text-text-mute mt-1">
                {t('reports.serviceHistoryCsvDesc')}{' '}
                {startDate || endDate ? t('reports.rangeCustom') : t('reports.rangeAll')}
              </p>
            </div>
            <Button variant="primary" icon={Download} onClick={() => handleDownloadCSV('service-history')} disabled={isGenerating} aria-label={t('reports.exportCsv')} className="ml-4">
              <span className="hidden sm:inline">{t('reports.exportCsv')}</span>
            </Button>
          </div>

          {/* All Records CSV */}
          <div className="flex items-center justify-between p-4 bg-surface-2 border border-border rounded-lg hover:border-(--accent-line) transition-colors">
            <div className="flex-1">
              <h4 className="font-medium text-text">{t('reports.allRecordsCsvTitle')}</h4>
              <p className="text-sm text-text-mute mt-1">
                {t('reports.allRecordsCsvDesc')}
              </p>
              <div className="mt-2">
                <Select
                  value={selectedYear}
                  onChange={(e) => setSelectedYear(Number(e.target.value))}
                  aria-label={t('reports.selectYear')}
                  placeholder={t('reports.allYears')}
                  options={years.map((year) => ({ value: String(year), label: String(year) }))}
                />
              </div>
            </div>
            <Button variant="primary" icon={Download} onClick={() => handleDownloadCSV('all-records')} disabled={isGenerating} aria-label={t('reports.exportCsv')} className="ml-4">
              <span className="hidden sm:inline">{t('reports.exportCsv')}</span>
            </Button>
          </div>
        </div>
      </Card>

      {isGenerating && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-surface rounded-lg p-6 max-w-sm border border-border">
            <div className="flex items-center gap-3">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-(--accent-solid)"></div>
              <p className="text-text">{t('reports.generating')}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
