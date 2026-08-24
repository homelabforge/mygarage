/**
 * Vehicle Wizard - 4-step vehicle creation process
 * Step 1: VIN Entry & Decode
 * Step 2: Basic Info
 * Step 3: Photos (optional)
 * Step 4: Review & Create
 */

import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { ChevronLeft, ChevronRight, Check } from 'lucide-react'
import VINInput from './VINInput'
import { FormError } from './FormError'
import { Stepper, Drawer, Button, Select, NumberInput, registerDecimal } from './ui'
import type { VINDecodeResponse } from '../types/vin'
import type { VehicleCreate } from '../types/vehicle'
import { FUEL_TYPE_VALUES, FUEL_TYPE_LABELS, type FuelType } from '../constants/fuel'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import vehicleService from '../services/vehicleService'
import { makeVehicleEditSchema, vehicleTypeOptions, defaultUsageUnitForType, type VehicleEditFormData } from '../schemas/vehicle'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'

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
  const [photoFiles, setPhotoFiles] = useState<File[]>([])

  // Watch form values for display
  const formData = watch()

  // Defined inside the component so `t` is in scope — module-scope arrays can't translate.
  const steps = [
    { number: 1, title: t('wizard.vin'), description: t('vinDemo.enterVIN') },
    { number: 2, title: t('wizard.misc.stepDetailsTitle'), description: t('wizard.misc.stepDetailsDesc') },
    { number: 3, title: t('detail.misc.photos'), description: t('wizard.misc.stepPhotosDesc') },
    { number: 4, title: t('wizard.misc.stepReviewTitle'), description: t('wizard.misc.stepReviewDesc') },
  ]

  // Handle VIN decode - populate form with setValue
  const handleVinDecode = (data: VINDecodeResponse) => {
    const currentNickname = getValues('nickname')
    const generatedNickname = `${data.year || ''} ${data.make || ''} ${data.model || ''}`.trim()

    // Set all decoded values using setValue
    setValue('year', data.year || undefined)
    setValue('make', data.make || null)
    setValue('model', data.model || null)
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

  // Handle photo selection
  const handlePhotoChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setPhotoFiles(Array.from(e.target.files))
    }
  }

  // Validate current step
  const canProceed = () => {
    if (currentStep === 1) {
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
      const vehicleData: VehicleCreate = {
        vin: vin,
        nickname: validatedData.nickname,
        vehicle_type: validatedData.vehicle_type,
        usage_unit: validatedData.usage_unit,
        secondary_usage_enabled: validatedData.secondary_usage_enabled,
        year: validatedData.year,
        make: validatedData.make,
        model: validatedData.model,
        license_plate: validatedData.license_plate,
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
      }

      const createdVehicle = await vehicleService.create(vehicleData)

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

        {/* Step 1: VIN Entry */}
        {currentStep === 1 && (
          <div className="space-y-6">
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
              />
            </div>
          </div>
        )}

        {/* Step 2: Basic Info */}
        {currentStep === 2 && (
          <div className="space-y-6">
            <h3 className="text-lg font-semibold text-text mb-4">{t('edit.vehicleDetails')}</h3>

            <div>
              <label className="block text-sm font-medium text-text-mid mb-2">
                {t('wizard.nickname')} <span className="text-danger">*</span>
              </label>
              <input
                type="text"
                {...register('nickname')}
                className="w-full bg-surface border border-border rounded-control px-4 py-2 text-text focus:outline-none focus:border-(--accent-solid)"
                placeholder={t('wizard.misc.nicknamePlaceholder')}
              />
              <FormError error={errors.nickname} />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-text-mid mb-2">
                  {t('edit.vehicleType')} <span className="text-danger">*</span>
                </label>
                <Select
                  {...register('vehicle_type', {
                    onChange: (e) => {
                      setValue('usage_unit', defaultUsageUnitForType(e.target.value))
                    },
                  })}
                  invalid={!!errors.vehicle_type}
                  options={vehicleTypeOptions(t)}
                />
                <FormError error={errors.vehicle_type} />
              </div>

              <div>
                <label className="block text-sm font-medium text-text-mid mb-2">{t('wizard.year')}</label>
                <NumberInput
                  {...registerDecimal(register, 'year')}
                  invalid={!!errors.year}
                  placeholder="2019"
                />
                <FormError error={errors.year} />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-text-mid mb-2">{t('wizard.make')}</label>
                <input
                  type="text"
                  {...register('make')}
                  className="w-full bg-surface border border-border rounded-control px-4 py-2 text-text focus:outline-none focus:border-(--accent-solid)"
                  placeholder="MITSUBISHI"
                />
                <FormError error={errors.make} />
              </div>

              <div>
                <label className="block text-sm font-medium text-text-mid mb-2">{t('wizard.model')}</label>
                <input
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
                <label className="block text-sm font-medium text-text-mid mb-2">{t('wizard.color')}</label>
                <input
                  type="text"
                  {...register('color')}
                  className="w-full bg-surface border border-border rounded-control px-4 py-2 text-text focus:outline-none focus:border-(--accent-solid)"
                  placeholder={t('wizard.misc.colorPlaceholder')}
                />
                <FormError error={errors.color} />
              </div>

              <div>
                <label className="block text-sm font-medium text-text-mid mb-2">
                  {t('edit.licensePlate')}
                </label>
                <input
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
                <label className="block text-sm font-medium text-text-mid mb-2">
                  {t('edit.purchaseDate')}
                </label>
                <input
                  type="date"
                  {...register('purchase_date')}
                  className="w-full bg-surface border border-border rounded-control px-4 py-2 text-text focus:outline-none focus:border-(--accent-solid)"
                />
                <FormError error={errors.purchase_date} />
              </div>

              <div>
                <label className="block text-sm font-medium text-text-mid mb-2">
                  {t('edit.purchasePrice')}
                </label>
                <NumberInput
                  {...registerDecimal(register, 'purchase_price')}
                  invalid={!!errors.purchase_price}
                  placeholder="15 000,00"
                />
                <FormError error={errors.purchase_price} />
              </div>
            </div>

            <h3 className="text-lg font-semibold text-text mt-6 mb-4">{t('wizard.misc.vinDecodedInfoOptional')}</h3>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-text-mid mb-2">{t('wizard.trim')}</label>
                <input
                  type="text"
                  {...register('trim')}
                  className="w-full bg-surface border border-border rounded-control px-4 py-2 text-text focus:outline-none focus:border-(--accent-solid)"
                  placeholder={t('wizard.misc.trimPlaceholder')}
                />
                <FormError error={errors.trim} />
              </div>

              <div>
                <label className="block text-sm font-medium text-text-mid mb-2">{t('edit.bodyClass')}</label>
                <input
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
                <label className="block text-sm font-medium text-text-mid mb-2">{t('edit.driveType')}</label>
                <input
                  type="text"
                  {...register('drive_type')}
                  className="w-full bg-surface border border-border rounded-control px-4 py-2 text-text focus:outline-none focus:border-(--accent-solid)"
                  placeholder={t('wizard.misc.driveTypePlaceholder')}
                />
                <FormError error={errors.drive_type} />
              </div>

              <div>
                <label className="block text-sm font-medium text-text-mid mb-2">{t('edit.doors')}</label>
                <NumberInput
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
                <label className="block text-sm font-medium text-text-mid mb-2">{t('edit.displacement')}</label>
                <input
                  type="text"
                  {...register('displacement_l')}
                  className="w-full bg-surface border border-border rounded-control px-4 py-2 text-text focus:outline-none focus:border-(--accent-solid)"
                  placeholder="2,0"
                />
                <FormError error={errors.displacement_l} />
              </div>

              <div>
                <label className="block text-sm font-medium text-text-mid mb-2">{t('edit.cylinders')}</label>
                <NumberInput
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
                <label className="block text-sm font-medium text-text-mid mb-2">{t('edit.transmissionType')}</label>
                <input
                  type="text"
                  {...register('transmission_type')}
                  className="w-full bg-surface border border-border rounded-control px-4 py-2 text-text focus:outline-none focus:border-(--accent-solid)"
                  placeholder={t('wizard.misc.transmissionTypePlaceholder')}
                />
                <FormError error={errors.transmission_type} />
              </div>

              <div>
                <label className="block text-sm font-medium text-text-mid mb-2">{t('edit.transmissionSpeeds')}</label>
                <input
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
              <label className="block text-sm font-medium text-text-mid mb-2">
                {t('wizard.misc.uploadPhotos')}
              </label>
              <input
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
                <div>
                  <p className="text-sm text-text-mute">{t('wizard.vin')}</p>
                  <p className="text-text font-mono">{vin}</p>
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
            </div>
          </div>
        )}
      </div>
    </Drawer>
  )
}
