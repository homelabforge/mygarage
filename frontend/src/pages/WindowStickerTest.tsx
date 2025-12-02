/**
 * Window Sticker OCR Test Page
 * Allows testing window sticker extraction without saving
 */

import { useState, useCallback, useEffect } from 'react'
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
  const { vin } = useParams<{ vin: string }>()
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
        toast.success('Extraction completed successfully')
      } else {
        toast.error(response.data.error || 'Extraction failed')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } }
      toast.error(err.response?.data?.detail || 'Failed to test extraction')
    } finally {
      setLoading(false)
    }
  }

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
    toast.success('Copied to clipboard')
  }

  const formatCurrency = (value: string | null) => {
    if (!value) return '-'
    const num = parseFloat(value)
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(num)
  }

  return (
    <div className="min-h-screen bg-garage-bg p-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex items-center gap-4 mb-6">
          <Link
            to={`/vehicles/${vin}`}
            className="p-2 rounded-lg bg-garage-card hover:bg-garage-card-hover transition-colors"
          >
            <ArrowLeft className="w-5 h-5 text-garage-text" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-garage-text">
              Window Sticker OCR Test
            </h1>
            <p className="text-garage-text-muted text-sm">
              VIN: {vin}
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Upload Section */}
          <div className="bg-garage-card rounded-xl p-6 border border-garage-border">
            <h2 className="text-lg font-semibold text-garage-text mb-4 flex items-center gap-2">
              <Upload className="w-5 h-5" />
              Upload Window Sticker
            </h2>

            {/* Drop Zone */}
            <div
              onDrop={handleDrop}
              onDragOver={(e) => e.preventDefault()}
              className={`
                relative border-2 border-dashed rounded-lg p-8 text-center transition-colors
                ${file ? 'border-garage-accent bg-garage-accent/10' : 'border-garage-border hover:border-garage-accent/50'}
              `}
            >
              {file ? (
                <div className="flex flex-col items-center gap-2">
                  <FileText className="w-12 h-12 text-garage-accent" />
                  <p className="text-garage-text font-medium">{file.name}</p>
                  <p className="text-garage-text-muted text-sm">
                    {(file.size / 1024 / 1024).toFixed(2)} MB
                  </p>
                  <button
                    onClick={() => setFile(null)}
                    className="text-red-500 text-sm hover:underline"
                  >
                    Remove
                  </button>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-2">
                  <Upload className="w-12 h-12 text-garage-text-muted" />
                  <p className="text-garage-text">
                    Drop file here or click to upload
                  </p>
                  <p className="text-garage-text-muted text-sm">
                    PDF, JPG, or PNG (max 10MB)
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
                Parser (optional - auto-detected from VIN)
              </label>
              <select
                value={selectedParser}
                onChange={(e) => setSelectedParser(e.target.value)}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-garage-accent"
              >
                <option value="">Auto-detect</option>
                {parsers.map((p) => (
                  <option key={p.manufacturer} value={p.manufacturer}>
                    {p.parser_class} ({p.supported_makes.join(', ') || 'Generic'})
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
                  ? 'bg-garage-accent text-white hover:bg-garage-accent-hover'
                  : 'bg-garage-border text-garage-text-muted cursor-not-allowed'
                }
              `}
            >
              {loading ? 'Processing...' : 'Test Extraction'}
            </button>
          </div>

          {/* Results Section */}
          <div className="bg-garage-card rounded-xl p-6 border border-garage-border">
            <h2 className="text-lg font-semibold text-garage-text mb-4 flex items-center gap-2">
              <FileText className="w-5 h-5" />
              Extraction Results
            </h2>

            {!result ? (
              <div className="text-center py-12 text-garage-text-muted">
                Upload a window sticker and click "Test Extraction" to see results
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
                    {result.success ? 'Extraction Successful' : 'Extraction Failed'}
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
                    <span className="text-garage-text-muted">Parser:</span>
                    <span className="ml-2 text-garage-text">{result.parser_name || '-'}</span>
                  </div>
                  <div>
                    <span className="text-garage-text-muted">Manufacturer:</span>
                    <span className="ml-2 text-garage-text">{result.manufacturer_detected || 'Unknown'}</span>
                  </div>
                  {result.extracted_data && (
                    <div className="col-span-2">
                      <span className="text-garage-text-muted">Confidence:</span>
                      <span className="ml-2 text-garage-text">
                        {result.extracted_data.confidence_score?.toFixed(1)}%
                      </span>
                    </div>
                  )}
                </div>

                {/* Validation Warnings */}
                {result.validation_warnings.length > 0 && (
                  <div className="space-y-2">
                    <h3 className="text-sm font-medium text-yellow-500 flex items-center gap-2">
                      <AlertTriangle className="w-4 h-4" />
                      Validation Warnings
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
                      <h3 className="text-sm font-medium text-garage-text mb-2">Pricing</h3>
                      <div className="grid grid-cols-2 gap-2 text-sm">
                        <div className="flex justify-between p-2 bg-garage-bg rounded">
                          <span className="text-garage-text-muted">Base MSRP:</span>
                          <span className="text-garage-text">{formatCurrency(result.extracted_data.msrp_base)}</span>
                        </div>
                        <div className="flex justify-between p-2 bg-garage-bg rounded">
                          <span className="text-garage-text-muted">Total MSRP:</span>
                          <span className="text-garage-text font-semibold">{formatCurrency(result.extracted_data.msrp_total)}</span>
                        </div>
                        <div className="flex justify-between p-2 bg-garage-bg rounded">
                          <span className="text-garage-text-muted">Options:</span>
                          <span className="text-garage-text">{formatCurrency(result.extracted_data.msrp_options)}</span>
                        </div>
                        <div className="flex justify-between p-2 bg-garage-bg rounded">
                          <span className="text-garage-text-muted">Destination:</span>
                          <span className="text-garage-text">{formatCurrency(result.extracted_data.destination_charge)}</span>
                        </div>
                      </div>
                    </div>

                    {/* Options Detail */}
                    {Object.keys(result.extracted_data.options_detail || {}).length > 0 && (
                      <div>
                        <h3 className="text-sm font-medium text-garage-text mb-2">Individual Options</h3>
                        <div className="space-y-1 max-h-40 overflow-y-auto">
                          {Object.entries(result.extracted_data.options_detail).map(([name, price]) => (
                            <div key={name} className="flex justify-between text-sm p-2 bg-garage-bg rounded">
                              <span className="text-garage-text truncate mr-2">{name}</span>
                              <span className="text-garage-accent whitespace-nowrap">{formatCurrency(price)}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Colors & Specs */}
                    <div>
                      <h3 className="text-sm font-medium text-garage-text mb-2">Vehicle Details</h3>
                      <div className="grid grid-cols-1 gap-2 text-sm">
                        {result.extracted_data.exterior_color && (
                          <div className="flex justify-between p-2 bg-garage-bg rounded">
                            <span className="text-garage-text-muted">Exterior:</span>
                            <span className="text-garage-text">{result.extracted_data.exterior_color}</span>
                          </div>
                        )}
                        {result.extracted_data.interior_color && (
                          <div className="flex justify-between p-2 bg-garage-bg rounded">
                            <span className="text-garage-text-muted">Interior:</span>
                            <span className="text-garage-text">{result.extracted_data.interior_color}</span>
                          </div>
                        )}
                        {result.extracted_data.engine_description && (
                          <div className="flex justify-between p-2 bg-garage-bg rounded">
                            <span className="text-garage-text-muted">Engine:</span>
                            <span className="text-garage-text text-right">{result.extracted_data.engine_description}</span>
                          </div>
                        )}
                        {result.extracted_data.transmission_description && (
                          <div className="flex justify-between p-2 bg-garage-bg rounded">
                            <span className="text-garage-text-muted">Transmission:</span>
                            <span className="text-garage-text text-right">{result.extracted_data.transmission_description}</span>
                          </div>
                        )}
                        {result.extracted_data.assembly_location && (
                          <div className="flex justify-between p-2 bg-garage-bg rounded">
                            <span className="text-garage-text-muted">Assembly:</span>
                            <span className="text-garage-text">{result.extracted_data.assembly_location}</span>
                          </div>
                        )}
                        {result.extracted_data.extracted_vin && (
                          <div className="flex justify-between p-2 bg-garage-bg rounded">
                            <span className="text-garage-text-muted">Extracted VIN:</span>
                            <span className={`text-garage-text ${result.extracted_data.extracted_vin === vin ? 'text-green-500' : 'text-yellow-500'}`}>
                              {result.extracted_data.extracted_vin}
                              {result.extracted_data.extracted_vin !== vin && ' (mismatch!)'}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Warranty */}
                    {(result.extracted_data.warranty_powertrain || result.extracted_data.warranty_basic) && (
                      <div>
                        <h3 className="text-sm font-medium text-garage-text mb-2">Warranty</h3>
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
                        <h3 className="text-sm font-medium text-garage-text mb-2">Environmental Ratings</h3>
                        <div className="grid grid-cols-2 gap-2 text-sm">
                          {result.extracted_data.environmental_rating_ghg && (
                            <div className="p-2 bg-garage-bg rounded text-center">
                              <div className="text-garage-text-muted">GHG Rating</div>
                              <div className="text-2xl font-bold text-garage-text">{result.extracted_data.environmental_rating_ghg}</div>
                            </div>
                          )}
                          {result.extracted_data.environmental_rating_smog && (
                            <div className="p-2 bg-garage-bg rounded text-center">
                              <div className="text-garage-text-muted">Smog Rating</div>
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
                          className="flex items-center gap-2 text-sm font-medium text-garage-text hover:text-garage-accent"
                        >
                          {showEquipment ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                          Equipment Lists ({(result.extracted_data.standard_equipment?.length || 0) + (result.extracted_data.optional_equipment?.length || 0)} items)
                        </button>
                        {showEquipment && (
                          <div className="mt-2 space-y-4">
                            {result.extracted_data.standard_equipment?.length > 0 && (
                              <div>
                                <h4 className="text-xs font-medium text-garage-text-muted mb-1">Standard Equipment ({result.extracted_data.standard_equipment.length})</h4>
                                <div className="max-h-32 overflow-y-auto space-y-1">
                                  {result.extracted_data.standard_equipment.map((item, i) => (
                                    <div key={i} className="text-xs p-1 bg-garage-bg rounded text-garage-text">{item}</div>
                                  ))}
                                </div>
                              </div>
                            )}
                            {result.extracted_data.optional_equipment?.length > 0 && (
                              <div>
                                <h4 className="text-xs font-medium text-garage-text-muted mb-1">Optional Equipment ({result.extracted_data.optional_equipment.length})</h4>
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
                      className="flex items-center gap-2 text-sm font-medium text-garage-text hover:text-garage-accent"
                    >
                      {showRawText ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                      Raw Extracted Text
                    </button>
                    {showRawText && (
                      <div className="mt-2 relative">
                        <button
                          onClick={() => copyToClipboard(result.raw_text!)}
                          className="absolute top-2 right-2 p-1 bg-garage-card rounded hover:bg-garage-card-hover"
                          title="Copy to clipboard"
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
                    className="flex items-center gap-2 text-sm text-garage-accent hover:underline"
                  >
                    <Download className="w-4 h-4" />
                    Export as JSON
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
