import { useState, useRef } from 'react'
import api from '../services/api'
import { InsurancePDFParseResponse, InsurancePolicyCreate } from '../types/insurance'
import { CloudUpload, X, AlertTriangle, CheckCircle } from 'lucide-react'

interface InsurancePDFUploadProps {
  vin: string
  onDataExtracted: (data: Partial<InsurancePolicyCreate>) => void
  onClose: () => void
}

export default function InsurancePDFUpload({ vin, onDataExtracted, onClose }: InsurancePDFUploadProps) {
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
        setError('Please upload a PDF file')
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
        setError('Please upload a PDF file')
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
      setError(err instanceof Error ? err.message : 'Failed to parse PDF')
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

    return (
      <span className={`text-xs px-2 py-1 rounded ${colors[confidence]}`}>
        {confidence}
      </span>
    )
  }

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center z-50 p-4">
      <div className="bg-garage-surface rounded-lg shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto border border-garage-border">
        {/* Header */}
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border px-6 py-4 flex justify-between items-center rounded-t-lg">
          <h2 className="text-xl font-semibold text-garage-text">
            Import Insurance Policy from PDF
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
                  {file ? file.name : 'Drag and drop your insurance PDF here'}
                </p>
                <p className="text-sm text-garage-text-muted mb-4">
                  or
                </p>
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="btn btn-secondary"
                >
                  Choose File
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
                    {uploading ? 'Parsing PDF...' : 'Parse PDF'}
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
                      PDF parsed successfully!
                    </p>
                    {parseResult.vehicles_found.length > 0 && (
                      <p className="text-sm text-green-600 dark:text-green-400 mt-1">
                        Found {parseResult.vehicles_found.length} vehicle(s): {parseResult.vehicles_found.join(', ')}
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
                          Warnings:
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
                <div className="bg-garage-background border border-garage-border rounded-lg p-4">
                  <h3 className="text-sm font-semibold text-garage-text mb-3">
                    Extracted Data
                  </h3>
                  <div className="space-y-2 text-sm">
                    {Object.entries(parseResult.data).map(([key, value]) => {
                      if (!value) return null
                      const label = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())
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
                    Upload Different PDF
                  </button>
                  <button
                    onClick={handleUseData}
                    className="btn btn-primary rounded-lg flex-1"
                  >
                    Use This Data
                  </button>
                </div>

                <p className="text-xs text-garage-text-muted text-center">
                  You can review and edit all fields before saving the policy
                </p>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
