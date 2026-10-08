/**
 * Import an EU registration certificate (carte grise, Zulassungsbescheinigung,
 * kentekenbewijs…) (#211).
 *
 * Without a `vin`, the file is only READ (the wizard, before the vehicle
 * exists) and the result is handed to `onParsed`. With a `vin`, the file is
 * stored on the vehicle, its empty fields are filled and the last inspection
 * is recorded; `onImported` gets the outcome.
 *
 * A PDF with a text layer is read on the server without any model. A photo
 * or a scan needs the vision model an admin turns on in Settings →
 * Integrations; when it is off, the hint says so up front and the 409 the
 * server answers with says it again. Everything shown can still be typed.
 */

import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FileText, Sparkles, Upload, AlertTriangle } from 'lucide-react'
import { Button, Drawer } from './ui'
import { useAiDocumentReading } from '@/hooks/queries/useAiDocumentReading'
import { useDateLocale } from '@/hooks/useDateLocale'
import { countryName, asCountryCode } from '@/constants/countries'
import { getActionErrorMessage } from '@/utils/httpErrorHandler'
import {
  CERTIFICATE_ACCEPT,
  CERTIFICATE_MAX_BYTES,
  CERTIFICATE_MIME_TYPES,
  isAiNotConfigured,
  isPdf,
  registrationCertificateService,
  type RegistrationImportResponse,
  type RegistrationParseResponse,
} from '@/services/registrationCertificateService'

/** The certificate fields the result table lists, in the certificate's order. */
const FIELD_ROWS = [
  'plate',
  'first_registration',
  'holder',
  'make',
  'type_variant_version',
  'commercial_name',
  'vin',
  'max_mass_kg',
  'mass_in_service_kg',
  'eu_category',
  'national_category',
  'type_approval',
  'displacement_cc',
  'power_kw',
  'energy_code',
  'fiscal_power',
  'seats',
  'co2_g_km',
  'euro_class',
  'last_inspection',
] as const
type FieldRow = (typeof FIELD_ROWS)[number]

/** Every certificate field row carries its own translated label. */
const FIELD_LABEL_KEYS: Record<FieldRow, string> = {
  plate: 'registrationImport.fields.plate',
  first_registration: 'registrationImport.fields.first_registration',
  holder: 'registrationImport.fields.holder',
  make: 'registrationImport.fields.make',
  type_variant_version: 'registrationImport.fields.type_variant_version',
  commercial_name: 'registrationImport.fields.commercial_name',
  vin: 'registrationImport.fields.vin',
  max_mass_kg: 'registrationImport.fields.max_mass_kg',
  mass_in_service_kg: 'registrationImport.fields.mass_in_service_kg',
  eu_category: 'registrationImport.fields.eu_category',
  national_category: 'registrationImport.fields.national_category',
  type_approval: 'registrationImport.fields.type_approval',
  displacement_cc: 'registrationImport.fields.displacement_cc',
  power_kw: 'registrationImport.fields.power_kw',
  energy_code: 'registrationImport.fields.energy_code',
  fiscal_power: 'registrationImport.fields.fiscal_power',
  seats: 'registrationImport.fields.seats',
  co2_g_km: 'registrationImport.fields.co2_g_km',
  euro_class: 'registrationImport.fields.euro_class',
  last_inspection: 'registrationImport.fields.last_inspection',
}

/** The vehicle fields an import may write, labelled like the edit form. */
const VEHICLE_FIELD_LABEL_KEYS: Record<string, string> = {
  license_plate: 'edit.licensePlate',
  registration_country: 'edit.registrationCountry',
  first_registration_date: 'edit.firstRegistrationDate',
  make: 'wizard.make',
  model: 'wizard.model',
  vehicle_type: 'edit.vehicleType',
  displacement_l: 'edit.displacement',
  fuel_type: 'wizard.fuelType',
  fuel_type_secondary: 'registrationImport.vehicleFields.fuel_type_secondary',
  power_kw: 'edit.powerKw',
  fiscal_power: 'edit.fiscalPower',
  co2_g_km: 'edit.co2',
  euro_emission_class: 'edit.euroClass',
  eu_category: 'edit.euCategory',
  national_category: 'edit.nationalCategory',
  vin: 'wizard.vin',
}

const CONFIDENCE_KEYS: Record<string, string> = {
  high: 'registrationImport.confidenceLevel.high',
  medium: 'registrationImport.confidenceLevel.medium',
  low: 'registrationImport.confidenceLevel.low',
}

const CONFIDENCE_CLASS: Record<string, string> = {
  high: 'bg-success/15 text-success',
  medium: 'bg-warning/15 text-warning',
  low: 'bg-danger/15 text-danger',
}

export interface RegistrationCertificateImportProps {
  /** Set: store and apply on this vehicle. Unset: read only. */
  vin?: string
  /** A hint for the plate format when the document says nothing. */
  country?: string | null
  onParsed?: (result: RegistrationParseResponse, file: File) => void
  onImported?: (result: RegistrationImportResponse) => void
}

export default function RegistrationCertificateImport({
  vin,
  country,
  onParsed,
  onImported,
}: RegistrationCertificateImportProps) {
  const { t } = useTranslation('vehicles')
  const locale = useDateLocale()
  const { enabled: aiEnabled } = useAiDocumentReading()
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [aiMissing, setAiMissing] = useState(false)
  const [overwrite, setOverwrite] = useState(false)
  const [parse, setParse] = useState<RegistrationParseResponse | null>(null)
  const [outcome, setOutcome] = useState<RegistrationImportResponse | null>(null)

  const choose = (selected: File | null) => {
    setParse(null)
    setOutcome(null)
    setError(null)
    setAiMissing(false)
    if (!selected) {
      setFile(null)
      return
    }
    if (!CERTIFICATE_MIME_TYPES.includes(selected.type) && !/\.(pdf|jpe?g|png|heic|heif)$/i.test(selected.name)) {
      setFile(null)
      setError(t('registrationImport.invalidFileType'))
      return
    }
    if (selected.size > CERTIFICATE_MAX_BYTES) {
      setFile(null)
      setError(t('registrationImport.fileTooLarge'))
      return
    }
    setFile(selected)
  }

  const run = async () => {
    if (!file) return
    setBusy(true)
    setError(null)
    setAiMissing(false)
    try {
      if (vin) {
        const result = await registrationCertificateService.importForVehicle(vin, file, overwrite)
        setParse(result.parse)
        setOutcome(result)
        onImported?.(result)
      } else {
        const result = await registrationCertificateService.parse(file, country)
        setParse(result)
        onParsed?.(result, file)
      }
    } catch (err) {
      if (isAiNotConfigured(err)) {
        setAiMissing(true)
      } else {
        setError(getActionErrorMessage(err, t(vin ? 'registrationImport.importAction' : 'registrationImport.readAction')))
      }
    } finally {
      setBusy(false)
    }
  }

  const needsAi = file !== null && !isPdf(file) && !aiEnabled
  const fields = (parse?.fields ?? {}) as Record<string, unknown>
  // Optional on the wire (the server fills them with defaults), never here.
  const warnings = parse?.warnings ?? []
  const taxes = (fields.taxes ?? {}) as Record<string, string>
  const rows = FIELD_ROWS.filter((name) => fields[name] !== null && fields[name] !== undefined && fields[name] !== '')
  const detectedCountry = asCountryCode(parse?.country)

  return (
    <div className="space-y-4" data-testid="registration-certificate-import">
      <p className="text-sm text-text-mute">
        {aiEnabled ? t('registrationImport.hint') : t('registrationImport.aiNotConfiguredHint')}
      </p>

      <div className="flex flex-wrap items-center gap-3">
        <input
          ref={inputRef}
          type="file"
          accept={CERTIFICATE_ACCEPT}
          onChange={(e) => choose(e.target.files?.[0] ?? null)}
          className="hidden"
          aria-label={t('registrationImport.choose')}
          data-testid="registration-certificate-file"
        />
        <Button variant="secondary" icon={FileText} onClick={() => inputRef.current?.click()}>
          {t('registrationImport.choose')}
        </Button>
        {file && (
          <span className="text-sm text-text" data-testid="registration-certificate-filename">
            {file.name}
          </span>
        )}
        <Button
          variant="primary"
          icon={vin ? Upload : Sparkles}
          disabled={!file || busy || needsAi}
          onClick={run}
        >
          {busy
            ? t('registrationImport.reading')
            : vin
              ? t('registrationImport.import')
              : t('registrationImport.read')}
        </Button>
      </div>
      <p className="text-xs text-text-faint">{t('registrationImport.fileTypes')}</p>

      {vin && (
        <label className="flex items-start gap-2 text-sm text-text">
          <input
            type="checkbox"
            checked={overwrite}
            onChange={(e) => setOverwrite(e.target.checked)}
            className="mt-0.5"
          />
          <span>
            {t('registrationImport.overwrite')}
            <span className="block text-xs text-text-mute">{t('registrationImport.overwriteHint')}</span>
          </span>
        </label>
      )}

      {(needsAi || aiMissing) && (
        <div
          role="status"
          className="flex items-start gap-2 rounded-panel border border-warning/40 bg-warning/10 p-3 text-sm text-text"
        >
          <AlertTriangle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
          <span>{t('registrationImport.aiNotConfigured')}</span>
        </div>
      )}

      {error && (
        <div role="alert" className="rounded-panel border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
          {error}
        </div>
      )}

      {parse && (
        <div className="space-y-3 rounded-panel border border-border bg-surface-2 p-4" data-testid="registration-certificate-result">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                parse.source === 'llm' ? 'bg-(--accent-fg)/15 text-(--accent-fg)' : 'bg-surface text-text-mute'
              }`}
            >
              {parse.source === 'llm'
                ? t('registrationImport.readByAi', { model: parse.model ?? '' })
                : t('registrationImport.readFromPdf')}
            </span>
            <span className="text-text-mute">
              {t('registrationImport.confidence', { score: Math.round(parse.confidence) })}
            </span>
            {detectedCountry && (
              <span className="text-text-mute">
                {t('registrationImport.detectedCountry', { country: countryName(detectedCountry, locale) })}
              </span>
            )}
          </div>

          {outcome && (
            <div className="space-y-1 text-sm">
              <p className="text-text">
                {outcome.applied.length > 0
                  ? t('registrationImport.appliedFields', {
                      fields: outcome.applied.map((key) => t(VEHICLE_FIELD_LABEL_KEYS[key] ?? key)).join(', '),
                    })
                  : t('registrationImport.nothingApplied')}
              </p>
              {outcome.skipped.length > 0 && (
                <p className="text-text-mute">
                  {t('registrationImport.skippedFields', {
                    fields: outcome.skipped.map((key) => t(VEHICLE_FIELD_LABEL_KEYS[key] ?? key)).join(', '),
                  })}
                </p>
              )}
              {outcome.inspection_recorded && parse.last_inspection_date && (
                <p className="text-text-mute">
                  {t('registrationImport.recordedInspection', { date: parse.last_inspection_date })}
                </p>
              )}
            </div>
          )}

          {rows.length === 0 ? (
            <p className="text-sm text-text-mute">{t('registrationImport.noFields')}</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-text-faint">
                  <th className="py-1 pr-3 font-medium">{t('registrationImport.fieldLabel')}</th>
                  <th className="py-1 pr-3 font-medium">{t('registrationImport.valueLabel')}</th>
                  <th className="py-1 font-medium">{t('registrationImport.confidenceLabel')}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((name) => {
                  const level = parse.field_confidence?.[name]
                  return (
                    <tr key={name} className="border-t border-border/60">
                      <td className="py-1 pr-3 text-text-mute">{t(FIELD_LABEL_KEYS[name])}</td>
                      <td className="py-1 pr-3 font-mono text-text">{String(fields[name])}</td>
                      <td className="py-1">
                        {level && (
                          <span className={`rounded-full px-2 py-0.5 text-xs ${CONFIDENCE_CLASS[level] ?? ''}`}>
                            {t(CONFIDENCE_KEYS[level] ?? level)}
                          </span>
                        )}
                      </td>
                    </tr>
                  )
                })}
                {Object.entries(taxes).map(([code, amount]) => (
                  <tr key={code} className="border-t border-border/60">
                    <td className="py-1 pr-3 text-text-mute">{t('registrationImport.fields.taxes', { code })}</td>
                    <td className="py-1 pr-3 font-mono text-text">{amount}</td>
                    <td className="py-1" />
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {warnings.length > 0 && (
            <ul className="list-disc space-y-0.5 pl-5 text-xs text-warning" data-testid="registration-certificate-warnings">
              {warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

/** The detail page's drawer around the import, stacked over the edit sidecar. */
export function RegistrationCertificateDrawer({
  vin,
  onClose,
  onImported,
}: {
  vin: string
  onClose: () => void
  onImported: (result: RegistrationImportResponse) => void
}) {
  const { t } = useTranslation('vehicles')
  return (
    <Drawer
      open
      onClose={onClose}
      title={t('registrationImport.title')}
      icon={FileText}
      width="lg"
      nested
      closeLabel={t('common:close')}
    >
      <RegistrationCertificateImport vin={vin} onImported={onImported} />
    </Drawer>
  )
}
