import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { ArrowLeft, Save } from 'lucide-react'
import api from '../services/api'
import type { Vehicle } from '../types/vehicle'
import { vehicleEditSchema, type VehicleEditFormData, VEHICLE_TYPES } from '../schemas/vehicle'
import { FormError } from '../components/FormError'

export default function VehicleEdit() {
  const { vin } = useParams<{ vin: string }>()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [vehicle, setVehicle] = useState<Vehicle | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    reset,
  } = useForm<VehicleEditFormData>({
    resolver: zodResolver(vehicleEditSchema) as Resolver<VehicleEditFormData>,
    defaultValues: {},
  })

  const fetchVehicle = useCallback(async () => {
    if (!vin) return
    try {
      const response = await api.get(`/vehicles/${vin}`)
      const data: Vehicle = response.data
      setVehicle(data)
      reset({
        nickname: data.nickname,
        license_plate: data.license_plate,
        vehicle_type: data.vehicle_type,
        color: data.color,
        year: data.year,
        make: data.make,
        model: data.model,
        purchase_date: data.purchase_date,
        purchase_price: data.purchase_price,
        sold_date: data.sold_date,
        sold_price: data.sold_price,
        // VIN decoded fields
        trim: data.trim,
        body_class: data.body_class,
        drive_type: data.drive_type,
        doors: data.doors,
        gvwr_class: data.gvwr_class,
        displacement_l: data.displacement_l,
        cylinders: data.cylinders,
        fuel_type: data.fuel_type,
        transmission_type: data.transmission_type,
        transmission_speeds: data.transmission_speeds,
      })
    } catch (error) {
      setError(error instanceof Error ? error.message : 'An error occurred')
    } finally {
      setLoading(false)
    }
  }, [vin, reset])

  useEffect(() => {
    fetchVehicle()
  }, [fetchVehicle])

  const onSubmit = async (data: VehicleEditFormData) => {
    if (!vin) return

    setError(null)

    try {
      await api.put(`/vehicles/${vin}`, data)

      // Navigate back to vehicle detail page with replace to force reload
      navigate(`/vehicles/${vin}`, { replace: true })
      // Force a page reload to ensure fresh data
      window.location.href = `/vehicles/${vin}`
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[400px]">
        <div className="text-garage-text-muted">Loading vehicle...</div>
      </div>
    )
  }

  if (error && !vehicle) {
    return (
      <div className="max-w-4xl mx-auto">
        <div className="bg-red-900/20 border border-red-500/50 rounded-lg p-4">
          <p className="text-red-400">{error}</p>
        </div>
      </div>
    )
  }

  if (!vehicle) {
    return (
      <div className="max-w-4xl mx-auto">
        <div className="bg-yellow-900/20 border border-yellow-500/50 rounded-lg p-4">
          <p className="text-yellow-400">Vehicle not found</p>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto">
      <div className="mb-6">
        <button
          onClick={() => navigate(`/vehicles/${vin}`)}
          className="flex items-center gap-2 text-garage-text-muted hover:text-garage-text mb-4 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          <span>Back to Vehicle</span>
        </button>

        <h1 className="text-3xl font-bold text-garage-text">
          Edit Vehicle
        </h1>
        <p className="text-garage-text-muted mt-1">
          {vehicle.year} {vehicle.make} {vehicle.model}
        </p>
        <p className="text-sm text-garage-text-muted mt-1">VIN: {vin}</p>
      </div>

      {error && (
        <div className="mb-6 bg-red-900/20 border border-red-500/50 rounded-lg p-4">
          <p className="text-red-400">{error}</p>
        </div>
      )}

      <form onSubmit={handleSubmit(onSubmit)} className="bg-garage-surface border border-garage-border rounded-lg p-6 space-y-6">
        {/* Basic Information Section */}
        <div>
          <h3 className="text-lg font-semibold text-garage-text mb-4">Basic Information</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label htmlFor="nickname" className="block text-sm font-medium text-garage-text mb-1">
                Nickname <span className="text-red-400">*</span>
              </label>
              <input
                type="text"
                id="nickname"
                {...register('nickname')}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-garage-text"
                placeholder="My Car"
              />
              <FormError error={errors.nickname} />
            </div>

            <div>
              <label htmlFor="license_plate" className="block text-sm font-medium text-garage-text mb-1">
                License Plate
              </label>
              <input
                type="text"
                id="license_plate"
                {...register('license_plate')}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-garage-text"
                placeholder="ABC1234"
              />
              <FormError error={errors.license_plate} />
            </div>

            <div>
              <label htmlFor="vehicle_type" className="block text-sm font-medium text-garage-text mb-1">
                Vehicle Type
              </label>
              <select
                id="vehicle_type"
                {...register('vehicle_type')}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-garage-text"
              >
                <option value="">Select type</option>
                {VEHICLE_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
              <FormError error={errors.vehicle_type} />
            </div>

            <div>
              <label htmlFor="color" className="block text-sm font-medium text-garage-text mb-1">
                Color
              </label>
              <input
                type="text"
                id="color"
                {...register('color')}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-garage-text"
                placeholder="Blue"
              />
              <FormError error={errors.color} />
            </div>
          </div>
        </div>

        {/* Vehicle Details Section */}
        <div>
          <h3 className="text-lg font-semibold text-garage-text mb-4">Vehicle Details</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label htmlFor="year" className="block text-sm font-medium text-garage-text mb-1">
                Year
              </label>
              <input
                type="number"
                id="year"
                {...register('year')}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-garage-text"
                placeholder="2020"
                min="1900"
                max="2100"
              />
              <FormError error={errors.year} />
            </div>

            <div>
              <label htmlFor="make" className="block text-sm font-medium text-garage-text mb-1">
                Make
              </label>
              <input
                type="text"
                id="make"
                {...register('make')}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-garage-text"
                placeholder="Toyota"
              />
              <FormError error={errors.make} />
            </div>

            <div>
              <label htmlFor="model" className="block text-sm font-medium text-garage-text mb-1">
                Model
              </label>
              <input
                type="text"
                id="model"
                {...register('model')}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-garage-text"
                placeholder="Camry"
              />
              <FormError error={errors.model} />
            </div>
          </div>
        </div>

        {/* VIN Decoded Information Section */}
        <div>
          <h3 className="text-lg font-semibold text-garage-text mb-4">VIN Decoded Information</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label htmlFor="trim" className="block text-sm font-medium text-garage-text mb-1">
                Trim
              </label>
              <input
                type="text"
                id="trim"
                {...register('trim')}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-garage-text"
                placeholder="EX, Limited, etc."
              />
              <FormError error={errors.trim} />
            </div>

            <div>
              <label htmlFor="body_class" className="block text-sm font-medium text-garage-text mb-1">
                Body Class
              </label>
              <input
                type="text"
                id="body_class"
                {...register('body_class')}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-garage-text"
                placeholder="Sedan, Coupe, etc."
              />
              <FormError error={errors.body_class} />
            </div>

            <div>
              <label htmlFor="drive_type" className="block text-sm font-medium text-garage-text mb-1">
                Drive Type
              </label>
              <input
                type="text"
                id="drive_type"
                {...register('drive_type')}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-garage-text"
                placeholder="FWD, RWD, AWD, 4WD"
              />
              <FormError error={errors.drive_type} />
            </div>

            <div>
              <label htmlFor="doors" className="block text-sm font-medium text-garage-text mb-1">
                Doors
              </label>
              <input
                type="number"
                id="doors"
                {...register('doors')}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-garage-text"
                placeholder="4"
              />
              <FormError error={errors.doors} />
            </div>

            <div>
              <label htmlFor="gvwr_class" className="block text-sm font-medium text-garage-text mb-1">
                GVWR Class
              </label>
              <input
                type="text"
                id="gvwr_class"
                {...register('gvwr_class')}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-garage-text"
                placeholder="Class 1, 2, etc."
              />
              <FormError error={errors.gvwr_class} />
            </div>
          </div>
        </div>

        {/* Engine & Transmission Section */}
        <div>
          <h3 className="text-lg font-semibold text-garage-text mb-4">Engine & Transmission</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label htmlFor="displacement_l" className="block text-sm font-medium text-garage-text mb-1">
                Displacement (L)
              </label>
              <input
                type="text"
                id="displacement_l"
                {...register('displacement_l')}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-garage-text"
                placeholder="2.0"
              />
              <FormError error={errors.displacement_l} />
            </div>

            <div>
              <label htmlFor="cylinders" className="block text-sm font-medium text-garage-text mb-1">
                Cylinders
              </label>
              <input
                type="number"
                id="cylinders"
                {...register('cylinders')}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-garage-text"
                placeholder="4"
              />
              <FormError error={errors.cylinders} />
            </div>

            <div>
              <label htmlFor="fuel_type" className="block text-sm font-medium text-garage-text mb-1">
                Fuel Type
              </label>
              <input
                type="text"
                id="fuel_type"
                {...register('fuel_type')}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-garage-text"
                placeholder="Gasoline, Diesel, etc."
              />
              <FormError error={errors.fuel_type} />
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
            <div>
              <label htmlFor="transmission_type" className="block text-sm font-medium text-garage-text mb-1">
                Transmission Type
              </label>
              <input
                type="text"
                id="transmission_type"
                {...register('transmission_type')}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-garage-text"
                placeholder="Automatic, Manual, CVT"
              />
              <FormError error={errors.transmission_type} />
            </div>

            <div>
              <label htmlFor="transmission_speeds" className="block text-sm font-medium text-garage-text mb-1">
                Transmission Speeds
              </label>
              <input
                type="text"
                id="transmission_speeds"
                {...register('transmission_speeds')}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-garage-text"
                placeholder="6-Speed, 8-Speed, etc."
              />
              <FormError error={errors.transmission_speeds} />
            </div>
          </div>
        </div>

        {/* Purchase Information Section */}
        <div>
          <h3 className="text-lg font-semibold text-garage-text mb-4">Purchase Information</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label htmlFor="purchase_date" className="block text-sm font-medium text-garage-text mb-1">
                Purchase Date
              </label>
              <input
                type="date"
                id="purchase_date"
                {...register('purchase_date')}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-garage-text"
              />
              <FormError error={errors.purchase_date} />
            </div>

            <div>
              <label htmlFor="purchase_price" className="block text-sm font-medium text-garage-text mb-1">
                Purchase Price
              </label>
              <div className="relative">
                <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
                <input
                  type="number"
                  id="purchase_price"
                  {...register('purchase_price')}
                  className="w-full pl-7 pr-3 py-2 bg-garage-bg border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-garage-text"
                  placeholder="25000.00"
                  step="0.01"
                  min="0"
                />
              </div>
              <FormError error={errors.purchase_price} />
            </div>
          </div>
        </div>

        {/* Sale Information Section */}
        <div>
          <h3 className="text-lg font-semibold text-garage-text mb-4">Sale Information (Optional)</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label htmlFor="sold_date" className="block text-sm font-medium text-garage-text mb-1">
                Sold Date
              </label>
              <input
                type="date"
                id="sold_date"
                {...register('sold_date')}
                className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-garage-text"
              />
              <FormError error={errors.sold_date} />
            </div>

            <div>
              <label htmlFor="sold_price" className="block text-sm font-medium text-garage-text mb-1">
                Sold Price
              </label>
              <div className="relative">
                <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
                <input
                  type="number"
                  id="sold_price"
                  {...register('sold_price')}
                  className="w-full pl-7 pr-3 py-2 bg-garage-bg border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-garage-text"
                  placeholder="20000.00"
                  step="0.01"
                  min="0"
                />
              </div>
              <FormError error={errors.sold_price} />
            </div>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex gap-3 pt-4 border-t border-garage-border">
          <button
            type="submit"
            disabled={isSubmitting}
            className="flex items-center gap-2 px-4 py-2 btn btn-primary rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <Save className="w-4 h-4" />
            <span>{isSubmitting ? 'Saving...' : 'Save Changes'}</span>
          </button>

          <button
            type="button"
            onClick={() => navigate(`/vehicles/${vin}`)}
            className="btn btn-primary rounded-lg"
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  )
}
