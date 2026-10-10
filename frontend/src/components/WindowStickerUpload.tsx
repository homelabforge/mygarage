import { useState, useRef, type ReactElement, type SyntheticEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Upload, FileText, DollarSign, Fuel, Edit2, Save, Palette, Shield, Leaf, Cog, Car } from 'lucide-react'
import api from '../services/api'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { applyControlledFieldErrors, withoutFieldError } from '../hooks/useApiFormErrors'
import { parseDecimalInput } from '../utils/decimalInput'
import { moneyTextError } from '../schemas/shared'
import { getActiveLocale } from '@/constants/i18n'
import { Checkbox, Drawer } from './ui'
import { useCurrencySymbol } from '../hooks/useCurrencySymbol'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'
import { formatStickerValue } from '../utils/formatUtils'
import { useUnitFormat } from '../hooks/useUnitFormat'
import { seedUnitField, unitFieldUnchanged, type UnitFieldOrigin } from '../utils/unitFormat'
import type { components } from '../types/api.generated'

type StickerData = components['schemas']['WindowStickerResponse']

// Widths match the vehicle columns, so an overlong value stops at the input
// instead of coming back as a 422.
const TEXT_FIELDS = {
  exterior_color: 100,
  interior_color: 100,
  sticker_engine_description: 150,
  sticker_transmission_description: 150,
  sticker_drivetrain: 50,
  wheel_specs: 100,
  tire_specs: 100,
  warranty_powertrain: 100,
  warranty_basic: 100,
  environmental_rating_ghg: 10,
  environmental_rating_smog: 10,
  assembly_location: 100,
} as const
type TextField = keyof typeof TEXT_FIELDS
const TEXT_KEYS = Object.keys(TEXT_FIELDS) as TextField[]

const MONEY_FIELDS = ['msrp_base', 'msrp_options', 'destination_charge', 'msrp_total'] as const
type MoneyField = (typeof MONEY_FIELDS)[number]

// Stored in L/100 km, shown and edited in the user's unit.
const ECONOMY_FIELDS = [
  'fuel_economy_city_l_per_100km',
  'fuel_economy_highway_l_per_100km',
  'fuel_economy_combined_l_per_100km',
] as const
type EconomyField = (typeof ECONOMY_FIELDS)[number]

type ReviewField = TextField | MoneyField | EconomyField

// Every editable field renders its own fieldErrors alert, so a 422 on any of
// them lands inline. A key listed here without an alert would swallow its
// error: it counts as attached, which suppresses the banner.
const WINDOW_STICKER_KNOWN_FIELDS: readonly ReviewField[] = [...MONEY_FIELDS, ...ECONOMY_FIELDS, ...TEXT_KEYS]

const toNumber = (value: string | number | null | undefined): number | null =>
  value == null || value === '' ? null : Number(value)

interface WindowStickerUploadProps {
  vin: string
  /** A sticker is already on file, so the upload asks whether to keep its values. */
  hasExistingSticker?: boolean
  onSuccess: () => void
  onClose: () => void
}

export default function WindowStickerUpload({
  vin,
  hasExistingSticker = false,
  onSuccess,
  onClose,
}: WindowStickerUploadProps): ReactElement {
  const { t } = useTranslation('vehicles')
  const currencySymbol = useCurrencySymbol()
  const { currencyCode, locale } = useCurrencyPreference()
  const u = useUnitFormat()
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [success, setSuccess] = useState<string | null>(null)
  // Its own tone: the upload worked, but the scan gave the review nothing.
  const [notice, setNotice] = useState<string | null>(null)
  // On by default (D1): a re-scan only fills what's empty.
  const [keepSaved, setKeepSaved] = useState(true)
  const [file, setFile] = useState<File | null>(null)
  // What the upload stored, and the review's edits as typed. Save sends only
  // the fields whose value differs from the seed, so an untouched review
  // writes nothing back.
  const [seed, setSeed] = useState<StickerData | null>(null)
  const [draft, setDraft] = useState<Record<ReviewField, string> | null>(null)
  const [economyOrigins, setEconomyOrigins] = useState<Record<EconomyField, UnitFieldOrigin> | null>(null)
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
    setFieldErrors({})
    setSuccess(null)
    setNotice(null)

    try {
      const formData = new FormData()
      formData.append('file', file)
      if (hasExistingSticker && !keepSaved) formData.append('replace', 'true')

      const response = await api.post(`/vehicles/${vin}/window-sticker/upload`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })

      const data = response.data as StickerData
      const origins = Object.fromEntries(
        ECONOMY_FIELDS.map((key) => [key, seedUnitField(toNumber(data[key]), u.consumption)])
      ) as Record<EconomyField, UnitFieldOrigin>
      const seeded = {} as Record<ReviewField, string>
      for (const key of TEXT_KEYS) seeded[key] = data[key] ?? ''
      for (const key of MONEY_FIELDS) seeded[key] = data[key] ?? ''
      for (const key of ECONOMY_FIELDS) seeded[key] = origins[key].display
      setSeed(data)
      setEconomyOrigins(origins)
      setDraft(seeded)
      if (data.scan_read_nothing) setNotice(t('windowSticker.scanReadNothing'))
      else setSuccess(t('windowSticker.misc.uploadSuccess'))
      setEditMode(true)
    } catch (err) {
      const { attached, unhandled, errorsByField } = applyControlledFieldErrors(
        err,
        WINDOW_STICKER_KNOWN_FIELDS
      )
      if (attached.length > 0) {
        setFieldErrors(errorsByField)
      }
      if (attached.length === 0 || unhandled.length > 0) {
        setError(getActionErrorMessage(err, t('windowSticker.uploadAction')))
      }
    } finally {
      setUploading(false)
    }
  }

  // The fields that differ from what the upload stored, plus any text that
  // doesn't parse as a number.
  const collectChanges = (
    stored: StickerData,
    typed: Record<ReviewField, string>,
    origins: Record<EconomyField, UnitFieldOrigin>
  ): { changes: Record<string, string | number | null>; problems: Record<string, string> } => {
    const changes: Record<string, string | number | null> = {}
    const problems: Record<string, string> = {}
    const invalid = t('common:validation.amount.invalid')

    for (const key of TEXT_KEYS) {
      if (typed[key] === (stored[key] ?? '')) continue
      changes[key] = typed[key] === '' ? null : typed[key]
    }
    for (const key of MONEY_FIELDS) {
      if (typed[key] === (stored[key] ?? '')) continue
      // Unreadable, negative or past the API's MONEY_MAX, said on the field.
      const problem = moneyTextError(t, typed[key])
      if (problem) {
        problems[key] = problem
        continue
      }
      const parsed = parseDecimalInput(typed[key], getActiveLocale())
      const value = parsed.kind === 'value' ? parsed.value : null
      if (value !== toNumber(stored[key])) changes[key] = value
    }
    for (const key of ECONOMY_FIELDS) {
      // Compared as a quantity: 7.84 L/100 km shows as 30.0 mpg, and 30.0 mpg
      // converted back would not be 7.84.
      if (unitFieldUnchanged(typed[key], origins[key])) continue
      const parsed = parseDecimalInput(typed[key], getActiveLocale())
      if (parsed.kind === 'invalid') {
        problems[key] = invalid
        continue
      }
      changes[key] = parsed.kind === 'empty' ? null : u.consumption.toCanonical(parsed.value)
    }
    return { changes, problems }
  }

  const finish = () => {
    setNotice(null)
    setSuccess(t('windowSticker.misc.saveSuccess'))
    setTimeout(() => {
      onSuccess()
      onClose()
    }, 1000)
  }

  const handleSaveEdits = async () => {
    if (!seed || !draft || !economyOrigins) return

    setError(null)
    setFieldErrors({})

    const { changes, problems } = collectChanges(seed, draft, economyOrigins)
    if (Object.keys(problems).length > 0) {
      setFieldErrors(problems)
      return
    }
    // The upload already stored everything, so an untouched review is done.
    if (Object.keys(changes).length === 0) {
      finish()
      return
    }

    setUploading(true)
    try {
      await api.patch(`/vehicles/${vin}/window-sticker/data`, changes)
      finish()
    } catch (err) {
      const { attached, unhandled, errorsByField } = applyControlledFieldErrors(
        err,
        WINDOW_STICKER_KNOWN_FIELDS
      )
      if (attached.length > 0) {
        setFieldErrors(errorsByField)
      }
      if (attached.length === 0 || unhandled.length > 0) {
        setError(getActionErrorMessage(err, t('windowSticker.saveAction')))
      }
    } finally {
      setUploading(false)
    }
  }

  const reviewInput = (key: ReviewField, label: string, placeholder?: string, unit?: string) => (
    <div>
      <label htmlFor={`sticker-${key}`} className="block text-xs text-garage-text-muted mb-1">
        {label}
        {unit ? ` (${unit})` : ''}
      </label>
      <input
        id={`sticker-${key}`}
        type="text"
        inputMode={key in TEXT_FIELDS ? undefined : 'decimal'}
        maxLength={key in TEXT_FIELDS ? TEXT_FIELDS[key as TextField] : undefined}
        value={draft?.[key] ?? ''}
        onChange={(e) => {
          const value = e.target.value
          setDraft((prev) => (prev ? { ...prev, [key]: value } : prev))
          setFieldErrors((prev) => withoutFieldError(prev, key))
        }}
        disabled={!editMode}
        placeholder={placeholder}
        aria-invalid={fieldErrors[key] ? true : undefined}
        className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60"
      />
      {fieldErrors[key] && (
        <p role="alert" className="mt-1 text-xs text-danger-500">{fieldErrors[key]}</p>
      )}
    </div>
  )

  const optionsDetail = seed?.window_sticker_options_detail ?? {}
  const standardItems = Array.isArray(seed?.standard_equipment?.items)
    ? (seed.standard_equipment.items as unknown[]).map(String)
    : []

  return (
    <Drawer
      open
      onClose={onClose}
      title={t('windowSticker.uploadTitle')}
      icon={FileText}
      width="xl"
      nested
      closeLabel={t('common:close')}
    >
      <form onSubmit={handleSubmit} className="space-y-6">
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

        {notice && (
          <div className="bg-warning-500/10 border border-warning-500 rounded-lg p-3">
            <p className="text-sm text-warning-500">{notice}</p>
          </div>
        )}

        {!seed && (
          <>
            {hasExistingSticker && (
              <div className="space-y-1">
                <Checkbox
                  label={t('windowSticker.keepSavedValues')}
                  checked={keepSaved}
                  onChange={(e) => setKeepSaved(e.target.checked)}
                  disabled={uploading}
                />
                <p className="text-xs text-text-mute">{t('windowSticker.keepSavedValuesHint')}</p>
              </div>
            )}

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

        {seed && (
          <>
            <div className="bg-garage-bg rounded-lg p-4 border border-garage-border max-h-[60vh] overflow-y-auto">
              <div className="flex items-center justify-between mb-4 sticky top-0 bg-garage-bg pb-2">
                <div>
                  <h3 className="text-lg font-semibold text-garage-text">{t('windowSticker.extractedData')}</h3>
                  {seed.window_sticker_parser_used && (
                    <p className="text-xs text-garage-text-muted">
                      {t('detail.misc.parser', { parser: seed.window_sticker_parser_used })}
                      {seed.window_sticker_confidence_score && (
                        <span className="ml-2">
                          {t('windowSticker.misc.confidence', {
                            percent: Math.round(Number(seed.window_sticker_confidence_score)),
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
                    {/* No grouping in the placeholders: a comma is the decimal point in most of our locales. */}
                    {reviewInput('msrp_base', t('detail.misc.basePrice'), '91860', currencySymbol)}
                    {reviewInput('msrp_options', t('detail.misc.options'), '11055', currencySymbol)}
                    {reviewInput('destination_charge', t('detail.misc.destination'), '2095', currencySymbol)}
                    {reviewInput('msrp_total', t('detail.misc.totalMsrp'), '102915', currencySymbol)}
                  </div>
                </div>

                {/* Colors Section */}
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-garage-text font-medium">
                    <Palette className="w-5 h-5 text-primary" />
                    <span>{t('windowSticker.misc.colors')}</span>
                  </div>
                  <div className="grid grid-cols-2 gap-3 ml-7">
                    {reviewInput('exterior_color', t('detail.misc.exteriorColor'), t('windowSticker.misc.exteriorColorPlaceholder'))}
                    {reviewInput('interior_color', t('detail.misc.interiorColor'), t('windowSticker.misc.interiorColorPlaceholder'))}
                  </div>
                </div>

                {/* Vehicle Specs Section */}
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-garage-text font-medium">
                    <Cog className="w-5 h-5 text-primary" />
                    <span>{t('windowSticker.misc.vehicleSpecs')}</span>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3 ml-7">
                    {reviewInput('sticker_engine_description', t('detail.misc.engine'), t('windowSticker.misc.enginePlaceholder'))}
                    {reviewInput('sticker_transmission_description', t('detail.misc.transmission'), t('windowSticker.misc.transmissionPlaceholder'))}
                    {reviewInput('sticker_drivetrain', t('detail.misc.drivetrain'), t('wizard.misc.driveTypePlaceholder'))}
                    {reviewInput('wheel_specs', t('detail.misc.wheels'), t('windowSticker.misc.wheelsPlaceholder'))}
                    {reviewInput('tire_specs', t('detail.misc.tires'), 'LT285/60R20E')}
                  </div>
                </div>

                {/* Fuel Economy Section: always shown, so you can add what the OCR missed. */}
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-garage-text font-medium">
                    <Fuel className="w-5 h-5 text-primary" />
                    <span>{t('windowSticker.misc.fuelEconomyUnit', { unit: u.consumption.label })}</span>
                  </div>
                  <div className="grid grid-cols-3 gap-3 ml-7">
                    {reviewInput('fuel_economy_city_l_per_100km', t('detail.misc.city'))}
                    {reviewInput('fuel_economy_highway_l_per_100km', t('detail.misc.highway'))}
                    {reviewInput('fuel_economy_combined_l_per_100km', t('detail.misc.combined'))}
                  </div>
                </div>

                {/* Warranty Section */}
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-garage-text font-medium">
                    <Shield className="w-5 h-5 text-primary" />
                    <span>{t('detail.warranty')}</span>
                  </div>
                  <div className="grid grid-cols-2 gap-3 ml-7">
                    {reviewInput('warranty_powertrain', t('detail.powertrain'), t('windowSticker.misc.warrantyPowertrainPlaceholder'))}
                    {reviewInput('warranty_basic', t('detail.misc.basic'), t('windowSticker.misc.warrantyBasicPlaceholder'))}
                  </div>
                </div>

                {/* Environmental Ratings Section: always shown, same as fuel economy. */}
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-garage-text font-medium">
                    <Leaf className="w-5 h-5 text-primary" />
                    <span>{t('windowSticker.misc.environmentalRatings')}</span>
                  </div>
                  <div className="grid grid-cols-2 gap-3 ml-7">
                    {reviewInput('environmental_rating_ghg', t('windowSticker.misc.greenhouseGas'), 'A+')}
                    {reviewInput('environmental_rating_smog', t('detail.misc.smogRating'), 'A+')}
                  </div>
                </div>

                {/* Assembly Location */}
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-garage-text font-medium">
                    <Car className="w-5 h-5 text-primary" />
                    <span>{t('windowSticker.misc.assemblyAndVin')}</span>
                  </div>
                  <div className="grid grid-cols-2 gap-3 ml-7">
                    {reviewInput('assembly_location', t('detail.misc.assemblyLocation'), t('windowSticker.misc.assemblyLocationPlaceholder'))}
                    {seed.window_sticker_extracted_vin && (
                      <div>
                        <label className="block text-xs text-garage-text-muted mb-1">{t('windowSticker.misc.extractedVin')}</label>
                        <input
                          type="text"
                          value={seed.window_sticker_extracted_vin}
                          disabled={true}
                          className="w-full px-3 py-2 bg-garage-surface border border-garage-border rounded text-garage-text text-sm disabled:opacity-60 font-mono"
                        />
                      </div>
                    )}
                  </div>
                </div>

                {/* Options Detail (if available) */}
                {Object.keys(optionsDetail).length > 0 && (
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-garage-text font-medium">
                      <DollarSign className="w-5 h-5 text-primary" />
                      <span>{t('windowSticker.misc.optionsDetail')}</span>
                    </div>
                    <div className="ml-7 bg-garage-surface rounded p-3 border border-garage-border">
                      <div className="space-y-1 text-sm">
                        {Object.entries(optionsDetail).map(([name, price]) => {
                          // Prices come back as strings and some read "Included", which
                          // stays a word instead of getting a currency sign glued on.
                          const value = formatStickerValue(price, { currencyCode, locale })
                          return (
                            <div key={name} className="flex justify-between">
                              <span className="text-garage-text-muted">{name}</span>
                              {value && <span className="text-garage-text">{value}</span>}
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  </div>
                )}

                {/* Standard Equipment (if available) */}
                {standardItems.length > 0 && (
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-garage-text font-medium">
                      <FileText className="w-5 h-5 text-primary" />
                      <span>
                        {t('windowSticker.misc.standardEquipmentCount', {
                          count: standardItems.length,
                        })}
                      </span>
                    </div>
                    <div className="ml-7 bg-garage-surface rounded p-3 border border-garage-border max-h-40 overflow-y-auto">
                      <ul className="text-sm text-garage-text-muted space-y-1">
                        {standardItems.slice(0, 20).map((item, i) => (
                          <li key={i} className="truncate">{item}</li>
                        ))}
                        {standardItems.length > 20 && (
                          <li className="text-primary">
                            {t('windowSticker.misc.andMore', {
                              count: standardItems.length - 20,
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
    </Drawer>
  )
}
