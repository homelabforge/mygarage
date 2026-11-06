/**
 * VIN Input component with auto-decode functionality
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { Search, Check, X, Loader2, Info, FileText } from 'lucide-react'
import { vinService } from '@/services/vinService'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'
import { Card, Select } from '@/components/ui'
import { asCountryCode, countryName } from '@/constants/countries'
import { useLanguageLocale } from '@/hooks/useLanguageLocale'
import { useResolvedCountry } from '@/hooks/useResolvedCountry'
import type { VINDecodeResponse, VINProvider } from '@/types/vin'

/** The decoder's notes (#211, #219), each with its own translated sentence. */
const NOTE_LABEL_KEYS: Record<string, string> = {
  eu_vin_no_model: 'vinInput.notes.eu_vin_no_model',
  year_unreliable: 'vinInput.notes.year_unreliable',
  check_digit_not_applicable: 'vinInput.notes.check_digit_not_applicable',
  autoref_best_guess: 'vinInput.notes.autoref_best_guess',
  autoref_external_record: 'vinInput.notes.autoref_external_record',
  autoref_no_match: 'vinInput.notes.autoref_no_match',
  autoref_key_rejected: 'vinInput.notes.autoref_key_rejected',
  autoref_quota: 'vinInput.notes.autoref_quota',
  autoref_unavailable: 'vinInput.notes.autoref_unavailable',
}

/** Shown on a full answer too: what the decoder itself wants checked. The
 *  VIN-structure notes (the check digit fires for most European VINs) stay in
 *  the partial banner. */
const isDecoderNote = (note: string): boolean => note.startsWith('autoref_')

const PROVIDER_LABEL_KEYS: Record<VINProvider, string> = {
  nhtsa: 'vinInput.providers.nhtsa',
  autoref: 'vinInput.providers.autoref',
}

type ProviderChoice = 'automatic' | VINProvider

interface VINInputProps {
  value: string
  onChange: (vin: string) => void
  /**
   * A decode's answer. `fillOnly` is set on a second decoder's answer (Try
   * AutoRef / Try NHTSA): it adds what it knows and blanks nothing.
   */
  onDecode?: (data: VINDecodeResponse, options?: { fillOnly?: boolean }) => void
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
  /** The vehicle's registration country, which orders the decoders (#219).
   *  Absent, the person's own country or the instance's is used. */
  registrationCountry?: string | null
}

export default function VINInput({
  value,
  onChange,
  onDecode,
  autoValidate = true,
  className = '',
  checkDuplicate = false,
  onImportCertificate,
  registrationCountry,
}: VINInputProps) {
  const { t } = useTranslation('vehicles')
  const locale = useLanguageLocale()
  const [isValidating, setIsValidating] = useState(false)
  const [isDecoding, setIsDecoding] = useState(false)
  const [validationStatus, setValidationStatus] = useState<
    'idle' | 'valid' | 'invalid'
  >('idle')
  const [errorMessage, setErrorMessage] = useState<string>('')
  const [duplicateWarning, setDuplicateWarning] = useState<string>('')
  const [decodedData, setDecodedData] = useState<VINDecodeResponse | null>(null)
  // Automatic sends no provider, so the backend may fall back (Codex R1-M1);
  // only a deliberate choice here, or a Try button, names one.
  const [choice, setChoice] = useState<ProviderChoice>('automatic')
  const [tryError, setTryError] = useState<string>('')
  const country = useResolvedCountry({ registration_country: registrationCountry })
  const { data: providers } = useQuery({
    queryKey: ['vin-providers', country],
    queryFn: () => vinService.providers(country),
    staleTime: 5 * 60 * 1000,
  })
  const available = providers?.available ?? ['nhtsa']
  const hasChoice = available.includes('autoref')
  const preferred = providers?.preferred ?? 'nhtsa'

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newValue = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '')
    onChange(newValue)
    setValidationStatus('idle')
    setErrorMessage('')
    setDuplicateWarning('')
    setDecodedData(null)
    setTryError('')

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
    setTryError('')

    try {
      const data = await vinService.decode(value, {
        ...(choice !== 'automatic' ? { provider: choice } : {}),
        country,
      })
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

  // The other decoder, offered on a thin answer when it's available.
  const otherProvider: VINProvider | null =
    decodedData && decodedData.decode_quality && decodedData.decode_quality !== 'full'
      ? decodedData.decoded_by === 'autoref'
        ? 'nhtsa'
        : 'autoref'
      : null
  const canTryOther = otherProvider !== null && available.includes(otherProvider)

  // A failed try keeps the answer already on screen (Fable F-10): the wizard
  // would otherwise blank the engine and body fields it filled.
  const handleTryOther = async (provider: VINProvider) => {
    setIsDecoding(true)
    setTryError('')
    try {
      const data = await vinService.decode(value, { provider, country })
      setDecodedData(data)
      if (onDecode) {
        onDecode(data, { fillOnly: true })
      }
    } catch (err: unknown) {
      setTryError(getActionErrorMessage(err, t('vinInput.decodeAction')))
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
        <div className="flex items-center gap-2">
        {hasChoice && (
          <Select
            size="sm"
            aria-label={t('vinInput.decodeWith')}
            value={choice}
            onChange={(e) => setChoice(e.target.value as ProviderChoice)}
            options={[
              {
                value: 'automatic',
                label: t('vinInput.providerAutomatic', { first: t(PROVIDER_LABEL_KEYS[preferred]) }),
              },
              { value: 'nhtsa', label: t(PROVIDER_LABEL_KEYS.nhtsa) },
              { value: 'autoref', label: t(PROVIDER_LABEL_KEYS.autoref) },
            ]}
          />
        )}
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
            {canTryOther && otherProvider && (
              <button
                type="button"
                onClick={() => void handleTryOther(otherProvider)}
                disabled={isDecoding}
                className="mr-4 inline-flex items-center gap-1 text-sm font-medium text-(--accent-fg) underline-offset-2 hover:underline disabled:opacity-50"
              >
                <Search aria-hidden="true" className="h-4 w-4" />
                {otherProvider === 'autoref' ? t('vinInput.tryAutoRef') : t('vinInput.tryNhtsa')}
              </button>
            )}
            {tryError && (
              <p data-testid="vin-try-error" className="text-xs text-danger-500">
                {tryError}
              </p>
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

      {/* A full answer can still carry the decoder's own caveats (#219): a
          best guess among several matches, a registry record, a fallback. */}
      {decodedData && !errorMessage && decodedData.decode_quality === 'full' &&
        (decodedData.notes ?? []).some(isDecoderNote) && (
        <ul
          data-testid="vin-full-notes"
          className="list-disc pl-5 text-xs text-text-mute"
        >
          {(decodedData.notes ?? []).filter(isDecoderNote).map((note) => (
            <li key={note}>{t(NOTE_LABEL_KEYS[note] ?? note)}</li>
          ))}
        </ul>
      )}

      {/* Decoded data display */}
      {decodedData && !errorMessage && (
        <Card className="bg-surface-2">
          <h4 className={`text-lg font-semibold ${decodedData.decoded_by ? 'mb-1' : 'mb-3'}`}>
            {t('vinInput.decodedTitle')}
          </h4>
          {decodedData.decoded_by && (
            <p className="mb-3 text-xs text-text-mute">
              {t('vinInput.decodedBy', { provider: t(PROVIDER_LABEL_KEYS[decodedData.decoded_by]) })}
            </p>
          )}
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
