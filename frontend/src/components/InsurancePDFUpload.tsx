import { useState, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import api from '../services/api'
import { InsurancePDFParseResponse, InsurancePolicyCreate } from '../types/insurance'
import { CloudUpload, X, AlertTriangle, CheckCircle } from 'lucide-react'

/**
 * Parsed-policy field name -> translation key.
 *
 * Domain verified against the `data` block built by parse_insurance_pdf in
 * backend/app/routes/insurance.py (provider, policy_number, policy_type,
 * start_date, end_date, premium_amount, premium_frequency, deductible,
 * coverage_limits, notes), which matches InsurancePDFParseResponse. Keys are
 * explicit literals, never built by interpolation, so
 * scripts/validate-i18n-usage.ts can resolve them statically. A field the
 * backend adds later falls through to humanizeFieldName below so it still
 * renders something readable.
 */
const INSURANCE_FIELD_KEYS: Record<string, string> = {
  provider: 'insuranceFields.provider',
  policy_number: 'insuranceFields.policyNumber',
  policy_type: 'insuranceFields.policyType',
  start_date: 'insuranceFields.startDate',
  end_date: 'insuranceFields.endDate',
  premium_amount: 'insuranceFields.premiumAmount',
  premium_frequency: 'insuranceFields.premiumFrequency',
  deductible: 'insuranceFields.deductible',
  coverage_limits: 'insuranceFields.coverageLimits',
  notes: 'insuranceFields.notes',
}

/** Last-resort label for an unmapped backend field: "policy_number" -> "Policy Number". */
function humanizeFieldName(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())
}

interface InsurancePDFUploadProps {
  vin: string
  onDataExtracted: (data: Partial<InsurancePolicyCreate>) => void
  onClose: () => void
}

export default function InsurancePDFUpload({ vin, onDataExtracted, onClose }: InsurancePDFUploadProps) {
  const { t } = useTranslation('vehicles')
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [parseResult, setParseResult] = useState<InsurancePDFParseResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dragActive, setDragActive] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true)
    } else if (e.type === 'dragleave') {
      setDragActive(false)
    }
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const droppedFile = e.dataTransfer.files[0]
      if (droppedFile.type === 'application/pdf' || droppedFile.name.toLowerCase().endsWith('.pdf')) {
        setFile(droppedFile)
        setError(null)
      } else {
        setError(t('insurancePdfUpload.errorInvalidType'))
      }
    }
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const selectedFile = e.target.files[0]
      if (selectedFile.type === 'application/pdf' || selectedFile.name.toLowerCase().endsWith('.pdf')) {
        setFile(selectedFile)
        setError(null)
      } else {
        setError(t('insurancePdfUpload.errorInvalidType'))
      }
    }
  }

  const handleUpload = async () => {
    if (!file) return

    setUploading(true)
    setError(null)
    setParseResult(null)

    try {
      const formData = new FormData()
      formData.append('file', file)

      const response = await api.post(`/vehicles/${vin}/insurance/parse-pdf`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      })

      setParseResult(response.data)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('insurancePdfUpload.errorParseFailed'))
    } finally {
      setUploading(false)
    }
  }

  const handleUseData = () => {
    if (!parseResult) return

    // Convert parsed data to form data format
    const formData: Partial<InsurancePolicyCreate> = {}

    if (parseResult.data.provider) formData.provider = parseResult.data.provider
    if (parseResult.data.policy_number) formData.policy_number = parseResult.data.policy_number
    if (parseResult.data.policy_type) formData.policy_type = parseResult.data.policy_type
    if (parseResult.data.start_date) formData.start_date = parseResult.data.start_date
    if (parseResult.data.end_date) formData.end_date = parseResult.data.end_date
    if (parseResult.data.premium_amount) formData.premium_amount = parseResult.data.premium_amount
    if (parseResult.data.premium_frequency) formData.premium_frequency = parseResult.data.premium_frequency
    if (parseResult.data.deductible) formData.deductible = parseResult.data.deductible
    if (parseResult.data.coverage_limits) formData.coverage_limits = parseResult.data.coverage_limits
    if (parseResult.data.notes) formData.notes = parseResult.data.notes

    onDataExtracted(formData)
    onClose()
  }

  const getConfidenceBadge = (field: string) => {
    const confidence = parseResult?.confidence[field]
    if (!confidence) return null

    const colors = {
      high: 'bg-green-100 text-green-800',
      medium: 'bg-yellow-100 text-yellow-800',
      low: 'bg-red-100 text-red-800',
    }

    const labels = {
      high: t('insurancePdfUpload.confidenceHigh'),
      medium: t('insurancePdfUpload.confidenceMedium'),
      low: t('insurancePdfUpload.confidenceLow'),
    }

    return (
      <span className={`text-xs px-2 py-1 rounded ${colors[confidence]}`}>
        {labels[confidence]}
      </span>
    )
  }

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center z-50 p-4">
      <div className="bg-garage-surface rounded-lg shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto border border-garage-border">
        {/* Header */}
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border px-6 py-4 flex justify-between items-center rounded-t-lg">
          <h2 className="text-xl font-semibold text-garage-text">
            {t('insurancePdfUpload.title')}
          </h2>
          <button
            onClick={onClose}
            className="text-garage-text-muted hover:text-garage-text"
          >
            <X className="w-6 h-6" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6">
          {!parseResult ? (
            <>
              {/* Upload Area */}
              <div
                className={`border-2 border-dashed rounded-lg p-8 text-center ${
                  dragActive
                    ? 'border-primary bg-primary/5'
                    : 'border-garage-border'
                }`}
                onDragEnter={handleDrag}
                onDragLeave={handleDrag}
                onDragOver={handleDrag}
                onDrop={handleDrop}
              >
                <CloudUpload className="w-12 h-12 mx-auto text-garage-text-muted mb-4" />
                <p className="text-garage-text mb-2">
                  {file ? file.name : t('insurancePdfUpload.dragDrop')}
                </p>
                <p className="text-sm text-garage-text-muted mb-4">
                  {t('insurancePdfUpload.or')}
                </p>
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="btn btn-secondary"
                >
                  {t('insurancePdfUpload.chooseFile')}
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,application/pdf"
                  onChange={handleFileChange}
                  className="hidden"
                />
              </div>

              {file && (
                <div className="mt-4">
                  <button
                    onClick={handleUpload}
                    disabled={uploading}
                    className="btn btn-secondary w-full"
                  >
                    {uploading ? t('insurancePdfUpload.parsing') : t('insurancePdfUpload.parse')}
                  </button>
                </div>
              )}

              {error && (
                <div className="mt-4 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg flex items-start gap-3">
                  <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
                  <p className="text-sm text-red-700 dark:text-red-300">{error}</p>
                </div>
              )}
            </>
          ) : (
            <>
              {/* Parse Results */}
              <div className="space-y-4">
                {/* Success Message */}
                <div className="p-4 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg flex items-start gap-3">
                  <CheckCircle className="w-5 h-5 text-green-600 dark:text-green-400 flex-shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <p className="text-sm font-medium text-green-700 dark:text-green-300">
                      {t('insurancePdfUpload.parseSuccess')}
                    </p>
                    {parseResult.vehicles_found.length > 0 && (
                      <p className="text-sm text-green-600 dark:text-green-400 mt-1">
                        {t('insurancePdfUpload.vehiclesFound', {
                          count: parseResult.vehicles_found.length,
                          vehicles: parseResult.vehicles_found.join(', '),
                        })}
                      </p>
                    )}
                  </div>
                </div>

                {/* Warnings */}
                {parseResult.warnings.length > 0 && (
                  <div className="p-4 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg">
                    <div className="flex items-start gap-3">
                      <AlertTriangle className="w-5 h-5 text-yellow-600 dark:text-yellow-400 flex-shrink-0 mt-0.5" />
                      <div>
                        <p className="text-sm font-medium text-yellow-700 dark:text-yellow-300 mb-2">
                          {t('insurancePdfUpload.warnings')}
                        </p>
                        <ul className="text-sm text-yellow-600 dark:text-yellow-400 space-y-1">
                          {parseResult.warnings.map((warning, idx) => (
                            <li key={idx}>• {warning}</li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  </div>
                )}

                {/* Extracted Data */}
                <div className="bg-garage-bg border border-garage-border rounded-lg p-4">
                  <h3 className="text-sm font-semibold text-garage-text mb-3">
                    {t('insurancePdfUpload.extractedData')}
                  </h3>
                  <div className="space-y-2 text-sm">
                    {Object.entries(parseResult.data).map(([key, value]) => {
                      if (!value) return null
                      const labelKey = INSURANCE_FIELD_KEYS[key]
                      const label = labelKey ? t(labelKey) : humanizeFieldName(key)
                      return (
                        <div key={key} className="flex justify-between items-start py-2 border-b border-garage-border last:border-0">
                          <span className="text-garage-text-muted font-medium">
                            {label}:
                          </span>
                          <div className="flex items-center gap-2">
                            <span className="text-garage-text text-right">
                              {value}
                            </span>
                            {getConfidenceBadge(key)}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>

                {/* Actions */}
                <div className="flex gap-3">
                  <button
                    onClick={() => {
                      setParseResult(null)
                      setFile(null)
                    }}
                    className="btn btn-secondary flex-1"
                  >
                    {t('insurancePdfUpload.uploadDifferent')}
                  </button>
                  <button
                    onClick={handleUseData}
                    className="btn btn-primary rounded-lg flex-1"
                  >
                    {t('insurancePdfUpload.useThisData')}
                  </button>
                </div>

                <p className="text-xs text-garage-text-muted text-center">
                  {t('insurancePdfUpload.reviewHint')}
                </p>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
