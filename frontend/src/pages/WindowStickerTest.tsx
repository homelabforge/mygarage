/**
 * Window Sticker OCR Test Page
 * Allows testing window sticker extraction without saving
 */

import { useState, useCallback, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams, Link } from 'react-router-dom'
import { toast } from 'sonner'
import {
  ArrowLeft,
  Upload,
  FileText,
  AlertTriangle,
  CheckCircle,
  XCircle,
  ChevronDown,
  ChevronUp,
  Copy,
  Download,
} from 'lucide-react'
import api from '../services/api'
import { formatCurrency } from '../utils/formatUtils'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'
import { getActiveLocale } from '@/constants/i18n'

/**
 * Format a number with a fixed number of fraction digits in the active app
 * locale (not the browser's — those diverge once the user picks a language).
 */
function formatDecimal(value: number, digits: number): string {
  return new Intl.NumberFormat(getActiveLocale(), {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value)
}

interface ExtractedData {
  msrp_base: string | null
  msrp_total: string | null
  msrp_options: string | null
  destination_charge: string | null
  options_detail: Record<string, string>
  packages: Record<string, string[]>
  exterior_color: string | null
  interior_color: string | null
  standard_equipment: string[]
  optional_equipment: string[]
  fuel_economy_city: number | null
  fuel_economy_highway: number | null
  fuel_economy_combined: number | null
  engine_description: string | null
  transmission_description: string | null
  drivetrain: string | null
  wheel_specs: string | null
  tire_specs: string | null
  warranty_powertrain: string | null
  warranty_basic: string | null
  environmental_rating_ghg: string | null
  environmental_rating_smog: string | null
  assembly_location: string | null
  extracted_vin: string | null
  parser_name: string | null
  confidence_score: number
}

interface TestResult {
  success: boolean
  parser_name: string | null
  manufacturer_detected: string | null
  raw_text: string | null
  extracted_data: ExtractedData | null
  validation_warnings: string[]
  error: string | null
}

interface Parser {
  manufacturer: string
  parser_class: string
  supported_makes: string[]
}

export default function WindowStickerTest() {
  const { t } = useTranslation('vehicles')
  const { vin } = useParams<{ vin: string }>()
  const { currencyCode, locale } = useCurrencyPreference()
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<TestResult | null>(null)
  const [parsers, setParsers] = useState<Parser[]>([])
  const [selectedParser, setSelectedParser] = useState<string>('')
  const [showRawText, setShowRawText] = useState(false)
  const [showEquipment, setShowEquipment] = useState(false)

  // Fetch available parsers on mount
  useEffect(() => {
    api.get('/vehicles/window-sticker/parsers')
      .then(res => setParsers(res.data))
      .catch(() => {/* silently fail if parsers endpoint not available */})
  }, [])

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0]
    if (selectedFile) {
      setFile(selectedFile)
      setResult(null)
    }
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    const droppedFile = e.dataTransfer.files[0]
    if (droppedFile) {
      setFile(droppedFile)
      setResult(null)
    }
  }, [])

  const handleTest = async () => {
    if (!file || !vin) return

    setLoading(true)
    try {
      const formData = new FormData()
      formData.append('file', file)

      const url = selectedParser
        ? `/vehicles/${vin}/window-sticker/test?parser=${selectedParser}`
        : `/vehicles/${vin}/window-sticker/test`

      const response = await api.post(url, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })

      setResult(response.data)

      if (response.data.success) {
        toast.success(t('windowSticker.test.extractionCompleted'))
      } else {
        toast.error(response.data.error || t('windowSticker.extractionFailed'))
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } }
      toast.error(err.response?.data?.detail || t('windowSticker.test.testFailed'))
    } finally {
      setLoading(false)
    }
  }

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
    toast.success(t('windowSticker.test.copiedToClipboard'))
  }

  return (
    <div className="min-h-screen bg-garage-bg p-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex items-center gap-4 mb-6">
          <Link
            to={`/vehicles/${vin}`}
            className="p-2 rounded-lg bg-garage-surface hover:bg-garage-surface-light transition-colors"
          >
            <ArrowLeft className="w-5 h-5 text-garage-text" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-garage-text">
              {t('windowSticker.ocrTestTitle')}
            </h1>
            <p className="text-garage-text-muted text-sm">
              {t('windowSticker.test.vinLabel')}: {vin}
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Upload Section */}
          <div className="bg-garage-surface rounded-xl p-6 border border-garage-border">
            <h2 className="text-lg font-semibold text-garage-text mb-4 flex items-center gap-2">
              <Upload className="w-5 h-5" />
              {t('windowSticker.upload')}
            </h2>

            {/* Drop Zone */}
            <div
              onDrop={handleDrop}
              onDragOver={(e) => e.preventDefault()}
              className={`
                relative border-2 border-dashed rounded-lg p-8 text-center transition-colors
                ${file ? 'border-primary bg-primary/10' : 'border-garage-border hover:border-primary/50'}
              `}
            >
              {file ? (
                <div className="flex flex-col items-center gap-2">
                  <FileText className="w-12 h-12 text-primary" />
                  <p className="text-garage-text font-medium">{file.name}</p>
                  <p className="text-garage-text-muted text-sm">
                    {t('windowSticker.test.fileSizeMb', { size: formatDecimal(file.size / 1024 / 1024, 2) })}
                  </p>
                  <button
                    onClick={() => setFile(null)}
                    className="text-red-500 text-sm hover:underline"
                  >
                    {t('common:remove')}
                  </button>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-2">
                  <Upload className="w-12 h-12 text-garage-text-muted" />
                  <p className="text-garage-text">
                    {t('windowSticker.dropOrClick')}
                  </p>
                  <p className="text-garage-text-muted text-sm">
                    {t('windowSticker.fileTypes')}
                  </p>
                </div>
              )}
              <input
                type="file"
                accept=".pdf,.jpg,.jpeg,.png"
                onChange={handleFileChange}
                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
              />
            </div>

            {/* Parser Selection */}
            <div className="mt-4">
              <label className="block text-sm text-garage-text-muted mb-2">
                {t('windowSticker.test.parserSelectLabel')}
              </label>
              <select
                value={selectedParser}
                onChange={(e) => setSelectedParser(e.target.value)}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
              >
                <option value="">{t('windowSticker.test.autoDetect')}</option>
                {parsers.map((p) => (
                  <option key={p.manufacturer} value={p.manufacturer}>
                    {p.parser_class} ({p.supported_makes.join(', ') || t('windowSticker.test.genericParser')})
                  </option>
                ))}
              </select>
            </div>

            {/* Test Button */}
            <button
              onClick={handleTest}
              disabled={!file || loading}
              className={`
                w-full mt-4 py-3 px-4 rounded-lg font-medium transition-colors
                ${file && !loading
                  ? 'bg-primary text-white hover:bg-primary-600'
                  : 'bg-garage-border text-garage-text-muted cursor-not-allowed'
                }
              `}
            >
              {loading ? t('windowSticker.processing') : t('windowSticker.testExtraction')}
            </button>
          </div>

          {/* Results Section */}
          <div className="bg-garage-surface rounded-xl p-6 border border-garage-border">
            <h2 className="text-lg font-semibold text-garage-text mb-4 flex items-center gap-2">
              <FileText className="w-5 h-5" />
              {t('windowSticker.extractionResults')}
            </h2>

            {!result ? (
              <div className="text-center py-12 text-garage-text-muted">
                {t('windowSticker.uploadPrompt')}
              </div>
            ) : (
              <div className="space-y-4">
                {/* Status */}
                <div className={`
                  flex items-center gap-2 p-3 rounded-lg
                  ${result.success ? 'bg-green-500/10 text-green-500' : 'bg-red-500/10 text-red-500'}
                `}>
                  {result.success ? (
                    <CheckCircle className="w-5 h-5" />
                  ) : (
                    <XCircle className="w-5 h-5" />
                  )}
                  <span className="font-medium">
                    {result.success ? t('windowSticker.extractionSuccess') : t('windowSticker.extractionFailed')}
                  </span>
                </div>

                {result.error && (
                  <div className="p-3 rounded-lg bg-red-500/10 text-red-500">
                    {result.error}
                  </div>
                )}

                {/* Parser Info */}
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <span className="text-garage-text-muted">{t('windowSticker.test.parser')}:</span>
                    <span className="ml-2 text-garage-text">{result.parser_name || '-'}</span>
                  </div>
                  <div>
                    <span className="text-garage-text-muted">{t('windowSticker.test.manufacturer')}:</span>
                    <span className="ml-2 text-garage-text">{result.manufacturer_detected || t('windowSticker.test.unknown')}</span>
                  </div>
                  {result.extracted_data && (
                    <div className="col-span-2">
                      <span className="text-garage-text-muted">{t('windowSticker.test.confidence')}:</span>
                      <span className="ml-2 text-garage-text">
                        {t('windowSticker.test.percentValue', {
                          percent: formatDecimal(result.extracted_data.confidence_score ?? 0, 1),
                        })}
                      </span>
                    </div>
                  )}
                </div>

                {/* Validation Warnings */}
                {result.validation_warnings.length > 0 && (
                  <div className="space-y-2">
                    <h3 className="text-sm font-medium text-yellow-500 flex items-center gap-2">
                      <AlertTriangle className="w-4 h-4" />
                      {t('windowSticker.test.validationWarnings')}
                    </h3>
                    {result.validation_warnings.map((warning, i) => (
                      <div key={i} className="text-sm text-yellow-500/80 bg-yellow-500/10 p-2 rounded">
                        {warning}
                      </div>
                    ))}
                  </div>
                )}

                {/* Extracted Data */}
                {result.extracted_data && (
                  <div className="space-y-4">
                    {/* Pricing */}
                    <div>
                      <h3 className="text-sm font-medium text-garage-text mb-2">{t('windowSticker.test.pricing')}</h3>
                      <div className="grid grid-cols-2 gap-2 text-sm">
                        <div className="flex justify-between p-2 bg-garage-bg rounded">
                          <span className="text-garage-text-muted">{t('windowSticker.test.baseMsrp')}:</span>
                          <span className="text-garage-text">{formatCurrency(result.extracted_data.msrp_base, { currencyCode, locale })}</span>
                        </div>
                        <div className="flex justify-between p-2 bg-garage-bg rounded">
                          <span className="text-garage-text-muted">{t('windowSticker.test.totalMsrp')}:</span>
                          <span className="text-garage-text font-semibold">{formatCurrency(result.extracted_data.msrp_total, { currencyCode, locale })}</span>
                        </div>
                        <div className="flex justify-between p-2 bg-garage-bg rounded">
                          <span className="text-garage-text-muted">{t('windowSticker.test.options')}:</span>
                          <span className="text-garage-text">{formatCurrency(result.extracted_data.msrp_options, { currencyCode, locale })}</span>
                        </div>
                        <div className="flex justify-between p-2 bg-garage-bg rounded">
                          <span className="text-garage-text-muted">{t('windowSticker.test.destination')}:</span>
                          <span className="text-garage-text">{formatCurrency(result.extracted_data.destination_charge, { currencyCode, locale })}</span>
                        </div>
                      </div>
                    </div>

                    {/* Options Detail */}
                    {Object.keys(result.extracted_data.options_detail || {}).length > 0 && (
                      <div>
                        <h3 className="text-sm font-medium text-garage-text mb-2">{t('windowSticker.test.individualOptions')}</h3>
                        <div className="space-y-1 max-h-40 overflow-y-auto">
                          {Object.entries(result.extracted_data.options_detail).map(([name, price]) => (
                            <div key={name} className="flex justify-between text-sm p-2 bg-garage-bg rounded">
                              <span className="text-garage-text truncate mr-2">{name}</span>
                              <span className="text-primary whitespace-nowrap">{formatCurrency(price, { currencyCode, locale })}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Colors & Specs */}
                    <div>
                      <h3 className="text-sm font-medium text-garage-text mb-2">{t('windowSticker.test.vehicleDetails')}</h3>
                      <div className="grid grid-cols-1 gap-2 text-sm">
                        {result.extracted_data.exterior_color && (
                          <div className="flex justify-between p-2 bg-garage-bg rounded">
                            <span className="text-garage-text-muted">{t('windowSticker.test.exterior')}:</span>
                            <span className="text-garage-text">{result.extracted_data.exterior_color}</span>
                          </div>
                        )}
                        {result.extracted_data.interior_color && (
                          <div className="flex justify-between p-2 bg-garage-bg rounded">
                            <span className="text-garage-text-muted">{t('windowSticker.test.interior')}:</span>
                            <span className="text-garage-text">{result.extracted_data.interior_color}</span>
                          </div>
                        )}
                        {result.extracted_data.engine_description && (
                          <div className="flex justify-between p-2 bg-garage-bg rounded">
                            <span className="text-garage-text-muted">{t('windowSticker.test.engine')}:</span>
                            <span className="text-garage-text text-right">{result.extracted_data.engine_description}</span>
                          </div>
                        )}
                        {result.extracted_data.transmission_description && (
                          <div className="flex justify-between p-2 bg-garage-bg rounded">
                            <span className="text-garage-text-muted">{t('windowSticker.test.transmission')}:</span>
                            <span className="text-garage-text text-right">{result.extracted_data.transmission_description}</span>
                          </div>
                        )}
                        {result.extracted_data.assembly_location && (
                          <div className="flex justify-between p-2 bg-garage-bg rounded">
                            <span className="text-garage-text-muted">{t('windowSticker.test.assembly')}:</span>
                            <span className="text-garage-text">{result.extracted_data.assembly_location}</span>
                          </div>
                        )}
                        {result.extracted_data.extracted_vin && (
                          <div className="flex justify-between p-2 bg-garage-bg rounded">
                            <span className="text-garage-text-muted">{t('windowSticker.misc.extractedVin')}:</span>
                            <span className={`text-garage-text ${result.extracted_data.extracted_vin === vin ? 'text-green-500' : 'text-yellow-500'}`}>
                              {result.extracted_data.extracted_vin}
                              {result.extracted_data.extracted_vin !== vin && ` ${t('windowSticker.test.vinMismatch')}`}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Warranty */}
                    {(result.extracted_data.warranty_powertrain || result.extracted_data.warranty_basic) && (
                      <div>
                        <h3 className="text-sm font-medium text-garage-text mb-2">{t('windowSticker.test.warranty')}</h3>
                        <div className="space-y-1 text-sm">
                          {result.extracted_data.warranty_powertrain && (
                            <div className="p-2 bg-garage-bg rounded text-garage-text">
                              {result.extracted_data.warranty_powertrain}
                            </div>
                          )}
                          {result.extracted_data.warranty_basic && (
                            <div className="p-2 bg-garage-bg rounded text-garage-text">
                              {result.extracted_data.warranty_basic}
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Environmental Ratings */}
                    {(result.extracted_data.environmental_rating_ghg || result.extracted_data.environmental_rating_smog) && (
                      <div>
                        <h3 className="text-sm font-medium text-garage-text mb-2">{t('windowSticker.test.environmentalRatings')}</h3>
                        <div className="grid grid-cols-2 gap-2 text-sm">
                          {result.extracted_data.environmental_rating_ghg && (
                            <div className="p-2 bg-garage-bg rounded text-center">
                              <div className="text-garage-text-muted">{t('windowSticker.test.ghgRating')}</div>
                              <div className="text-2xl font-bold text-garage-text">{result.extracted_data.environmental_rating_ghg}</div>
                            </div>
                          )}
                          {result.extracted_data.environmental_rating_smog && (
                            <div className="p-2 bg-garage-bg rounded text-center">
                              <div className="text-garage-text-muted">{t('windowSticker.test.smogRating')}</div>
                              <div className="text-2xl font-bold text-garage-text">{result.extracted_data.environmental_rating_smog}</div>
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Equipment Lists (Collapsible) */}
                    {(result.extracted_data.standard_equipment?.length > 0 || result.extracted_data.optional_equipment?.length > 0) && (
                      <div>
                        <button
                          onClick={() => setShowEquipment(!showEquipment)}
                          className="flex items-center gap-2 text-sm font-medium text-garage-text hover:text-primary"
                        >
                          {showEquipment ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                          {t('windowSticker.test.equipmentLists', {
                            count:
                              (result.extracted_data.standard_equipment?.length || 0) +
                              (result.extracted_data.optional_equipment?.length || 0),
                          })}
                        </button>
                        {showEquipment && (
                          <div className="mt-2 space-y-4">
                            {result.extracted_data.standard_equipment?.length > 0 && (
                              <div>
                                <h4 className="text-xs font-medium text-garage-text-muted mb-1">{t('windowSticker.misc.standardEquipmentCount', { count: result.extracted_data.standard_equipment.length })}</h4>
                                <div className="max-h-32 overflow-y-auto space-y-1">
                                  {result.extracted_data.standard_equipment.map((item, i) => (
                                    <div key={i} className="text-xs p-1 bg-garage-bg rounded text-garage-text">{item}</div>
                                  ))}
                                </div>
                              </div>
                            )}
                            {result.extracted_data.optional_equipment?.length > 0 && (
                              <div>
                                <h4 className="text-xs font-medium text-garage-text-muted mb-1">{t('windowSticker.test.optionalEquipmentCount', { count: result.extracted_data.optional_equipment.length })}</h4>
                                <div className="max-h-32 overflow-y-auto space-y-1">
                                  {result.extracted_data.optional_equipment.map((item, i) => (
                                    <div key={i} className="text-xs p-1 bg-garage-bg rounded text-garage-text">{item}</div>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Raw Text (Collapsible) */}
                {result.raw_text && (
                  <div>
                    <button
                      onClick={() => setShowRawText(!showRawText)}
                      className="flex items-center gap-2 text-sm font-medium text-garage-text hover:text-primary"
                    >
                      {showRawText ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                      {t('windowSticker.test.rawExtractedText')}
                    </button>
                    {showRawText && (
                      <div className="mt-2 relative">
                        <button
                          onClick={() => copyToClipboard(result.raw_text!)}
                          className="absolute top-2 right-2 p-1 bg-garage-surface rounded hover:bg-garage-surface-light"
                          title={t('windowSticker.test.copyToClipboard')}
                        >
                          <Copy className="w-4 h-4 text-garage-text-muted" />
                        </button>
                        <pre className="text-xs p-3 bg-garage-bg rounded-lg overflow-auto max-h-48 text-garage-text-muted whitespace-pre-wrap">
                          {result.raw_text}
                        </pre>
                      </div>
                    )}
                  </div>
                )}

                {/* Export JSON */}
                {result.extracted_data && (
                  <button
                    onClick={() => {
                      const blob = new Blob([JSON.stringify(result.extracted_data, null, 2)], { type: 'application/json' })
                      const url = URL.createObjectURL(blob)
                      const a = document.createElement('a')
                      a.href = url
                      a.download = `window_sticker_${vin}.json`
                      a.click()
                    }}
                    className="flex items-center gap-2 text-sm text-primary hover:underline"
                  >
                    <Download className="w-4 h-4" />
                    {t('windowSticker.exportJSON')}
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
