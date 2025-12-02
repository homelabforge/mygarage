import { useState, useRef } from 'react'
import { Upload, X, FileText, DollarSign, Fuel, Edit2, Save, Palette, Shield, Leaf, Cog, Car } from 'lucide-react'
import api from '../services/api'

interface WindowStickerUploadProps {
  vin: string
  onSuccess: () => void
  onClose: () => void
}

interface ExtractedData {
  // Pricing
  msrp_base?: number
  msrp_options?: number
  msrp_total?: number
  destination_charge?: number
  // Fuel economy
  fuel_economy_city?: number
  fuel_economy_highway?: number
  fuel_economy_combined?: number
  // Colors
  exterior_color?: string
  interior_color?: string
  // Vehicle specs
  sticker_engine_description?: string
  sticker_transmission_description?: string
  wheel_specs?: string
  tire_specs?: string
  // Warranty
  warranty_powertrain?: string
  warranty_basic?: string
  // Environmental
  environmental_rating_ghg?: string
  environmental_rating_smog?: string
  // Location & metadata
  assembly_location?: string
  window_sticker_parser_used?: string
  window_sticker_confidence_score?: number
  window_sticker_extracted_vin?: string
  // Equipment (JSON)
  standard_equipment?: { items: string[] }
  optional_equipment?: { items: string[] }
  window_sticker_options_detail?: Record<string, string>
  window_sticker_packages?: Record<string, string>
}

export default function WindowStickerUpload({ vin, onSuccess, onClose }: WindowStickerUploadProps) {
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [extractedData, setExtractedData] = useState<ExtractedData | null>(null)
  const [editMode, setEditMode] = useState(false)
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
      handleFile(e.dataTransfer.files[0])
    }
  }

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      handleFile(e.target.files[0])
    }
  }

  const handleFile = (selectedFile: File) => {
    // Validate file type
    const validTypes = ['application/pdf', 'image/jpeg', 'image/jpg', 'image/png']
    if (!validTypes.includes(selectedFile.type)) {
      setError('Please select a valid file (PDF, JPG, or PNG)')
      return
    }

    // Validate file size (10MB)
    if (selectedFile.size > 10 * 1024 * 1024) {
      setError('File size must be less than 10MB')
      return
    }

    setFile(selectedFile)
    setError(null)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file) return

    setUploading(true)
    setError(null)
    setSuccess(null)

    try {
      const formData = new FormData()
      formData.append('file', file)

      const response = await api.post(`/vehicles/${vin}/window-sticker/upload`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })

      setExtractedData(response.data)
      setSuccess('Window sticker uploaded successfully! Review the extracted data below.')
      setEditMode(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    } finally {
      setUploading(false)
    }
  }

  const handleSaveEdits = async () => {
    if (!extractedData) return

    setUploading(true)
    setError(null)

    try {
      await api.patch(`/vehicles/${vin}/window-sticker/data`, extractedData)

      setSuccess('Window sticker data saved successfully!')
      setTimeout(() => {
        onSuccess()
        onClose()
      }, 1000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    } finally {
      setUploading(false)
    }
  }

  const formatCurrency = (value: number | undefined) => {
    if (value === undefined) return ''
    return value.toString()
  }

  const parseCurrency = (value: string): number | undefined => {
    const parsed = parseFloat(value.replace(/[^0-9.]/g, ''))
    return isNaN(parsed) ? undefined : parsed
  }

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center p-4 z-50 overflow-y-auto">
      <div className="bg-garage-surface rounded-lg shadow-2xl max-w-3xl w-full border border-garage-border my-8">
        <div className="bg-garage-surface border-b border-garage-border px-6 py-4 flex justify-between items-center rounded-t-lg">
          <h2 className="text-xl font-semibold text-garage-text">Upload Window Sticker</h2>
          <button
            onClick={onClose}
            className="text-garage-text-muted hover:text-garage-text"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-6">
          {error && (
            <div className="bg-danger-500/10 border border-danger-500 rounded-lg p-3">
              <p className="text-sm text-danger-500">{error}</p>
            </div>
          )}

          {success && (
            <div className="bg-success-500/10 border border-success-500 rounded-lg p-3">
              <p className="text-sm text-success-500">{success}</p>
            </div>
          )}

          {!extractedData && (
            <>
              <div
                className={`border-2 border-dashed rounded-lg p-12 text-center transition-colors ${
                  dragActive
                    ? 'border-primary bg-primary/10'
                    : 'border-garage-border hover:border-primary/50'
                }`}
                onDragEnter={handleDrag}
                onDragLeave={handleDrag}
                onDragOver={handleDrag}
                onDrop={handleDrop}
              >
                <FileText className="w-12 h-12 text-garage-text-muted mx-auto mb-4" />
                <p className="text-garage-text mb-2">
                  Drag and drop your window sticker here, or click to select
                </p>
                <p className="text-sm text-garage-text-muted mb-4">
                  PDF, JPG, or PNG (max 10MB)
                </p>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="application/pdf,image/jpeg,image/jpg,image/png"
                  onChange={handleFileInput}
                  className="hidden"
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
                >
                  Select File
                </button>
              </div>

              {file && (
                <div className="bg-garage-bg rounded-lg p-4 border border-garage-border">
                  <div className="flex items-center gap-3">
                    <FileText className="w-8 h-8 text-primary" />
                    <div className="flex-1">
                      <p className="text-sm font-medium text-garage-text">{file.name}</p>
                      <p className="text-xs text-garage-text-muted">
                        {(file.size / 1024 / 1024).toFixed(2)} MB
                      </p>
                    </div>
                  </div>
                </div>
              )}

              <div className="flex justify-end gap-3">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 bg-garage-bg border border-garage-border text-garage-text rounded-lg hover:bg-garage-border/50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!file || uploading}
                  className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Upload className="w-4 h-4" />
                  {uploading ? 'Uploading...' : 'Upload & Extract Data'}
                </button>
              </div>
            </>
          )}

          {extractedData && (
            <>
              <div className="bg-garage-bg rounded-lg p-4 border border-garage-border max-h-[60vh] overflow-y-auto">
                <div className="flex items-center justify-between mb-4 sticky top-0 bg-garage-bg pb-2">
                  <div>
                    <h3 className="text-lg font-semibold text-garage-text">Extracted Data</h3>
                    {extractedData.window_sticker_parser_used && (
                      <p className="text-xs text-garage-text-muted">
                        Parser: {extractedData.window_sticker_parser_used}
                        {extractedData.window_sticker_confidence_score && (
                          <span className="ml-2">
                            ({Math.round(Number(extractedData.window_sticker_confidence_score))}% confidence)
                          </span>
                        )}
                      </p>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => setEditMode(!editMode)}
                    className="flex items-center gap-2 px-3 py-1 text-sm bg-garage-surface border border-garage-border text-garage-text rounded hover:bg-garage-border/50 transition-colors"
                  >
                    <Edit2 className="w-4 h-4" />
                    {editMode ? 'View Mode' : 'Edit Mode'}
                  </button>
                </div>

                <div className="space-y-6">
                  {/* MSRP Section */}
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-garage-text font-medium">
                      <DollarSign className="w-5 h-5 text-primary" />
                      <span>MSRP Pricing</span>
                    </div>

                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 ml-7">
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">Base Price</label>
                        <input
                          type="text"
                          value={formatCurrency(extractedData.msrp_base)}
                          onChange={(e) => setExtractedData({
                            ...extractedData,
                            msrp_base: parseCurrency(e.target.value)
                          })}
                          disabled={!editMode}
                          placeholder="91,860"
                          className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">Options</label>
                        <input
                          type="text"
                          value={formatCurrency(extractedData.msrp_options)}
                          onChange={(e) => setExtractedData({
                            ...extractedData,
                            msrp_options: parseCurrency(e.target.value)
                          })}
                          disabled={!editMode}
                          placeholder="11,055"
                          className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">Destination</label>
                        <input
                          type="text"
                          value={formatCurrency(extractedData.destination_charge)}
                          onChange={(e) => setExtractedData({
                            ...extractedData,
                            destination_charge: parseCurrency(e.target.value)
                          })}
                          disabled={!editMode}
                          placeholder="2,095"
                          className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">Total MSRP</label>
                        <input
                          type="text"
                          value={formatCurrency(extractedData.msrp_total)}
                          onChange={(e) => setExtractedData({
                            ...extractedData,
                            msrp_total: parseCurrency(e.target.value)
                          })}
                          disabled={!editMode}
                          placeholder="102,915"
                          className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                        />
                      </div>
                    </div>
                  </div>

                  {/* Colors Section */}
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-garage-text font-medium">
                      <Palette className="w-5 h-5 text-primary" />
                      <span>Colors</span>
                    </div>

                    <div className="grid grid-cols-2 gap-3 ml-7">
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">Exterior Color</label>
                        <input
                          type="text"
                          value={extractedData.exterior_color || ''}
                          onChange={(e) => setExtractedData({
                            ...extractedData,
                            exterior_color: e.target.value || undefined
                          })}
                          disabled={!editMode}
                          placeholder="Diamond Black Crystal Pearl"
                          className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">Interior Color</label>
                        <input
                          type="text"
                          value={extractedData.interior_color || ''}
                          onChange={(e) => setExtractedData({
                            ...extractedData,
                            interior_color: e.target.value || undefined
                          })}
                          disabled={!editMode}
                          placeholder="Black"
                          className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                        />
                      </div>
                    </div>
                  </div>

                  {/* Vehicle Specs Section */}
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-garage-text font-medium">
                      <Cog className="w-5 h-5 text-primary" />
                      <span>Vehicle Specifications</span>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 ml-7">
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">Engine</label>
                        <input
                          type="text"
                          value={extractedData.sticker_engine_description || ''}
                          onChange={(e) => setExtractedData({
                            ...extractedData,
                            sticker_engine_description: e.target.value || undefined
                          })}
                          disabled={!editMode}
                          placeholder="6.7L I6 Cummins HO Turbo Diesel"
                          className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">Transmission</label>
                        <input
                          type="text"
                          value={extractedData.sticker_transmission_description || ''}
                          onChange={(e) => setExtractedData({
                            ...extractedData,
                            sticker_transmission_description: e.target.value || undefined
                          })}
                          disabled={!editMode}
                          placeholder="8-Speed Automatic"
                          className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">Wheels</label>
                        <input
                          type="text"
                          value={extractedData.wheel_specs || ''}
                          onChange={(e) => setExtractedData({
                            ...extractedData,
                            wheel_specs: e.target.value || undefined
                          })}
                          disabled={!editMode}
                          placeholder='20" x 8.0" Aluminum'
                          className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">Tires</label>
                        <input
                          type="text"
                          value={extractedData.tire_specs || ''}
                          onChange={(e) => setExtractedData({
                            ...extractedData,
                            tire_specs: e.target.value || undefined
                          })}
                          disabled={!editMode}
                          placeholder="LT285/60R20E"
                          className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                        />
                      </div>
                    </div>
                  </div>

                  {/* Fuel Economy Section */}
                  {(extractedData.fuel_economy_city || extractedData.fuel_economy_highway || extractedData.fuel_economy_combined) && (
                    <div className="space-y-3">
                      <div className="flex items-center gap-2 text-garage-text font-medium">
                        <Fuel className="w-5 h-5 text-primary" />
                        <span>Fuel Economy (MPG)</span>
                      </div>

                      <div className="grid grid-cols-3 gap-3 ml-7">
                        <div>
                          <label className="block text-xs text-garage-text-muted mb-1">City</label>
                          <input
                            type="number"
                            value={extractedData.fuel_economy_city || ''}
                            onChange={(e) => setExtractedData({
                              ...extractedData,
                              fuel_economy_city: e.target.value ? parseInt(e.target.value) : undefined
                            })}
                            disabled={!editMode}
                            placeholder="20"
                            className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                          />
                        </div>
                        <div>
                          <label className="block text-xs text-garage-text-muted mb-1">Highway</label>
                          <input
                            type="number"
                            value={extractedData.fuel_economy_highway || ''}
                            onChange={(e) => setExtractedData({
                              ...extractedData,
                              fuel_economy_highway: e.target.value ? parseInt(e.target.value) : undefined
                            })}
                            disabled={!editMode}
                            placeholder="25"
                            className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                          />
                        </div>
                        <div>
                          <label className="block text-xs text-garage-text-muted mb-1">Combined</label>
                          <input
                            type="number"
                            value={extractedData.fuel_economy_combined || ''}
                            onChange={(e) => setExtractedData({
                              ...extractedData,
                              fuel_economy_combined: e.target.value ? parseInt(e.target.value) : undefined
                            })}
                            disabled={!editMode}
                            placeholder="22"
                            className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                          />
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Warranty Section */}
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-garage-text font-medium">
                      <Shield className="w-5 h-5 text-primary" />
                      <span>Warranty</span>
                    </div>

                    <div className="grid grid-cols-2 gap-3 ml-7">
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">Powertrain</label>
                        <input
                          type="text"
                          value={extractedData.warranty_powertrain || ''}
                          onChange={(e) => setExtractedData({
                            ...extractedData,
                            warranty_powertrain: e.target.value || undefined
                          })}
                          disabled={!editMode}
                          placeholder="5-year or 100,000-mile"
                          className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">Basic</label>
                        <input
                          type="text"
                          value={extractedData.warranty_basic || ''}
                          onChange={(e) => setExtractedData({
                            ...extractedData,
                            warranty_basic: e.target.value || undefined
                          })}
                          disabled={!editMode}
                          placeholder="3-year or 36,000-mile"
                          className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                        />
                      </div>
                    </div>
                  </div>

                  {/* Environmental Ratings Section */}
                  {(extractedData.environmental_rating_ghg || extractedData.environmental_rating_smog) && (
                    <div className="space-y-3">
                      <div className="flex items-center gap-2 text-garage-text font-medium">
                        <Leaf className="w-5 h-5 text-primary" />
                        <span>Environmental Ratings (CA ARB)</span>
                      </div>

                      <div className="grid grid-cols-2 gap-3 ml-7">
                        <div>
                          <label className="block text-xs text-garage-text-muted mb-1">Greenhouse Gas (GHG)</label>
                          <input
                            type="text"
                            value={extractedData.environmental_rating_ghg || ''}
                            onChange={(e) => setExtractedData({
                              ...extractedData,
                              environmental_rating_ghg: e.target.value || undefined
                            })}
                            disabled={!editMode}
                            placeholder="A+"
                            className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                          />
                        </div>
                        <div>
                          <label className="block text-xs text-garage-text-muted mb-1">Smog Rating</label>
                          <input
                            type="text"
                            value={extractedData.environmental_rating_smog || ''}
                            onChange={(e) => setExtractedData({
                              ...extractedData,
                              environmental_rating_smog: e.target.value || undefined
                            })}
                            disabled={!editMode}
                            placeholder="A+"
                            className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                          />
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Assembly Location */}
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-garage-text font-medium">
                      <Car className="w-5 h-5 text-primary" />
                      <span>Assembly & VIN</span>
                    </div>

                    <div className="grid grid-cols-2 gap-3 ml-7">
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">Assembly Location</label>
                        <input
                          type="text"
                          value={extractedData.assembly_location || ''}
                          onChange={(e) => setExtractedData({
                            ...extractedData,
                            assembly_location: e.target.value || undefined
                          })}
                          disabled={!editMode}
                          placeholder="e.g., Warren, MI, USA"
                          className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                        />
                      </div>
                      {extractedData.window_sticker_extracted_vin && (
                        <div>
                          <label className="block text-xs text-garage-text-muted mb-1">Extracted VIN</label>
                          <input
                            type="text"
                            value={extractedData.window_sticker_extracted_vin || ''}
                            disabled={true}
                            className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60 font-mono"
                          />
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Options Detail (if available) */}
                  {extractedData.window_sticker_options_detail && Object.keys(extractedData.window_sticker_options_detail).length > 0 && (
                    <div className="space-y-3">
                      <div className="flex items-center gap-2 text-garage-text font-medium">
                        <DollarSign className="w-5 h-5 text-primary" />
                        <span>Options Detail</span>
                      </div>
                      <div className="ml-7 bg-garage-surface rounded p-3 border border-garage-border">
                        <div className="space-y-1 text-sm">
                          {Object.entries(extractedData.window_sticker_options_detail).map(([name, price]) => (
                            <div key={name} className="flex justify-between">
                              <span className="text-garage-text-muted">{name}</span>
                              <span className="text-garage-text">${price}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Standard Equipment (if available) */}
                  {extractedData.standard_equipment?.items && extractedData.standard_equipment.items.length > 0 && (
                    <div className="space-y-3">
                      <div className="flex items-center gap-2 text-garage-text font-medium">
                        <FileText className="w-5 h-5 text-primary" />
                        <span>Standard Equipment ({extractedData.standard_equipment.items.length} items)</span>
                      </div>
                      <div className="ml-7 bg-garage-surface rounded p-3 border border-garage-border max-h-40 overflow-y-auto">
                        <ul className="text-sm text-garage-text-muted space-y-1">
                          {extractedData.standard_equipment.items.slice(0, 20).map((item, i) => (
                            <li key={i} className="truncate">{item}</li>
                          ))}
                          {extractedData.standard_equipment.items.length > 20 && (
                            <li className="text-primary">...and {extractedData.standard_equipment.items.length - 20} more</li>
                          )}
                        </ul>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              <div className="flex justify-end gap-3">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 bg-garage-bg border border-garage-border text-garage-text rounded-lg hover:bg-garage-border/50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleSaveEdits}
                  disabled={uploading}
                  className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  <Save className="w-4 h-4" />
                  {uploading ? 'Saving...' : 'Save Data'}
                </button>
              </div>
            </>
          )}
        </form>
      </div>
    </div>
  )
}
