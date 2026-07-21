/**
 * Vehicle Wizard - 4-step vehicle creation process
 * Step 1: VIN Entry & Decode
 * Step 2: Basic Info
 * Step 3: Photos (optional)
 * Step 4: Review & Create
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { X, ChevronLeft, ChevronRight, Check } from 'lucide-react'
import VINInput from './VINInput'
import { FormError } from './FormError'
import { Stepper } from './ui'
import type { VINDecodeResponse } from '../types/vin'
import type { VehicleCreate } from '../types/vehicle'
import { FUEL_TYPE_VALUES, FUEL_TYPE_LABELS, type FuelType } from '../constants/fuel'
import vehicleService from '../services/vehicleService'
import { vehicleEditSchema, VEHICLE_TYPES, type VehicleEditFormData } from '../schemas/vehicle'
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

  // Form management with react-hook-form + Zod
  const {
    register,
    handleSubmit: handleFormSubmit,
    setValue,
    watch,
    getValues,
    formState: { errors },
  } = useForm<VehicleEditFormData>({
    resolver: zodResolver(vehicleEditSchema) as Resolver<VehicleEditFormData>,
    mode: 'onChange',
    defaultValues: {
      nickname: '',
      vehicle_type: 'Car',
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
      if (err && typeof err === 'object' && 'response' in err) {
        const response = (err as { response?: { data?: { detail?: string } } }).response
        setError(response?.data?.detail || t('wizard.misc.createFailed'))
      } else {
        setError(t('wizard.misc.createFailed'))
      }
      setLoading(false)
    }
  }

  const handleSubmit = () => {
    handleFormSubmit(onSubmit)()
  }

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center z-50 p-4">
      <div className="bg-garage-surface rounded-lg shadow-xl max-w-3xl w-full max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-garage-border">
          <div>
            <h2 className="text-2xl font-bold text-garage-text">{t('wizard.title')}</h2>
            <p className="text-garage-text-muted mt-1">
              {t('wizard.misc.stepProgress', {
                current: currentStep,
                total: steps.length,
                description: steps[currentStep - 1].description,
              })}
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-garage-text-muted hover:text-garage-text transition-colors"
          >
            <X className="w-6 h-6" />
          </button>
        </div>

        {/* Progress Steps */}
        <div className="px-6 py-4 bg-garage-bg">
          <Stepper
            steps={steps}
            current={currentStep}
            label={t('wizard.misc.progressLabel')}
            valueText={t('wizard.stepOf', { current: currentStep, total: steps.length })}
          />
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {error && (
            <div className="mb-4 p-4 bg-danger/10 border border-danger rounded-lg text-danger">
              {error}
            </div>
          )}

          {/* Step 1: VIN Entry */}
          {currentStep === 1 && (
            <div className="space-y-6">
              <div>
                <h3 className="text-lg font-semibold text-garage-text mb-4">
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
              <h3 className="text-lg font-semibold text-garage-text mb-4">{t('edit.vehicleDetails')}</h3>

              <div>
                <label className="block text-sm font-medium text-garage-text mb-2">
                  {t('wizard.nickname')} <span className="text-danger">*</span>
                </label>
                <input
                  type="text"
                  {...register('nickname')}
                  className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                  placeholder={t('wizard.misc.nicknamePlaceholder')}
                />
                <FormError error={errors.nickname} />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">
                    {t('edit.vehicleType')} <span className="text-danger">*</span>
                  </label>
                  <select
                    {...register('vehicle_type')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                  >
                    {VEHICLE_TYPES.map((type) => (
                      <option key={type} value={type}>
                        {type}
                      </option>
                    ))}
                  </select>
                  <FormError error={errors.vehicle_type} />
                </div>

                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">{t('wizard.year')}</label>
                  <input
                    type="number"
                    {...register('year', { valueAsNumber: true })}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder="2019"
                  />
                  <FormError error={errors.year} />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">{t('wizard.make')}</label>
                  <input
                    type="text"
                    {...register('make')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder="MITSUBISHI"
                  />
                  <FormError error={errors.make} />
                </div>

                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">{t('wizard.model')}</label>
                  <input
                    type="text"
                    {...register('model')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder={t('wizard.misc.modelPlaceholder')}
                  />
                  <FormError error={errors.model} />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">{t('wizard.color')}</label>
                  <input
                    type="text"
                    {...register('color')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder={t('wizard.misc.colorPlaceholder')}
                  />
                  <FormError error={errors.color} />
                </div>

                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">
                    {t('edit.licensePlate')}
                  </label>
                  <input
                    type="text"
                    {...register('license_plate')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder={t('wizard.misc.licensePlatePlaceholder')}
                  />
                  <FormError error={errors.license_plate} />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">
                    {t('edit.purchaseDate')}
                  </label>
                  <input
                    type="date"
                    {...register('purchase_date')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                  />
                  <FormError error={errors.purchase_date} />
                </div>

                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">
                    {t('edit.purchasePrice')}
                  </label>
                  <input
                    type="number"
                    step="0.01"
                    {...register('purchase_price', { valueAsNumber: true })}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder="15000.00"
                  />
                  <FormError error={errors.purchase_price} />
                </div>
              </div>

              <h3 className="text-lg font-semibold text-garage-text mt-6 mb-4">{t('wizard.misc.vinDecodedInfoOptional')}</h3>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">{t('wizard.trim')}</label>
                  <input
                    type="text"
                    {...register('trim')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder={t('wizard.misc.trimPlaceholder')}
                  />
                  <FormError error={errors.trim} />
                </div>

                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">{t('edit.bodyClass')}</label>
                  <input
                    type="text"
                    {...register('body_class')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder={t('wizard.misc.bodyClassPlaceholder')}
                  />
                  <FormError error={errors.body_class} />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">{t('edit.driveType')}</label>
                  <input
                    type="text"
                    {...register('drive_type')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder={t('wizard.misc.driveTypePlaceholder')}
                  />
                  <FormError error={errors.drive_type} />
                </div>

                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">{t('edit.doors')}</label>
                  <input
                    type="number"
                    {...register('doors', { valueAsNumber: true })}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder="4"
                  />
                  <FormError error={errors.doors} />
                </div>
              </div>

              <h3 className="text-lg font-semibold text-garage-text mt-6 mb-4">{t('wizard.misc.engineTransmissionOptional')}</h3>

              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">{t('edit.displacement')}</label>
                  <input
                    type="text"
                    {...register('displacement_l')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder="2.0"
                  />
                  <FormError error={errors.displacement_l} />
                </div>

                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">{t('edit.cylinders')}</label>
                  <input
                    type="number"
                    {...register('cylinders', { valueAsNumber: true })}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder="4"
                  />
                  <FormError error={errors.cylinders} />
                </div>

                <div>
                  <label
                    htmlFor="wizard-fuel-type"
                    className="block text-sm font-medium text-garage-text mb-2"
                  >
                    {t('wizard.fuelType')}
                  </label>
                  <select
                    id="wizard-fuel-type"
                    aria-label={t('wizard.fuelType')}
                    {...register('fuel_type')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                  >
                    <option value="">—</option>
                    {FUEL_TYPE_VALUES.map((value) => (
                      <option key={value} value={value}>
                        {FUEL_TYPE_LABELS[value]}
                      </option>
                    ))}
                  </select>
                  <FormError error={errors.fuel_type} />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">{t('edit.transmissionType')}</label>
                  <input
                    type="text"
                    {...register('transmission_type')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder={t('wizard.misc.transmissionTypePlaceholder')}
                  />
                  <FormError error={errors.transmission_type} />
                </div>

                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">{t('edit.transmissionSpeeds')}</label>
                  <input
                    type="text"
                    {...register('transmission_speeds')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
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
              <h3 className="text-lg font-semibold text-garage-text mb-4">
                {t('wizard.misc.addPhotosOptional')}
              </h3>

              <div>
                <label className="block text-sm font-medium text-garage-text mb-2">
                  {t('wizard.misc.uploadPhotos')}
                </label>
                <input
                  type="file"
                  accept="image/*"
                  multiple
                  onChange={handlePhotoChange}
                  className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:bg-primary file:text-white file:cursor-pointer"
                />
                <p className="text-sm text-garage-text-muted mt-2">
                  {t('wizard.misc.photoUploadHelp')}
                </p>
              </div>

              {photoFiles.length > 0 && (
                <div>
                  <p className="text-sm font-medium text-garage-text mb-2">
                    {t('wizard.misc.selectedPhotos', { count: photoFiles.length })}
                  </p>
                  <ul className="space-y-1">
                    {photoFiles.map((file, index) => (
                      <li key={index} className="text-sm text-garage-text-muted">
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
              <h3 className="text-lg font-semibold text-garage-text mb-4">{t('wizard.misc.reviewConfirm')}</h3>

              <div className="bg-garage-bg rounded-lg p-6 space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-sm text-garage-text-muted">{t('wizard.vin')}</p>
                    <p className="text-garage-text font-mono">{vin}</p>
                  </div>
                  <div>
                    <p className="text-sm text-garage-text-muted">{t('wizard.nickname')}</p>
                    <p className="text-garage-text">{formData.nickname}</p>
                  </div>
                  <div>
                    <p className="text-sm text-garage-text-muted">{t('detail.misc.type')}</p>
                    <p className="text-garage-text">{formData.vehicle_type}</p>
                  </div>
                  <div>
                    <p className="text-sm text-garage-text-muted">{t('wizard.year')}</p>
                    <p className="text-garage-text">{formData.year || t('detail.notSpecified')}</p>
                  </div>
                  <div>
                    <p className="text-sm text-garage-text-muted">{t('wizard.make')}</p>
                    <p className="text-garage-text">{formData.make || t('detail.notSpecified')}</p>
                  </div>
                  <div>
                    <p className="text-sm text-garage-text-muted">{t('wizard.model')}</p>
                    <p className="text-garage-text">{formData.model || t('detail.notSpecified')}</p>
                  </div>
                  <div>
                    <p className="text-sm text-garage-text-muted">{t('wizard.color')}</p>
                    <p className="text-garage-text">{formData.color || t('detail.notSpecified')}</p>
                  </div>
                  <div>
                    <p className="text-sm text-garage-text-muted">{t('edit.licensePlate')}</p>
                    <p className="text-garage-text">{formData.license_plate || t('detail.notSpecified')}</p>
                  </div>
                  {formData.purchase_date && (
                    <div>
                      <p className="text-sm text-garage-text-muted">{t('edit.purchaseDate')}</p>
                      <p className="text-garage-text">{formData.purchase_date}</p>
                    </div>
                  )}
                  {formData.purchase_price && (
                    <div>
                      <p className="text-sm text-garage-text-muted">{t('edit.purchasePrice')}</p>
                      <p className="text-garage-text">
                        {formatCurrency(formData.purchase_price, {
                          fallback: t('detail.notSpecified'),
                        })}
                      </p>
                    </div>
                  )}
                </div>

                {photoFiles.length > 0 && (
                  <div>
                    <p className="text-sm text-garage-text-muted mb-2">{t('wizard.misc.photosToUpload')}</p>
                    <p className="text-garage-text">{t('wizard.misc.photoCount', { count: photoFiles.length })}</p>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between p-6 border-t border-garage-border bg-garage-bg">
          <button
            onClick={handlePrevious}
            disabled={currentStep === 1}
            className="flex items-center space-x-2 px-4 py-2 text-garage-text-muted hover:text-garage-text disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <ChevronLeft className="w-4 h-4" />
            <span>{t('wizard.misc.previous')}</span>
          </button>

          <div className="flex space-x-3">
            <button
              onClick={onClose}
              className="btn btn-secondary rounded-lg transition-colors"
            >
              {t('wizard.misc.cancel')}
            </button>

            {currentStep < 4 ? (
              <button
                onClick={handleNext}
                disabled={!canProceed()}
                className="flex items-center space-x-2 px-6 py-2 btn btn-primary rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <span>{t('wizard.next')}</span>
                <ChevronRight className="w-4 h-4" />
              </button>
            ) : (
              <button
                onClick={handleSubmit}
                disabled={loading}
                className="flex items-center space-x-2 px-6 py-2 bg-success text-white rounded-lg hover:bg-success/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {loading ? (
                  <>
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    <span>{t('wizard.misc.creating')}</span>
                  </>
                ) : (
                  <>
                    <Check className="w-4 h-4" />
                    <span>{t('wizard.misc.createVehicle')}</span>
                  </>
                )}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
