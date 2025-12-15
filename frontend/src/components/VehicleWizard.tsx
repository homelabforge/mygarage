/**
 * Vehicle Wizard - 4-step vehicle creation process
 * Step 1: VIN Entry & Decode
 * Step 2: Basic Info
 * Step 3: Photos (optional)
 * Step 4: Review & Create
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { X, ChevronLeft, ChevronRight, Check } from 'lucide-react'
import VINInput from './VINInput'
import { FormError } from './FormError'
import type { VINDecodeResponse } from '../types/vin'
import type { VehicleCreate, VehicleType } from '../types/vehicle'
import vehicleService from '../services/vehicleService'
import { vehicleEditSchema, VEHICLE_TYPES, type VehicleEditFormData } from '../schemas/vehicle'

interface VehicleWizardProps {
  onClose: () => void
  onSuccess?: (vin: string) => void
}

export default function VehicleWizard({ onClose, onSuccess }: VehicleWizardProps) {
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

  const steps = [
    { number: 1, title: 'VIN', description: 'Enter VIN' },
    { number: 2, title: 'Details', description: 'Basic info' },
    { number: 3, title: 'Photos', description: 'Add photos' },
    { number: 4, title: 'Review', description: 'Confirm' },
  ]

  // Handle VIN decode - populate form with setValue
  const handleVinDecode = (data: VINDecodeResponse) => {
    const currentNickname = getValues('nickname')
    const generatedNickname = `${data.year || ''} ${data.make || ''} ${data.model || ''}`.trim()

    // Set all decoded values using setValue
    setValue('year', data.year || undefined)
    setValue('make', data.make || undefined)
    setValue('model', data.model || undefined)
    setValue('nickname', currentNickname || generatedNickname)
    setValue('trim', data.trim || undefined)
    setValue('body_class', data.body_class || undefined)
    setValue('drive_type', data.drive_type || undefined)
    setValue('doors', data.doors || undefined)
    setValue('gvwr_class', data.gvwr || undefined)
    setValue('displacement_l', data.engine?.displacement_l || undefined)
    setValue('cylinders', data.engine?.cylinders || undefined)
    setValue('fuel_type', data.engine?.fuel_type || undefined)
    setValue('transmission_type', data.transmission?.type || undefined)
    setValue('transmission_speeds', data.transmission?.speeds || undefined)
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
        nickname: validatedData.nickname!,
        vehicle_type: validatedData.vehicle_type as VehicleType,
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
        setError(response?.data?.detail || 'Failed to create vehicle')
      } else {
        setError('Failed to create vehicle')
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
            <h2 className="text-2xl font-bold text-garage-text">Add New Vehicle</h2>
            <p className="text-garage-text-muted mt-1">
              Step {currentStep} of {steps.length}: {steps[currentStep - 1].description}
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
        <div className="flex items-center justify-between px-6 py-4 bg-garage-bg">
          {steps.map((step, index) => (
            <div key={step.number} className="flex items-center flex-1">
              <div className="flex items-center">
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center font-semibold ${
                    currentStep > step.number
                      ? 'bg-primary text-white'
                      : currentStep === step.number
                      ? 'bg-primary text-white'
                      : 'bg-garage-surface text-garage-text-muted border-2 border-garage-border'
                  }`}
                >
                  {currentStep > step.number ? <Check className="w-4 h-4" /> : step.number}
                </div>
                <div className="ml-3">
                  <div className="text-sm font-medium text-garage-text">{step.title}</div>
                </div>
              </div>
              {index < steps.length - 1 && (
                <div className="flex-1 h-0.5 bg-garage-border mx-4" />
              )}
            </div>
          ))}
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
                  Enter Vehicle Identification Number
                </h3>
                <VINInput
                  value={vin}
                  onChange={setVin}
                  onDecode={handleVinDecode}
                  autoValidate={true}
                />
              </div>
            </div>
          )}

          {/* Step 2: Basic Info */}
          {currentStep === 2 && (
            <div className="space-y-6">
              <h3 className="text-lg font-semibold text-garage-text mb-4">Vehicle Details</h3>

              <div>
                <label className="block text-sm font-medium text-garage-text mb-2">
                  Nickname <span className="text-danger">*</span>
                </label>
                <input
                  type="text"
                  {...register('nickname')}
                  className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                  placeholder="My Red Mirage"
                />
                <FormError error={errors.nickname} />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">
                    Vehicle Type <span className="text-danger">*</span>
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
                  <label className="block text-sm font-medium text-garage-text mb-2">Year</label>
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
                  <label className="block text-sm font-medium text-garage-text mb-2">Make</label>
                  <input
                    type="text"
                    {...register('make')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder="MITSUBISHI"
                  />
                  <FormError error={errors.make} />
                </div>

                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">Model</label>
                  <input
                    type="text"
                    {...register('model')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder="Mirage"
                  />
                  <FormError error={errors.model} />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">Color</label>
                  <input
                    type="text"
                    {...register('color')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder="Red"
                  />
                  <FormError error={errors.color} />
                </div>

                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">
                    License Plate
                  </label>
                  <input
                    type="text"
                    {...register('license_plate')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder="ABC-1234"
                  />
                  <FormError error={errors.license_plate} />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">
                    Purchase Date
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
                    Purchase Price
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

              <h3 className="text-lg font-semibold text-garage-text mt-6 mb-4">VIN Decoded Information (Optional)</h3>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">Trim</label>
                  <input
                    type="text"
                    {...register('trim')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder="EX, Limited, etc."
                  />
                  <FormError error={errors.trim} />
                </div>

                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">Body Class</label>
                  <input
                    type="text"
                    {...register('body_class')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder="Sedan, Coupe, etc."
                  />
                  <FormError error={errors.body_class} />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">Drive Type</label>
                  <input
                    type="text"
                    {...register('drive_type')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder="FWD, RWD, AWD, 4WD"
                  />
                  <FormError error={errors.drive_type} />
                </div>

                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">Doors</label>
                  <input
                    type="number"
                    {...register('doors', { valueAsNumber: true })}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder="4"
                  />
                  <FormError error={errors.doors} />
                </div>
              </div>

              <h3 className="text-lg font-semibold text-garage-text mt-6 mb-4">Engine & Transmission (Optional)</h3>

              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">Displacement (L)</label>
                  <input
                    type="text"
                    {...register('displacement_l')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder="2.0"
                  />
                  <FormError error={errors.displacement_l} />
                </div>

                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">Cylinders</label>
                  <input
                    type="number"
                    {...register('cylinders', { valueAsNumber: true })}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder="4"
                  />
                  <FormError error={errors.cylinders} />
                </div>

                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">Fuel Type</label>
                  <input
                    type="text"
                    {...register('fuel_type')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder="Gasoline, Diesel, etc."
                  />
                  <FormError error={errors.fuel_type} />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">Transmission Type</label>
                  <input
                    type="text"
                    {...register('transmission_type')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder="Automatic, Manual, CVT"
                  />
                  <FormError error={errors.transmission_type} />
                </div>

                <div>
                  <label className="block text-sm font-medium text-garage-text mb-2">Transmission Speeds</label>
                  <input
                    type="text"
                    {...register('transmission_speeds')}
                    className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary"
                    placeholder="6-Speed, 8-Speed, etc."
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
                Add Photos (Optional)
              </h3>

              <div>
                <label className="block text-sm font-medium text-garage-text mb-2">
                  Upload Photos
                </label>
                <input
                  type="file"
                  accept="image/*"
                  multiple
                  onChange={handlePhotoChange}
                  className="w-full bg-garage-bg border border-garage-border rounded-lg px-4 py-2 text-garage-text focus:outline-none focus:border-primary file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:bg-primary file:text-white file:cursor-pointer"
                />
                <p className="text-sm text-garage-text-muted mt-2">
                  You can upload photos now or add them later. Supported formats: JPG, PNG, WEBP
                </p>
              </div>

              {photoFiles.length > 0 && (
                <div>
                  <p className="text-sm font-medium text-garage-text mb-2">
                    Selected: {photoFiles.length} photo(s)
                  </p>
                  <ul className="space-y-1">
                    {photoFiles.map((file, index) => (
                      <li key={index} className="text-sm text-garage-text-muted">
                        {file.name} ({(file.size / 1024 / 1024).toFixed(2)} MB)
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
              <h3 className="text-lg font-semibold text-garage-text mb-4">Review & Confirm</h3>

              <div className="bg-garage-bg rounded-lg p-6 space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-sm text-garage-text-muted">VIN</p>
                    <p className="text-garage-text font-mono">{vin}</p>
                  </div>
                  <div>
                    <p className="text-sm text-garage-text-muted">Nickname</p>
                    <p className="text-garage-text">{formData.nickname}</p>
                  </div>
                  <div>
                    <p className="text-sm text-garage-text-muted">Type</p>
                    <p className="text-garage-text">{formData.vehicle_type}</p>
                  </div>
                  <div>
                    <p className="text-sm text-garage-text-muted">Year</p>
                    <p className="text-garage-text">{formData.year || 'Not specified'}</p>
                  </div>
                  <div>
                    <p className="text-sm text-garage-text-muted">Make</p>
                    <p className="text-garage-text">{formData.make || 'Not specified'}</p>
                  </div>
                  <div>
                    <p className="text-sm text-garage-text-muted">Model</p>
                    <p className="text-garage-text">{formData.model || 'Not specified'}</p>
                  </div>
                  <div>
                    <p className="text-sm text-garage-text-muted">Color</p>
                    <p className="text-garage-text">{formData.color || 'Not specified'}</p>
                  </div>
                  <div>
                    <p className="text-sm text-garage-text-muted">License Plate</p>
                    <p className="text-garage-text">{formData.license_plate || 'Not specified'}</p>
                  </div>
                  {formData.purchase_date && (
                    <div>
                      <p className="text-sm text-garage-text-muted">Purchase Date</p>
                      <p className="text-garage-text">{formData.purchase_date}</p>
                    </div>
                  )}
                  {formData.purchase_price && (
                    <div>
                      <p className="text-sm text-garage-text-muted">Purchase Price</p>
                      <p className="text-garage-text">${Number(formData.purchase_price).toFixed(2)}</p>
                    </div>
                  )}
                </div>

                {photoFiles.length > 0 && (
                  <div>
                    <p className="text-sm text-garage-text-muted mb-2">Photos to Upload</p>
                    <p className="text-garage-text">{photoFiles.length} photo(s)</p>
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
            <span>Previous</span>
          </button>

          <div className="flex space-x-3">
            <button
              onClick={onClose}
              className="btn btn-secondary rounded-lg transition-colors"
            >
              Cancel
            </button>

            {currentStep < 4 ? (
              <button
                onClick={handleNext}
                disabled={!canProceed()}
                className="flex items-center space-x-2 px-6 py-2 btn btn-primary rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <span>Next</span>
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
                    <span>Creating...</span>
                  </>
                ) : (
                  <>
                    <Check className="w-4 h-4" />
                    <span>Create Vehicle</span>
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
