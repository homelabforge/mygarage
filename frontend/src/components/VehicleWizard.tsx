/**
 * Vehicle Wizard - 4-step vehicle creation process
 * Step 1: Identify: a VIN (entry, decode, certificate) or, for equipment and
 *         vehicles without one, a serial / HIN / chassis number / asset tag (#226)
 * Step 2: Basic Info
 * Step 3: Photos (optional)
 * Step 4: Review & Create
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { ChevronLeft, ChevronRight, Check } from 'lucide-react'
import VINInput from './VINInput'
import { FormError } from './FormError'
import { Stepper, Drawer, Button, Select, NumberInput, Tabs, registerDecimal } from './ui'
import type { VINDecodeResponse } from '../types/vin'
import type { VehicleCreate } from '../types/vehicle'
import { FUEL_TYPE_VALUES, FUEL_TYPE_LABELS, type FuelType } from '../constants/fuel'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import vehicleService from '../services/vehicleService'
import { makeVehicleEditSchema, vehicleTypeOptions, defaultUsageUnitForType, type VehicleEditFormData } from '../schemas/vehicle'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'
import { useDateLocale } from '../hooks/useDateLocale'
import { useResolvedCountry } from '../hooks/useResolvedCountry'
import { countryOptions } from '../constants/countries'
import RegistrationCertificateImport from './RegistrationCertificateImport'
import registrationCertificateService, {
  type RegistrationParseResponse,
} from '../services/registrationCertificateService'
import { taxTypeLabel } from '../schemas/tax'
import { VEHICLE_TYPES } from '../schemas/vehicle'
import { NON_VIN_IDENTIFIER_TYPES, identifierTypeLabel, type IdentifierType } from '../utils/vehicleIdentifier'
import { toast } from 'sonner'

/** The certificate fields the wizard form edits; the rest ride in the payload. */
type CertificateExtras = Pick<
  VehicleCreate,
  | 'fuel_type_secondary'
  | 'power_kw'
  | 'fiscal_power'
  | 'co2_g_km'
  | 'euro_emission_class'
  | 'eu_category'
  | 'national_category'
>
const CERTIFICATE_EXTRA_KEYS: (keyof CertificateExtras)[] = [
  'fuel_type_secondary',
  'power_kw',
  'fiscal_power',
  'co2_g_km',
  'euro_emission_class',
  'eu_category',
  'national_category',
]

interface ParsedCertificate {
  file: File
  parse: RegistrationParseResponse
  extras: CertificateExtras
}

/** VIN, or one of the identifiers a vehicle without a VIN has (#226). */
type IdentifyMode = 'vin' | 'no_vin'

interface VehicleWizardProps {
  onClose: () => void
  onSuccess?: (vin: string) => void
}

export default function VehicleWizard({ onClose, onSuccess }: VehicleWizardProps) {
  const { t } = useTranslation('vehicles')
  const { formatCurrency } = useCurrencyPreference()
  const navigate = useNavigate()
  const [currentStep, setCurrentStep] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Zod bakes its messages in at construction, so the schema is rebuilt when
  // the language changes. Only the resolver depends on it — no fetch, no
  // reset() — so a rebuild can't discard what the user typed.
  const schema = useMemo(() => makeVehicleEditSchema(t), [t])

  // Form management with react-hook-form + Zod
  const {
    register,
    handleSubmit: handleFormSubmit,
    setValue,
    watch,
    getValues,
    formState: { errors },
  } = useForm<VehicleEditFormData>({
    resolver: zodResolver(schema) as Resolver<VehicleEditFormData>,
    mode: 'onChange',
    defaultValues: {
      nickname: '',
      vehicle_type: 'Car',
      usage_unit: 'distance',
    },
  })

  // Wizard state
  const [vin, setVin] = useState('')
  // No VIN (#226): the server keys the vehicle itself, so nothing typed here
  // is ever the key. Everything after the create uses the key it returns.
  const [identifyMode, setIdentifyMode] = useState<IdentifyMode>('vin')
  const [identifierType, setIdentifierType] = useState<IdentifierType>('serial')
  const [identifier, setIdentifier] = useState('')
  // Set when a certificate's field E was a chassis number, not a VIN.
  const [chassisFromCertificate, setChassisFromCertificate] = useState(false)
  const noVin = identifyMode === 'no_vin'
  const [photoFiles, setPhotoFiles] = useState<File[]>([])
  // A registration certificate read on step 1 (#211): its file is filed on
  // the vehicle after creation, its taxes are offered on the review step,
  // and the fields the form does not edit ride along in the create payload.
  const [certificate, setCertificate] = useState<ParsedCertificate | null>(null)
  const [selectedTaxes, setSelectedTaxes] = useState<Set<string>>(new Set())
  // Where the VIN input's "import the certificate" link scrolls to.
  const certificateCardRef = useRef<HTMLDivElement>(null)

  // The registration country opens on the one this person's settings resolve
  // (their own country, else the instance default): a one-country household
  // never picks it. The select keeps "Not set" so it can still be cleared.
  const resolvedCountry = useResolvedCountry()
  const locale = useDateLocale()
  const registrationCountryOptions = useMemo(
    () => [{ value: '', label: t('edit.registrationCountryNone') }, ...countryOptions(locale)],
    [locale, t]
  )
  useEffect(() => {
    if (resolvedCountry && !getValues('registration_country')) {
      setValue('registration_country', resolvedCountry)
    }
  }, [resolvedCountry, getValues, setValue])

  // Watch form values for display
  const formData = watch()

  // Defined inside the component so `t` is in scope — module-scope arrays can't translate.
  const steps = [
    {
      number: 1,
      title: t('wizard.misc.stepIdentifyTitle'),
      description: noVin ? t('wizard.misc.stepNoVinDesc') : t('vinDemo.enterVIN'),
    },
    { number: 2, title: t('wizard.misc.stepDetailsTitle'), description: t('wizard.misc.stepDetailsDesc') },
    { number: 3, title: t('detail.misc.photos'), description: t('wizard.misc.stepPhotosDesc') },
    { number: 4, title: t('wizard.misc.stepReviewTitle'), description: t('wizard.misc.stepReviewDesc') },
  ]

  // Handle VIN decode - populate form with setValue
  const handleVinDecode = (data: VINDecodeResponse) => {
    const currentNickname = getValues('nickname')
    const generatedNickname = `${data.year || ''} ${data.make || ''} ${data.model || ''}`.trim()

    // Set all decoded values using setValue. A European VIN decodes with no
    // year and no model (#211): neither clears what was typed.
    if (data.year) setValue('year', data.year)
    if (data.make || !getValues('make')) setValue('make', data.make || null)
    if (data.model || !getValues('model')) setValue('model', data.model || null)
    setValue('nickname', currentNickname || generatedNickname)
    setValue('trim', data.trim || null)
    setValue('body_class', data.body_class || null)
    setValue('drive_type', data.drive_type || null)
    setValue('doors', data.doors || undefined)
    setValue('gvwr_class', data.gvwr || null)
    setValue('displacement_l', data.engine?.displacement_l || null)
    setValue('cylinders', data.engine?.cylinders || undefined)
    // Use the server-normalized fuel type (canonical FuelTypeEnum value),
    // not the raw NHTSA string — the vehicle API rejects non-canonical
    // fuel_type values with 422. Fall back to null when NHTSA's fuel type
    // couldn't be normalized. The OpenAPI type is a plain `string | null`
    // (the Pydantic field isn't a literal enum), but the value is always
    // one of FUEL_TYPE_VALUES when non-null — normalize_fuel_type() on the
    // backend guarantees it. The form's own zod validation (fuelTypeSchema)
    // re-checks this at submit time regardless.
    setValue('fuel_type', (data.engine?.fuel_type_normalized as FuelType | null) || null)
    setValue('transmission_type', data.transmission?.type || null)
    setValue('transmission_speeds', data.transmission?.speeds || null)
  }

  // A certificate fills what it can; every value stays editable on step 2,
  // which opens with a notice to check them. The VIN is taken only when none
  // was typed. A patch value is `unknown` on the wire; each one is checked
  // against the form's own vocabulary before it is set.
  const handleCertificateParsed = (parse: RegistrationParseResponse, file: File) => {
    const patch = parse.vehicle_patch as Record<string, unknown>
    const text = (key: string): string | null => (typeof patch[key] === 'string' ? (patch[key] as string) : null)
    const whole = (key: string): number | null => (typeof patch[key] === 'number' ? (patch[key] as number) : null)

    const certificateVin = text('vin')
    if (certificateVin && !vin) setVin(certificateVin)
    // An old vehicle's field E is a chassis number (#226): it goes in as
    // one, under No VIN, unless a full VIN was already typed.
    const fields = parse.fields as Record<string, unknown>
    const chassis = typeof fields.chassis_number === 'string' ? fields.chassis_number : null
    const routeToChassis = !certificateVin && chassis !== null && vin.length !== 17
    if (routeToChassis) {
      setIdentifyMode('no_vin')
      setIdentifierType('chassis')
      setIdentifier(chassis)
    }
    setChassisFromCertificate(routeToChassis)
    for (const key of ['license_plate', 'registration_country', 'first_registration_date', 'make', 'model', 'displacement_l'] as const) {
      const value = text(key)
      if (value) setValue(key, value)
    }
    const vehicleType = text('vehicle_type')
    if (vehicleType && (VEHICLE_TYPES as readonly string[]).includes(vehicleType)) {
      setValue('vehicle_type', vehicleType as (typeof VEHICLE_TYPES)[number])
      setValue('usage_unit', defaultUsageUnitForType(vehicleType))
    }
    const fuelType = text('fuel_type')
    if (fuelType && (FUEL_TYPE_VALUES as readonly string[]).includes(fuelType)) {
      setValue('fuel_type', fuelType as FuelType)
    }
    const firstRegistration = text('first_registration_date')
    if (firstRegistration && !getValues('year')) {
      setValue('year', Number(firstRegistration.slice(0, 4)))
    }
    if (!getValues('nickname')) {
      setValue('nickname', `${getValues('year') || ''} ${text('make') || ''} ${text('model') || ''}`.trim())
    }

    const extras: CertificateExtras = {}
    for (const key of CERTIFICATE_EXTRA_KEYS) {
      const value = key === 'fuel_type_secondary' || key === 'euro_emission_class' || key === 'eu_category' || key === 'national_category'
        ? text(key)
        : whole(key)
      if (value !== null) (extras as Record<string, unknown>)[key] = value
    }
    setCertificate({ file, parse, extras })
    setSelectedTaxes(new Set((parse.suggested_tax_records ?? []).map((record) => record.code)))
    if (routeToChassis || (certificateVin ?? vin).length === 17) setCurrentStep(2)
  }

  const toggleTax = (code: string, checked: boolean) => {
    setSelectedTaxes((previous) => {
      const next = new Set(previous)
      if (checked) next.add(code)
      else next.delete(code)
      return next
    })
  }

  // Handle photo selection
  const handlePhotoChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setPhotoFiles(Array.from(e.target.files))
    }
  }

  // Validate current step
  const canProceed = () => {
    if (currentStep === 1) {
      if (noVin) return identifierType === 'none' || identifier.trim().length > 0
      return vin.length === 17
    }
    if (currentStep === 2) {
      // Check required fields and form validity
      const values = getValues()
      return Boolean(values.nickname && values.vehicle_type) && Object.keys(errors).length === 0
    }
    return true
  }

  // Handle next step
  const handleNext = () => {
    if (canProceed() && currentStep < 4) {
      setCurrentStep(currentStep + 1)
      setError(null)
    }
  }

  // Handle previous step
  const handlePrevious = () => {
    if (currentStep > 1) {
      setCurrentStep(currentStep - 1)
      setError(null)
    }
  }

  // Handle form submission - wrapped with form validation
  const onSubmit = async (validatedData: VehicleEditFormData) => {
    setLoading(true)
    setError(null)

    try {
      // Create vehicle with validated form data
      // No VIN sends no `vin` at all: the server generates the key.
      const identity: Pick<VehicleCreate, 'vin' | 'identifier_type' | 'identifier'> = noVin
        ? { identifier_type: identifierType, identifier: identifierType === 'none' ? null : identifier.trim() }
        : { vin, identifier_type: 'vin' }
      const vehicleData: VehicleCreate = {
        ...identity,
        nickname: validatedData.nickname,
        vehicle_type: validatedData.vehicle_type,
        usage_unit: validatedData.usage_unit,
        secondary_usage_enabled: validatedData.secondary_usage_enabled,
        year: validatedData.year,
        make: validatedData.make,
        model: validatedData.model,
        license_plate: validatedData.license_plate,
        registration_country: validatedData.registration_country,
        first_registration_date: validatedData.first_registration_date,
        color: validatedData.color,
        purchase_date: validatedData.purchase_date,
        purchase_price: validatedData.purchase_price,
        // VIN decoded fields
        trim: validatedData.trim,
        body_class: validatedData.body_class,
        drive_type: validatedData.drive_type,
        doors: validatedData.doors,
        gvwr_class: validatedData.gvwr_class,
        displacement_l: validatedData.displacement_l,
        cylinders: validatedData.cylinders,
        fuel_type: validatedData.fuel_type,
        transmission_type: validatedData.transmission_type,
        transmission_speeds: validatedData.transmission_speeds,
        // The certificate's fields the form does not edit (#211).
        ...(certificate?.extras ?? {}),
      }

      const createdVehicle = await vehicleService.create(vehicleData)

      // File the certificate on the new vehicle (it records the last
      // inspection) and create the taxes ticked on the review step. The
      // parse token lets the server reuse its step-1 read of this same file
      // (no second model call), and the taxes come from that read, by code.
      // The vehicle exists either way: a failure here is a toast, and the
      // import can be redone from the vehicle's settings.
      if (certificate) {
        try {
          await registrationCertificateService.importForVehicle(createdVehicle.vin, certificate.file, {
            parseToken: certificate.parse.parse_token,
            taxCodes: (certificate.parse.suggested_tax_records ?? [])
              .map((record) => record.code)
              .filter((code) => selectedTaxes.has(code)),
          })
        } catch {
          toast.warning(t('registrationImport.importFailedAfterCreate'))
        }
      }

      // Upload photos if any, set first one as main photo
      if (photoFiles.length > 0) {
        let firstPhotoFilename: string | null = null
        for (const file of photoFiles) {
          const uploadResponse = await vehicleService.uploadPhoto(createdVehicle.vin, file)
          if (!firstPhotoFilename) {
            firstPhotoFilename = uploadResponse.filename
          }
        }
        // Set the first uploaded photo as the main photo
        if (firstPhotoFilename) {
          await vehicleService.setMainPhoto(createdVehicle.vin, firstPhotoFilename)
        }
      }

      // Success
      if (onSuccess) {
        onSuccess(createdVehicle.vin)
      } else {
        navigate(`/vehicles/${createdVehicle.vin}`)
      }
      onClose()
    } catch (err: unknown) {
      setError(getActionErrorMessage(err, t('wizard.misc.createAction')))
      setLoading(false)
    }
  }

  const handleSubmit = () => {
    handleFormSubmit(onSubmit)()
  }

  return (
    <Drawer
      open
      onClose={onClose}
      title={t('wizard.title')}
      width="lg"
      closeLabel={t('common:close')}
      footer={
        <div className="flex w-full items-center justify-between">
          <Button
            variant="ghost"
            icon={ChevronLeft}
            disabled={currentStep === 1}
            onClick={handlePrevious}
          >
            {t('wizard.misc.previous')}
          </Button>

          <div className="flex items-center gap-3">
            <Button variant="secondary" onClick={onClose}>
              {t('wizard.misc.cancel')}
            </Button>

            {currentStep < 4 ? (
              <Button
                variant="primary"
                iconRight={ChevronRight}
                disabled={!canProceed()}
                onClick={handleNext}
              >
                {t('wizard.next')}
              </Button>
            ) : (
              // Bespoke success button (G4 (e)): no `success` Button variant, and
              // it swaps BOTH the icon (Check<->spinner) and the label
              // (createVehicle<->creating) on `loading`, which Button's icon-only
              // `loading` prop cannot express.
              <button
                type="button"
                onClick={handleSubmit}
                disabled={loading}
                className="ui-focus-ring ui-motion inline-flex h-btn-md items-center gap-2 rounded-control bg-success px-4 text-sm font-semibold text-on-status hover:bg-success/90 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
              >
                {loading ? (
                  <>
                    <div className="h-4 w-4 animate-spin rounded-full border-2 border-on-status border-t-transparent" />
                    <span>{t('wizard.misc.creating')}</span>
                  </>
                ) : (
                  <>
                    <Check aria-hidden="true" className="h-4 w-4" />
                    <span>{t('wizard.misc.createVehicle')}</span>
                  </>
                )}
              </button>
            )}
          </div>
        </div>
      }
    >
      {/* First body row: step-progress subtitle (preserves e2e getByText('Enter VIN')) */}
      <p className="text-sm text-text-mute">
        {t('wizard.misc.stepProgress', {
          current: currentStep,
          total: steps.length,
          description: steps[currentStep - 1].description,
        })}
      </p>

      {/* Progress Steps */}
      <div className="mt-4">
        <Stepper
          steps={steps}
          current={currentStep}
          label={t('wizard.misc.progressLabel')}
          valueText={t('wizard.stepOf', { current: currentStep, total: steps.length })}
        />
      </div>

      {/* Content */}
      <div className="mt-6">
        {error && (
          <div className="mb-4 p-4 bg-danger/10 border border-danger rounded-control text-danger">
            {error}
          </div>
        )}

        {/* Step 1: Identify. VIN, or No VIN for equipment and old vehicles (#226). */}
        {currentStep === 1 && (
          <div className="space-y-6">
            <Tabs
              variant="segmented"
              label={t('identifier.modeLabel')}
              activeId={identifyMode}
              onChange={(id) => setIdentifyMode(id as IdentifyMode)}
              items={[
                { id: 'vin', label: t('identifier.hasVin') },
                { id: 'no_vin', label: t('identifier.noVin') },
              ]}
            />

            {noVin ? (
              <div className="space-y-4" data-testid="wizard-no-vin">
                <p className="text-sm text-text-mute">{t('identifier.noVinHelp')}</p>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="wizard-identifier-type" className="block text-sm font-medium text-text-mid mb-2">
                      {t('identifier.typeLabel')}
                    </label>
                    <Select
                      id="wizard-identifier-type"
                      value={identifierType}
                      onChange={(e) => setIdentifierType(e.target.value as IdentifierType)}
                      options={NON_VIN_IDENTIFIER_TYPES.map((kind) => ({
                        value: kind,
                        label: identifierTypeLabel(kind, t),
                      }))}
                    />
                  </div>
                  {identifierType !== 'none' && (
                    <div>
                      <label htmlFor="wizard-identifier" className="block text-sm font-medium text-text-mid mb-2">
                        {t('identifier.valueLabel')} <span className="text-danger">*</span>
                      </label>
                      <input
                        id="wizard-identifier"
                        type="text"
                        maxLength={64}
                        value={identifier}
                        onChange={(e) => setIdentifier(e.target.value)}
                        className="w-full bg-surface border border-border rounded-control px-4 py-2 text-text focus:outline-none focus:border-(--accent-solid)"
                        placeholder={t('identifier.valuePlaceholder')}
                      />
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <>
                <div>
                  <h3 className="text-lg font-semibold text-text mb-4">
                    {t('wizard.misc.enterVinHeading')}
                  </h3>
                  <VINInput
                    value={vin}
                    onChange={setVin}
                    onDecode={handleVinDecode}
                    autoValidate={true}
                    checkDuplicate={true}
                    onImportCertificate={() =>
                      certificateCardRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                    }
                  />
                </div>

                {/* Or read the registration certificate (#211): fills the VIN
                    and the fields of step 2 from the document. */}
                <div ref={certificateCardRef} className="rounded-panel border border-border bg-surface-2 p-4">
                  <h3 className="mb-2 text-base font-semibold text-text">{t('registrationImport.title')}</h3>
                  <RegistrationCertificateImport country={resolvedCountry} onParsed={handleCertificateParsed} />
                </div>
              </>
            )}
          </div>
        )}

        {/* Step 2: Basic Info */}
        {currentStep === 2 && (
          <div className="space-y-6">
            <h3 className="text-lg font-semibold text-text mb-4">{t('edit.vehicleDetails')}</h3>

            {certificate && (
              <div
                role="status"
                className="rounded-panel border border-(--accent-fg)/40 bg-(--accent-fg)/10 p-3 text-sm text-text"
              >
                {t('registrationImport.checkFields')}
                {noVin && chassisFromCertificate && (
                  <span className="mt-1 block">{t('registrationImport.chassisRouted')}</span>
                )}
              </div>
            )}

            <div>
              <label htmlFor="wizard-nickname" className="block text-sm font-medium text-text-mid mb-2">
                {t('wizard.nickname')} <span className="text-danger">*</span>
              </label>
              <input
                id="wizard-nickname"
                type="text"
                {...register('nickname')}
                className="w-full bg-surface border border-border rounded-control px-4 py-2 text-text focus:outline-none focus:border-(--accent-solid)"
                placeholder={t('wizard.misc.nicknamePlaceholder')}
              />
              <FormError error={errors.nickname} />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label htmlFor="wizard-vehicle-type" className="block text-sm font-medium text-text-mid mb-2">
                  {t('edit.vehicleType')} <span className="text-danger">*</span>
                </label>
                <Select
                  id="wizard-vehicle-type"
                  {...register('vehicle_type', {
                    onChange: (e) => {
                      setValue('usage_unit', defaultUsageUnitForType(e.target.value))
                    },
                  })}
                  invalid={!!errors.vehicle_type}
                  options={vehicleTypeOptions(t, { equipmentFirst: noVin })}
                />
                <FormError error={errors.vehicle_type} />
              </div>

              <div>
                <label htmlFor="wizard-year" className="block text-sm font-medium text-text-mid mb-2">{t('wizard.year')}</label>
                <NumberInput
                  id="wizard-year"
                  {...registerDecimal(register, 'year')}
                  invalid={!!errors.year}
                  placeholder="2019"
                />
                <FormError error={errors.year} />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label htmlFor="wizard-make" className="block text-sm font-medium text-text-mid mb-2">{t('wizard.make')}</label>
                <input
                  id="wizard-make"
                  type="text"
                  {...register('make')}
                  className="w-full bg-surface border border-border rounded-control px-4 py-2 text-text focus:outline-none focus:border-(--accent-solid)"
                  placeholder="MITSUBISHI"
                />
                <FormError error={errors.make} />
              </div>

              <div>
                <label htmlFor="wizard-model" className="block text-sm font-medium text-text-mid mb-2">{t('wizard.model')}</label>
                <input
                  id="wizard-model"
                  type="text"
                  {...register('model')}
                  className="w-full bg-surface border border-border rounded-control px-4 py-2 text-text focus:outline-none focus:border-(--accent-solid)"
                  placeholder={t('wizard.misc.modelPlaceholder')}
                />
                <FormError error={errors.model} />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label htmlFor="wizard-color" className="block text-sm font-medium text-text-mid mb-2">{t('wizard.color')}</label>
                <input
                  id="wizard-color"
                  type="text"
                  {...register('color')}
                  className="w-full bg-surface border border-border rounded-control px-4 py-2 text-text focus:outline-none focus:border-(--accent-solid)"
                  placeholder={t('wizard.misc.colorPlaceholder')}
                />
                <FormError error={errors.color} />
              </div>

              <div>
                <label htmlFor="wizard-license-plate" className="block text-sm font-medium text-text-mid mb-2">
                  {t('edit.licensePlate')}
                </label>
                <input
                  id="wizard-license-plate"
                  type="text"
                  {...register('license_plate')}
                  className="w-full bg-surface border border-border rounded-control px-4 py-2 text-text focus:outline-none focus:border-(--accent-solid)"
                  placeholder={t('wizard.misc.licensePlatePlaceholder')}
                />
                <FormError error={errors.license_plate} />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label htmlFor="wizard-purchase-date" className="block text-sm font-medium text-text-mid mb-2">
                  {t('edit.purchaseDate')}
                </label>
                <input
                  id="wizard-purchase-date"
                  type="date"
                  {...register('purchase_date')}
                  className="w-full bg-surface border border-border rounded-control px-4 py-2 text-text focus:outline-none focus:border-(--accent-solid)"
                />
                <FormError error={errors.purchase_date} />
              </div>

              <div>
                <label htmlFor="wizard-purchase-price" className="block text-sm font-medium text-text-mid mb-2">
                  {t('edit.purchasePrice')}
                </label>
                <NumberInput
                  id="wizard-purchase-price"
                  {...registerDecimal(register, 'purchase_price')}
                  invalid={!!errors.purchase_price}
                  placeholder="15 000,00"
                />
                <FormError error={errors.purchase_price} />
              </div>
            </div>

            {/* Registration country and first registration date (#211). The
                country opens on the one Quick Settings resolves, so a French
                household never has to pick it; the date drives the technical
                inspection cadence of the country's profile. */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-text-mid mb-2">
                  {t('edit.registrationCountry')}
                </label>
                <Select
                  {...register('registration_country')}
                  invalid={!!errors.registration_country}
                  options={registrationCountryOptions}
                />
                <p className="mt-1 text-xs text-garage-text-muted">
                  {t('edit.registrationCountryHint')}
                </p>
                <FormError error={errors.registration_country} />
              </div>

              <div>
                <label className="block text-sm font-medium text-text-mid mb-2">
                  {t('edit.firstRegistrationDate')}
                </label>
                <input
                  type="date"
                  {...register('first_registration_date')}
                  className="w-full bg-surface border border-border rounded-control px-4 py-2 text-text focus:outline-none focus:border-(--accent-solid)"
                />
                <p className="mt-1 text-xs text-garage-text-muted">
                  {t('edit.firstRegistrationDateHint')}
                </p>
                <FormError error={errors.first_registration_date} />
              </div>
            </div>

            <h3 className="text-lg font-semibold text-text mt-6 mb-4">{t('wizard.misc.vinDecodedInfoOptional')}</h3>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label htmlFor="wizard-trim" className="block text-sm font-medium text-text-mid mb-2">{t('wizard.trim')}</label>
                <input
                  id="wizard-trim"
                  type="text"
                  {...register('trim')}
                  className="w-full bg-surface border border-border rounded-control px-4 py-2 text-text focus:outline-none focus:border-(--accent-solid)"
                  placeholder={t('wizard.misc.trimPlaceholder')}
                />
                <FormError error={errors.trim} />
              </div>

              <div>
                <label htmlFor="wizard-body-class" className="block text-sm font-medium text-text-mid mb-2">{t('edit.bodyClass')}</label>
                <input
                  id="wizard-body-class"
                  type="text"
                  {...register('body_class')}
                  className="w-full bg-surface border border-border rounded-control px-4 py-2 text-text focus:outline-none focus:border-(--accent-solid)"
                  placeholder={t('wizard.misc.bodyClassPlaceholder')}
                />
                <FormError error={errors.body_class} />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label htmlFor="wizard-drive-type" className="block text-sm font-medium text-text-mid mb-2">{t('edit.driveType')}</label>
                <input
                  id="wizard-drive-type"
                  type="text"
                  {...register('drive_type')}
                  className="w-full bg-surface border border-border rounded-control px-4 py-2 text-text focus:outline-none focus:border-(--accent-solid)"
                  placeholder={t('wizard.misc.driveTypePlaceholder')}
                />
                <FormError error={errors.drive_type} />
              </div>

              <div>
                <label htmlFor="wizard-doors" className="block text-sm font-medium text-text-mid mb-2">{t('edit.doors')}</label>
                <NumberInput
                  id="wizard-doors"
                  {...registerDecimal(register, 'doors')}
                  invalid={!!errors.doors}
                  placeholder="4"
                />
                <FormError error={errors.doors} />
              </div>
            </div>

            <h3 className="text-lg font-semibold text-text mt-6 mb-4">{t('wizard.misc.engineTransmissionOptional')}</h3>

            <div className="grid grid-cols-3 gap-4">
              <div>
                <label htmlFor="wizard-displacement" className="block text-sm font-medium text-text-mid mb-2">{t('edit.displacement')}</label>
                <input
                  id="wizard-displacement"
                  type="text"
                  {...register('displacement_l')}
                  className="w-full bg-surface border border-border rounded-control px-4 py-2 text-text focus:outline-none focus:border-(--accent-solid)"
                  placeholder="2,0"
                />
                <FormError error={errors.displacement_l} />
              </div>

              <div>
                <label htmlFor="wizard-cylinders" className="block text-sm font-medium text-text-mid mb-2">{t('edit.cylinders')}</label>
                <NumberInput
                  id="wizard-cylinders"
                  {...registerDecimal(register, 'cylinders')}
                  invalid={!!errors.cylinders}
                  placeholder="4"
                />
                <FormError error={errors.cylinders} />
              </div>

              <div>
                <label
                  htmlFor="wizard-fuel-type"
                  className="block text-sm font-medium text-text-mid mb-2"
                >
                  {t('wizard.fuelType')}
                </label>
                <Select
                  id="wizard-fuel-type"
                  aria-label={t('wizard.fuelType')}
                  {...register('fuel_type')}
                  invalid={!!errors.fuel_type}
                  placeholder="—"
                  options={FUEL_TYPE_VALUES.map((value) => ({
                    value,
                    label: t(`forms:fuel.fuelTypes.${value}`, { defaultValue: FUEL_TYPE_LABELS[value] }),
                  }))}
                />
                <FormError error={errors.fuel_type} />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label htmlFor="wizard-transmission-type" className="block text-sm font-medium text-text-mid mb-2">{t('edit.transmissionType')}</label>
                <input
                  id="wizard-transmission-type"
                  type="text"
                  {...register('transmission_type')}
                  className="w-full bg-surface border border-border rounded-control px-4 py-2 text-text focus:outline-none focus:border-(--accent-solid)"
                  placeholder={t('wizard.misc.transmissionTypePlaceholder')}
                />
                <FormError error={errors.transmission_type} />
              </div>

              <div>
                <label htmlFor="wizard-transmission-speeds" className="block text-sm font-medium text-text-mid mb-2">{t('edit.transmissionSpeeds')}</label>
                <input
                  id="wizard-transmission-speeds"
                  type="text"
                  {...register('transmission_speeds')}
                  className="w-full bg-surface border border-border rounded-control px-4 py-2 text-text focus:outline-none focus:border-(--accent-solid)"
                  placeholder={t('wizard.misc.transmissionSpeedsPlaceholder')}
                />
                <FormError error={errors.transmission_speeds} />
              </div>
            </div>
          </div>
        )}

        {/* Step 3: Photos */}
        {currentStep === 3 && (
          <div className="space-y-6">
            <h3 className="text-lg font-semibold text-text mb-4">
              {t('wizard.misc.addPhotosOptional')}
            </h3>

            <div>
              <label htmlFor="wizard-photos" className="block text-sm font-medium text-text-mid mb-2">
                {t('wizard.misc.uploadPhotos')}
              </label>
              <input
                id="wizard-photos"
                type="file"
                accept="image/*"
                multiple
                onChange={handlePhotoChange}
                className="w-full bg-surface border border-border rounded-control px-4 py-2 text-text focus:outline-none focus:border-(--accent-solid) file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:bg-(--accent-solid) file:text-(--accent-on-solid) file:cursor-pointer"
              />
              <p className="text-sm text-text-mute mt-2">
                {t('wizard.misc.photoUploadHelp')}
              </p>
            </div>

            {photoFiles.length > 0 && (
              <div>
                <p className="text-sm font-medium text-text-mid mb-2">
                  {t('wizard.misc.selectedPhotos', { count: photoFiles.length })}
                </p>
                <ul className="space-y-1">
                  {photoFiles.map((file, index) => (
                    <li key={index} className="text-sm text-text-mute">
                      {t('wizard.misc.photoFileEntry', {
                        name: file.name,
                        size: (file.size / 1024 / 1024).toFixed(2),
                      })}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Step 4: Review */}
        {currentStep === 4 && (
          <div className="space-y-6">
            <h3 className="text-lg font-semibold text-text mb-4">{t('wizard.misc.reviewConfirm')}</h3>

            <div className="bg-surface border border-border rounded-panel p-6 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div data-testid="wizard-review-identifier">
                  {!noVin ? (
                    <>
                      <p className="text-sm text-text-mute">{t('wizard.vin')}</p>
                      <p className="text-text font-mono">{vin}</p>
                    </>
                  ) : identifierType === 'none' ? (
                    <>
                      <p className="text-sm text-text-mute">{t('identifier.typeLabel')}</p>
                      <p className="text-text">{identifierTypeLabel('none', t)}</p>
                    </>
                  ) : (
                    <>
                      <p className="text-sm text-text-mute">{identifierTypeLabel(identifierType, t)}</p>
                      <p className="text-text font-mono">{identifier.trim()}</p>
                    </>
                  )}
                </div>
                <div>
                  <p className="text-sm text-text-mute">{t('wizard.nickname')}</p>
                  <p className="text-text">{formData.nickname}</p>
                </div>
                <div>
                  <p className="text-sm text-text-mute">{t('detail.misc.type')}</p>
                  <p className="text-text">{formData.vehicle_type}</p>
                </div>
                <div>
                  <p className="text-sm text-text-mute">{t('wizard.year')}</p>
                  <p className="text-text">{formData.year || t('detail.notSpecified')}</p>
                </div>
                <div>
                  <p className="text-sm text-text-mute">{t('wizard.make')}</p>
                  <p className="text-text">{formData.make || t('detail.notSpecified')}</p>
                </div>
                <div>
                  <p className="text-sm text-text-mute">{t('wizard.model')}</p>
                  <p className="text-text">{formData.model || t('detail.notSpecified')}</p>
                </div>
                <div>
                  <p className="text-sm text-text-mute">{t('wizard.color')}</p>
                  <p className="text-text">{formData.color || t('detail.notSpecified')}</p>
                </div>
                <div>
                  <p className="text-sm text-text-mute">{t('edit.licensePlate')}</p>
                  <p className="text-text">{formData.license_plate || t('detail.notSpecified')}</p>
                </div>
                {formData.purchase_date && (
                  <div>
                    <p className="text-sm text-text-mute">{t('edit.purchaseDate')}</p>
                    <p className="text-text">{formData.purchase_date}</p>
                  </div>
                )}
                {formData.purchase_price && (
                  <div>
                    <p className="text-sm text-text-mute">{t('edit.purchasePrice')}</p>
                    <p className="text-text">
                      {formatCurrency(formData.purchase_price, {
                        fallback: t('detail.notSpecified'),
                      })}
                    </p>
                  </div>
                )}
              </div>

              {photoFiles.length > 0 && (
                <div>
                  <p className="text-sm text-text-mute mb-2">{t('wizard.misc.photosToUpload')}</p>
                  <p className="text-text">{t('wizard.misc.photoCount', { count: photoFiles.length })}</p>
                </div>
              )}

              {certificate && (
                <div className="space-y-2" data-testid="wizard-certificate-review">
                  <p className="text-sm text-text-mute">
                    {t('registrationImport.certificateFile', { name: certificate.file.name })}
                  </p>
                  {certificate.parse.last_inspection_date && (
                    <p className="text-sm text-text">
                      {t('registrationImport.lastInspection', { date: certificate.parse.last_inspection_date })}
                    </p>
                  )}
                  {(certificate.parse.suggested_tax_records ?? []).length > 0 && (
                    <div>
                      <p className="text-sm font-medium text-text">{t('registrationImport.suggestedTaxes')}</p>
                      <p className="mb-1 text-xs text-text-mute">{t('registrationImport.suggestedTaxesHint')}</p>
                      {(certificate.parse.suggested_tax_records ?? []).map((record) => (
                        <label key={record.code} className="flex items-center gap-2 text-sm text-text">
                          <input
                            type="checkbox"
                            checked={selectedTaxes.has(record.code)}
                            onChange={(e) => toggleTax(record.code, e.target.checked)}
                          />
                          <span>
                            {taxTypeLabel(record.tax_type, t)} · {formatCurrency(Number(record.amount))} · {record.date}
                          </span>
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </Drawer>
  )
}
