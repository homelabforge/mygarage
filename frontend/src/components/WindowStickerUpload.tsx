import { useState, useRef, type SyntheticEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Upload, X, FileText, DollarSign, Fuel, Edit2, Save, Palette, Shield, Leaf, Cog, Car } from 'lucide-react'
import api from '../services/api'
import { useCurrencySymbol } from '../hooks/useCurrencySymbol'

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
  const { t } = useTranslation('vehicles')
  const currencySymbol = useCurrencySymbol()
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
      setError(t('windowSticker.misc.invalidFileType'))
      return
    }

    // Validate file size (10MB)
    if (selectedFile.size > 10 * 1024 * 1024) {
      setError(t('windowSticker.misc.fileTooLarge'))
      return
    }

    setFile(selectedFile)
    setError(null)
  }

  const handleSubmit = async (e: SyntheticEvent<HTMLFormElement>) => {
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
      setSuccess(t('windowSticker.misc.uploadSuccess'))
      setEditMode(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('windowSticker.misc.errorOccurred'))
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

      setSuccess(t('windowSticker.misc.saveSuccess'))
      setTimeout(() => {
        onSuccess()
        onClose()
      }, 1000)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('windowSticker.misc.errorOccurred'))
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
          <h2 className="text-xl font-semibold text-garage-text">{t('windowSticker.uploadTitle')}</h2>
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
                  {t('windowSticker.misc.dragDropPrompt')}
                </p>
                <p className="text-sm text-garage-text-muted mb-4">
                  {t('windowSticker.fileTypes')}
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
                  className="px-4 py-2 bg-primary text-(--accent-on-solid) rounded-lg hover:bg-primary/90 transition-colors"
                >
                  {t('windowSticker.misc.selectFile')}
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
                  {t('windowSticker.misc.cancel')}
                </button>
                <button
                  type="submit"
                  disabled={!file || uploading}
                  className="flex items-center gap-2 px-4 py-2 bg-primary text-(--accent-on-solid) rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Upload className="w-4 h-4" />
                  {uploading ? t('windowSticker.uploading') : t('windowSticker.uploadAndExtract')}
                </button>
              </div>
            </>
          )}

          {extractedData && (
            <>
              <div className="bg-garage-bg rounded-lg p-4 border border-garage-border max-h-[60vh] overflow-y-auto">
                <div className="flex items-center justify-between mb-4 sticky top-0 bg-garage-bg pb-2">
                  <div>
                    <h3 className="text-lg font-semibold text-garage-text">{t('windowSticker.extractedData')}</h3>
                    {extractedData.window_sticker_parser_used && (
                      <p className="text-xs text-garage-text-muted">
                        {t('detail.misc.parser', { parser: extractedData.window_sticker_parser_used })}
                        {extractedData.window_sticker_confidence_score && (
                          <span className="ml-2">
                            {t('windowSticker.misc.confidence', {
                              percent: Math.round(Number(extractedData.window_sticker_confidence_score)),
                            })}
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
                    {editMode ? t('windowSticker.viewMode') : t('windowSticker.editMode')}
                  </button>
                </div>

                <div className="space-y-6">
                  {/* MSRP Section */}
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-garage-text font-medium">
                      <DollarSign className="w-5 h-5 text-primary" />
                      <span>{t('windowSticker.msrpPricing')}</span>
                    </div>

                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 ml-7">
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">{t('detail.misc.basePrice')}</label>
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
                        <label className="block text-xs text-garage-text-muted mb-1">{t('detail.misc.options')}</label>
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
                        <label className="block text-xs text-garage-text-muted mb-1">{t('detail.misc.destination')}</label>
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
                        <label className="block text-xs text-garage-text-muted mb-1">{t('detail.misc.totalMsrp')}</label>
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
                      <span>{t('windowSticker.misc.colors')}</span>
                    </div>

                    <div className="grid grid-cols-2 gap-3 ml-7">
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">{t('detail.misc.exteriorColor')}</label>
                        <input
                          type="text"
                          value={extractedData.exterior_color || ''}
                          onChange={(e) => setExtractedData({
                            ...extractedData,
                            exterior_color: e.target.value || undefined
                          })}
                          disabled={!editMode}
                          placeholder={t('windowSticker.misc.exteriorColorPlaceholder')}
                          className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">{t('detail.misc.interiorColor')}</label>
                        <input
                          type="text"
                          value={extractedData.interior_color || ''}
                          onChange={(e) => setExtractedData({
                            ...extractedData,
                            interior_color: e.target.value || undefined
                          })}
                          disabled={!editMode}
                          placeholder={t('windowSticker.misc.interiorColorPlaceholder')}
                          className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                        />
                      </div>
                    </div>
                  </div>

                  {/* Vehicle Specs Section */}
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-garage-text font-medium">
                      <Cog className="w-5 h-5 text-primary" />
                      <span>{t('windowSticker.misc.vehicleSpecs')}</span>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 ml-7">
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">{t('detail.misc.engine')}</label>
                        <input
                          type="text"
                          value={extractedData.sticker_engine_description || ''}
                          onChange={(e) => setExtractedData({
                            ...extractedData,
                            sticker_engine_description: e.target.value || undefined
                          })}
                          disabled={!editMode}
                          placeholder={t('windowSticker.misc.enginePlaceholder')}
                          className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">{t('detail.misc.transmission')}</label>
                        <input
                          type="text"
                          value={extractedData.sticker_transmission_description || ''}
                          onChange={(e) => setExtractedData({
                            ...extractedData,
                            sticker_transmission_description: e.target.value || undefined
                          })}
                          disabled={!editMode}
                          placeholder={t('windowSticker.misc.transmissionPlaceholder')}
                          className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">{t('detail.misc.wheels')}</label>
                        <input
                          type="text"
                          value={extractedData.wheel_specs || ''}
                          onChange={(e) => setExtractedData({
                            ...extractedData,
                            wheel_specs: e.target.value || undefined
                          })}
                          disabled={!editMode}
                          placeholder={t('windowSticker.misc.wheelsPlaceholder')}
                          className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">{t('detail.misc.tires')}</label>
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
                        <span>{t('windowSticker.misc.fuelEconomyMpg')}</span>
                      </div>

                      <div className="grid grid-cols-3 gap-3 ml-7">
                        <div>
                          <label className="block text-xs text-garage-text-muted mb-1">{t('detail.misc.city')}</label>
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
                          <label className="block text-xs text-garage-text-muted mb-1">{t('detail.misc.highway')}</label>
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
                          <label className="block text-xs text-garage-text-muted mb-1">{t('detail.misc.combined')}</label>
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
                      <span>{t('detail.warranty')}</span>
                    </div>

                    <div className="grid grid-cols-2 gap-3 ml-7">
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">{t('detail.powertrain')}</label>
                        <input
                          type="text"
                          value={extractedData.warranty_powertrain || ''}
                          onChange={(e) => setExtractedData({
                            ...extractedData,
                            warranty_powertrain: e.target.value || undefined
                          })}
                          disabled={!editMode}
                          placeholder={t('windowSticker.misc.warrantyPowertrainPlaceholder')}
                          className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">{t('detail.misc.basic')}</label>
                        <input
                          type="text"
                          value={extractedData.warranty_basic || ''}
                          onChange={(e) => setExtractedData({
                            ...extractedData,
                            warranty_basic: e.target.value || undefined
                          })}
                          disabled={!editMode}
                          placeholder={t('windowSticker.misc.warrantyBasicPlaceholder')}
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
                        <span>{t('windowSticker.misc.environmentalRatings')}</span>
                      </div>

                      <div className="grid grid-cols-2 gap-3 ml-7">
                        <div>
                          <label className="block text-xs text-garage-text-muted mb-1">{t('windowSticker.misc.greenhouseGas')}</label>
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
                          <label className="block text-xs text-garage-text-muted mb-1">{t('detail.misc.smogRating')}</label>
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
                      <span>{t('windowSticker.misc.assemblyAndVin')}</span>
                    </div>

                    <div className="grid grid-cols-2 gap-3 ml-7">
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">{t('detail.misc.assemblyLocation')}</label>
                        <input
                          type="text"
                          value={extractedData.assembly_location || ''}
                          onChange={(e) => setExtractedData({
                            ...extractedData,
                            assembly_location: e.target.value || undefined
                          })}
                          disabled={!editMode}
                          placeholder={t('windowSticker.misc.assemblyLocationPlaceholder')}
                          className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
                        />
                      </div>
                      {extractedData.window_sticker_extracted_vin && (
                        <div>
                          <label className="block text-xs text-garage-text-muted mb-1">{t('windowSticker.misc.extractedVin')}</label>
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
                        <span>{t('windowSticker.misc.optionsDetail')}</span>
                      </div>
                      <div className="ml-7 bg-garage-surface rounded p-3 border border-garage-border">
                        <div className="space-y-1 text-sm">
                          {Object.entries(extractedData.window_sticker_options_detail).map(([name, price]) => (
                            <div key={name} className="flex justify-between">
                              <span className="text-garage-text-muted">{name}</span>
                              <span className="text-garage-text">{currencySymbol}{price}</span>
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
                        <span>
                          {t('windowSticker.misc.standardEquipmentCount', {
                            count: extractedData.standard_equipment.items.length,
                          })}
                        </span>
                      </div>
                      <div className="ml-7 bg-garage-surface rounded p-3 border border-garage-border max-h-40 overflow-y-auto">
                        <ul className="text-sm text-garage-text-muted space-y-1">
                          {extractedData.standard_equipment.items.slice(0, 20).map((item, i) => (
                            <li key={i} className="truncate">{item}</li>
                          ))}
                          {extractedData.standard_equipment.items.length > 20 && (
                            <li className="text-primary">
                              {t('windowSticker.misc.andMore', {
                                count: extractedData.standard_equipment.items.length - 20,
                              })}
                            </li>
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
                  {t('windowSticker.misc.cancel')}
                </button>
                <button
                  type="button"
                  onClick={handleSaveEdits}
                  disabled={uploading}
                  className="flex items-center gap-2 px-4 py-2 bg-primary text-(--accent-on-solid) rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  <Save className="w-4 h-4" />
                  {uploading ? t('windowSticker.misc.saving') : t('windowSticker.misc.saveData')}
                </button>
              </div>
            </>
          )}
        </form>
      </div>
    </div>
  )
}
