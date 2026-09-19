import { useState, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import api from '../services/api'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import type { InsurancePDFParseResponse } from '../types/insurance'
import { CloudUpload, X, AlertTriangle, CheckCircle } from 'lucide-react'
import { Button, Card, IconButton, Chip } from './ui'
import type { Tone } from './ui'

// LD3: confidence is off-accent (§4.3); high→success, medium→warning, low→danger.
const CONFIDENCE_TONE: Record<'high' | 'medium' | 'low', Tone> = {
  high: 'success',
  medium: 'warning',
  low: 'danger',
}

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

/** Every parser reports the two dates under ONE confidence key, `dates`. */
const CONFIDENCE_ALIAS: Record<string, string> = { start_date: 'dates', end_date: 'dates' }

interface InsurancePDFUploadProps {
  /** The whole parse: the policy-level data AND every vehicle on the document. */
  onDataExtracted: (parsed: InsurancePDFParseResponse) => void
  onClose: () => void
}

export default function InsurancePDFUpload({ onDataExtracted, onClose }: InsurancePDFUploadProps) {
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

      const response = await api.post('/insurance/parse-pdf', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      })

      setParseResult(response.data)
    } catch (err) {
      setError(getActionErrorMessage(err, t('insurancePdfUpload.parseAction')))
    } finally {
      setUploading(false)
    }
  }

  const handleUseData = () => {
    if (!parseResult) return
    onDataExtracted(parseResult)
    onClose()
  }

  const getConfidenceBadge = (field: string) => {
    const confidence = parseResult?.confidence[CONFIDENCE_ALIAS[field] ?? field]
    if (!confidence) return null

    const labels = {
      high: t('insurancePdfUpload.confidenceHigh'),
      medium: t('insurancePdfUpload.confidenceMedium'),
      low: t('insurancePdfUpload.confidenceLow'),
    }

    return <Chip tone={CONFIDENCE_TONE[confidence]}>{labels[confidence]}</Chip>
  }

  return createPortal(
    <div className="fixed inset-0 modal-overlay flex items-center justify-center z-drawer-nested p-4">
      <div className="bg-surface rounded-lg shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto border border-border">
        {/* Header */}
        <div className="sticky top-0 bg-surface border-b border-border px-6 py-4 flex justify-between items-center rounded-t-lg">
          <h2 className="text-xl font-semibold text-text">{t('insurancePdfUpload.title')}</h2>
          <IconButton icon={X} label={t('common:close')} variant="ghost" onClick={onClose} />
        </div>

        {/* Content */}
        <div className="p-6">
          {!parseResult ? (
            <>
              {/* Upload Area (G4b dropzone) */}
              <div
                className={`border-2 border-dashed rounded-lg p-8 text-center ${
                  dragActive ? 'border-(--accent-line) bg-(--accent-soft)' : 'border-border'
                }`}
                onDragEnter={handleDrag}
                onDragLeave={handleDrag}
                onDragOver={handleDrag}
                onDrop={handleDrop}
              >
                <CloudUpload aria-hidden="true" className="w-12 h-12 mx-auto text-text-mute mb-4" />
                <p className="text-text mb-2">{file ? file.name : t('insurancePdfUpload.dragDrop')}</p>
                <p className="text-sm text-text-mute mb-4">{t('insurancePdfUpload.or')}</p>
                {/* B3/M6/G4(b): the Choose-File affordance is a real focusable <Button> that clicks
                    the hidden input's ref — restoring KEYBOARD operability (Tab to the button,
                    Enter/Space opens the native picker), the exact pre-B3 trigger retokenized onto
                    the primitive. A separate sr-only <label htmlFor> gives the input its accessible
                    name so getByLabelText still resolves it (B3). "Retokenize only" does not forbid
                    restoring keyboard access + an accessible name — both are net a11y gains. */}
                <Button type="button" variant="secondary" onClick={() => fileInputRef.current?.click()}>
                  {t('insurancePdfUpload.chooseFile')}
                </Button>
                <label htmlFor="insurance-pdf-file" className="sr-only">
                  {t('insurancePdfUpload.chooseFile')}
                </label>
                <input
                  id="insurance-pdf-file"
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,application/pdf"
                  onChange={handleFileChange}
                  className="hidden"
                />
              </div>

              {file && (
                <div className="mt-4">
                  <Button variant="secondary" className="w-full" loading={uploading} onClick={handleUpload}>
                    {uploading ? t('insurancePdfUpload.parsing') : t('insurancePdfUpload.parse')}
                  </Button>
                </div>
              )}

              {error && (
                <div className="mt-4 p-4 bg-danger/10 border border-danger rounded-lg flex items-start gap-3">
                  <AlertTriangle aria-hidden="true" className="w-5 h-5 text-danger flex-shrink-0 mt-0.5" />
                  <p className="text-sm text-danger">{error}</p>
                </div>
              )}
            </>
          ) : (
            <>
              {/* Parse Results */}
              <div className="space-y-4">
                {/* Success Message (G4e) */}
                <div className="p-4 bg-success/10 border border-success rounded-lg flex items-start gap-3">
                  <CheckCircle aria-hidden="true" className="w-5 h-5 text-success flex-shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <p className="text-sm font-medium text-success">{t('insurancePdfUpload.parseSuccess')}</p>
                  </div>
                </div>

                {/* Warnings (G4e) */}
                {parseResult.warnings.length > 0 && (
                  <div className="p-4 bg-warning/10 border border-warning rounded-lg">
                    <div className="flex items-start gap-3">
                      <AlertTriangle aria-hidden="true" className="w-5 h-5 text-warning flex-shrink-0 mt-0.5" />
                      <div>
                        <p className="text-sm font-medium text-warning mb-2">{t('insurancePdfUpload.warnings')}</p>
                        <ul className="text-sm text-warning space-y-1">
                          {parseResult.warnings.map((warning, idx) => (
                            <li key={idx}>• {warning}</li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  </div>
                )}

                {/* Extracted Data — B6: the real Card API fits (no conditional border, no status
                    tone), so compose <Card>, not a raw bg-surface-2/border/rounded/p-4 copy. Do
                    NOT override its fixed bg/border with competing utilities. padding="sm" ⇒ p-4. */}
                <Card padding="sm">
                  <div className="flex items-center justify-between gap-2 mb-3">
                    <h3 className="text-sm font-semibold text-text">{t('insurancePdfUpload.extractedData')}</h3>
                    {parseResult.parser_used && (
                      <span className="text-xs text-text-mute">
                        {t('insurancePdfUpload.readBy', {
                          parser: parseResult.parser_used,
                          score: Math.round(parseResult.confidence_score),
                        })}
                      </span>
                    )}
                  </div>
                  <div className="space-y-2 text-sm">
                    {Object.entries(parseResult.data).map(([key, value]) => {
                      if (!value) return null
                      const labelKey = INSURANCE_FIELD_KEYS[key]
                      const label = labelKey ? t(labelKey) : humanizeFieldName(key)
                      return (
                        <div key={key} className="flex justify-between items-start py-2 border-b border-border last:border-0">
                          <span className="text-text-mute font-medium">{label}:</span>
                          <div className="flex items-center gap-2">
                            <span className="text-text text-right">{value}</span>
                            {getConfidenceBadge(key)}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </Card>

                {parseResult.vehicles.length > 0 && (
                  <Card padding="sm">
                    <h3 className="text-sm font-semibold text-text mb-3">{t('insurancePdfUpload.vehiclesOnPolicy')}</h3>
                    <ul className="space-y-2 text-sm">
                      {parseResult.vehicles.map((vehicle) => (
                        <li key={vehicle.vin} className="flex justify-between items-center gap-2">
                          <span className="text-text">{vehicle.vehicle_name ?? vehicle.vin}</span>
                          <Chip tone={vehicle.matched ? 'success' : 'muted'}>
                            {vehicle.matched
                              ? t('insurancePdfUpload.vehicleMatched')
                              : t('insurancePdfUpload.vehicleNotInGarage')}
                          </Chip>
                        </li>
                      ))}
                    </ul>
                  </Card>
                )}

                {/* Actions */}
                <div className="flex gap-3">
                  <Button variant="secondary" className="flex-1" onClick={() => { setParseResult(null); setFile(null) }}>
                    {t('insurancePdfUpload.uploadDifferent')}
                  </Button>
                  <Button variant="primary" className="flex-1" onClick={handleUseData}>
                    {t('insurancePdfUpload.useThisData')}
                  </Button>
                </div>

                <p className="text-xs text-text-mute text-center">{t('insurancePdfUpload.reviewHint')}</p>
              </div>
            </>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
