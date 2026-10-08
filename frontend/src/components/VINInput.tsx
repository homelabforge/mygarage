/**
 * VIN Input component with auto-decode functionality
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Search, Check, X, Loader2, Info, FileText } from 'lucide-react'
import { vinService } from '@/services/vinService'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'
import { Card } from '@/components/ui'
import { asCountryCode, countryName } from '@/constants/countries'
import { useDateLocale } from '@/hooks/useDateLocale'
import type { VINDecodeResponse } from '@/types/vin'

/** The decoder's notes (#211), each with its own translated sentence. */
const NOTE_LABEL_KEYS: Record<string, string> = {
  eu_vin_no_model: 'vinInput.notes.eu_vin_no_model',
  year_unreliable: 'vinInput.notes.year_unreliable',
  check_digit_not_applicable: 'vinInput.notes.check_digit_not_applicable',
}

interface VINInputProps {
  value: string
  onChange: (vin: string) => void
  onDecode?: (data: VINDecodeResponse) => void
  autoValidate?: boolean
  className?: string
  /**
   * When true, on blur (and on auto-complete to 17 chars) the component
   * also pings the backend for an existing vehicle with this VIN. Surfaces
   * a "VIN already exists" warning so the user doesn't fill out the whole
   * wizard before discovering the duplicate. Surfaced by issue #69.
   */
  checkDuplicate?: boolean
  /**
   * Offered on a partial decode (a European VIN names the maker and nothing
   * else): the caller brings the registration certificate import into view.
   * Absent, no button.
   */
  onImportCertificate?: () => void
}

export default function VINInput({
  value,
  onChange,
  onDecode,
  autoValidate = true,
  className = '',
  checkDuplicate = false,
  onImportCertificate,
}: VINInputProps) {
  const { t } = useTranslation('vehicles')
  const locale = useDateLocale()
  const [isValidating, setIsValidating] = useState(false)
  const [isDecoding, setIsDecoding] = useState(false)
  const [validationStatus, setValidationStatus] = useState<
    'idle' | 'valid' | 'invalid'
  >('idle')
  const [errorMessage, setErrorMessage] = useState<string>('')
  const [duplicateWarning, setDuplicateWarning] = useState<string>('')
  const [decodedData, setDecodedData] = useState<VINDecodeResponse | null>(null)

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newValue = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '')
    onChange(newValue)
    setValidationStatus('idle')
    setErrorMessage('')
    setDuplicateWarning('')
    setDecodedData(null)

    // Auto-validate when 17 characters
    if (autoValidate && newValue.length === 17) {
      validateVIN(newValue)
      if (checkDuplicate) {
        void runDuplicateCheck(newValue)
      }
    }
  }

  const handleBlur = () => {
    // Late check for users who paste a partial VIN and tab away before
    // hitting the 17-char auto-trigger above. No-op when value is too
    // short (still invalid by format) or already known to be a dup.
    if (checkDuplicate && value.length === 17 && !duplicateWarning) {
      void runDuplicateCheck(value)
    }
  }

  const runDuplicateCheck = async (vin: string) => {
    try {
      const exists = await vinService.exists(vin)
      if (exists) {
        setDuplicateWarning(t('vinInput.alreadyExists'))
      }
    } catch {
      // Network error — don't block the user; the backend POST will
      // catch the duplicate at submit time.
    }
  }

  const validateVIN = async (vin: string) => {
    if (vin.length !== 17) {
      setValidationStatus('invalid')
      setErrorMessage(t('vinInput.mustBe17Characters'))
      return
    }

    setIsValidating(true)
    setErrorMessage('')

    try {
      const result = await vinService.validate(vin)
      if (result.valid) {
        setValidationStatus('valid')
      } else {
        setValidationStatus('invalid')
        // `result.error` is backend-supplied text — surfaced verbatim, never
        // routed through t().
        setErrorMessage(result.error || t('vinInput.invalidFormat'))
      }
    } catch {
      setValidationStatus('invalid')
      setErrorMessage(t('vinInput.validateFailed'))
    } finally {
      setIsValidating(false)
    }
  }

  const handleDecode = async () => {
    if (value.length !== 17) {
      setErrorMessage(t('vinInput.mustBe17Characters'))
      return
    }

    setIsDecoding(true)
    setErrorMessage('')

    try {
      const data = await vinService.decode(value)
      setDecodedData(data)
      if (onDecode) {
        onDecode(data)
      }
    } catch (err: unknown) {
      setErrorMessage(getActionErrorMessage(err, t('vinInput.decodeAction')))
    } finally {
      setIsDecoding(false)
    }
  }

  const getStatusIcon = () => {
    if (isValidating) {
      return <Loader2 className="w-5 h-5 text-garage-text-muted animate-spin" />
    }
    if (validationStatus === 'valid') {
      return <Check className="w-5 h-5 text-success-500" />
    }
    if (validationStatus === 'invalid') {
      return <X className="w-5 h-5 text-danger-500" />
    }
    return null
  }

  return (
    <div className={`space-y-3 ${className}`}>
      {/* VIN Input with validation status */}
      <div className="relative">
        <input
          type="text"
          value={value}
          onChange={handleChange}
          onBlur={handleBlur}
          maxLength={17}
          placeholder={t('vinInput.placeholder')}
          className="input pr-12"
        />
        <div className="absolute right-3 top-1/2 -translate-y-1/2">
          {getStatusIcon()}
        </div>
      </div>

      {/* Character counter */}
      <div className="flex items-center justify-between text-sm">
        <span
          className={`${
            value.length === 17
              ? 'text-success-500'
              : 'text-garage-text-muted'
          }`}
        >
          {t('vinInput.characterCount', { current: value.length, max: 17 })}
        </span>
        <button
          onClick={handleDecode}
          disabled={value.length !== 17 || isDecoding}
          className="btn btn-primary btn-sm flex items-center space-x-2 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isDecoding ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>{t('vinInput.decoding')}</span>
            </>
          ) : (
            <>
              <Search className="w-4 h-4" />
              <span>{t('vinInput.decode')}</span>
            </>
          )}
        </button>
      </div>

      {/* Error message */}
      {errorMessage && (
        <div className="flex items-center space-x-2 text-danger-500 text-sm">
          <X className="w-4 h-4" />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Duplicate-VIN warning (Phase 3.2 / issue #69) */}
      {duplicateWarning && (
        <div
          role="alert"
          className="flex items-center space-x-2 text-warning-500 text-sm"
        >
          <X className="w-4 h-4" />
          <span>{duplicateWarning}</span>
        </div>
      )}

      {/* A partial decode (#211): a European VIN names the maker and nothing
          else, so say so and point at the certificate instead of showing
          an empty card as if the vehicle were unknown. */}
      {decodedData && !errorMessage && decodedData.decode_quality && decodedData.decode_quality !== 'full' && (
        <div
          role="status"
          data-testid="vin-partial-decode"
          className="flex items-start gap-2 rounded-panel border border-(--accent-fg)/40 bg-(--accent-fg)/10 p-3 text-sm text-text"
        >
          <Info aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-(--accent-fg)" />
          <div className="space-y-2">
            <p>
              {decodedData.make
                ? decodedData.region === 'EU'
                  ? t('vinInput.euPartial', { make: decodedData.make })
                  : t('vinInput.partialDecode', { make: decodedData.make })
                : t('vinInput.nothingDecoded')}
            </p>
            {decodedData.notes && decodedData.notes.length > 0 && (
              <ul className="list-disc pl-5 text-xs text-text-mute">
                {decodedData.notes.map((note) => (
                  <li key={note}>{t(NOTE_LABEL_KEYS[note] ?? note)}</li>
                ))}
              </ul>
            )}
            {onImportCertificate && (
              <button
                type="button"
                onClick={onImportCertificate}
                className="inline-flex items-center gap-1 text-sm font-medium text-(--accent-fg) underline-offset-2 hover:underline"
              >
                <FileText aria-hidden="true" className="h-4 w-4" />
                {t('vinInput.importCertificate')}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Decoded data display */}
      {decodedData && !errorMessage && (
        <Card className="bg-surface-2">
          <h4 className="text-lg font-semibold mb-3">{t('vinInput.decodedTitle')}</h4>
          <div className="grid grid-cols-2 gap-3 text-sm">
            {decodedData.year && (
              <div>
                <span className="text-garage-text-muted">{t('vinInput.fieldYear')}</span>
                <span className="ml-2 font-medium">{decodedData.year}</span>
              </div>
            )}
            {decodedData.make && (
              <div>
                <span className="text-garage-text-muted">{t('vinInput.fieldMake')}</span>
                <span className="ml-2 font-medium">{decodedData.make}</span>
              </div>
            )}
            {decodedData.model && (
              <div>
                <span className="text-garage-text-muted">{t('vinInput.fieldModel')}</span>
                <span className="ml-2 font-medium">{decodedData.model}</span>
              </div>
            )}
            {decodedData.series && (
              <div>
                <span className="text-garage-text-muted">{t('vinInput.fieldSeries')}</span>
                <span className="ml-2 font-medium">{decodedData.series}</span>
              </div>
            )}
            {decodedData.vehicle_type && (
              <div>
                <span className="text-garage-text-muted">{t('vinInput.fieldType')}</span>
                <span className="ml-2 font-medium">{decodedData.vehicle_type}</span>
              </div>
            )}
            {decodedData.body_class && (
              <div>
                <span className="text-garage-text-muted">{t('vinInput.fieldBody')}</span>
                <span className="ml-2 font-medium">{decodedData.body_class}</span>
              </div>
            )}
            {decodedData.engine?.displacement_l && (
              <div>
                <span className="text-garage-text-muted">{t('vinInput.fieldEngine')}</span>
                <span className="ml-2 font-medium">
                  {decodedData.engine.displacement_l}L
                  {decodedData.engine.cylinders && ` ${decodedData.engine.cylinders}cyl`}
                </span>
              </div>
            )}
            {decodedData.drive_type && (
              <div>
                <span className="text-garage-text-muted">{t('vinInput.fieldDrive')}</span>
                <span className="ml-2 font-medium">{decodedData.drive_type}</span>
              </div>
            )}
            {decodedData.doors && (
              <div>
                <span className="text-garage-text-muted">{t('vinInput.fieldDoors')}</span>
                <span className="ml-2 font-medium">{decodedData.doors}</span>
              </div>
            )}
            {decodedData.plant_country ? (
              <div>
                <span className="text-garage-text-muted">{t('vinInput.fieldMadeIn')}</span>
                <span className="ml-2 font-medium">
                  {decodedData.plant_city && `${decodedData.plant_city}, `}
                  {decodedData.plant_country}
                </span>
              </div>
            ) : (
              asCountryCode(decodedData.wmi_country) && (
                <div>
                  <span className="text-garage-text-muted">{t('vinInput.fieldWmiCountry')}</span>
                  <span className="ml-2 font-medium">
                    {countryName(asCountryCode(decodedData.wmi_country) as string, locale)}
                  </span>
                </div>
              )
            )}
          </div>
        </Card>
      )}
    </div>
  )
}
