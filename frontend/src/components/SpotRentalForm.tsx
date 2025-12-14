import { useState } from 'react'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { X, Save } from 'lucide-react'
import type { SpotRental, SpotRentalCreate, SpotRentalUpdate } from '../types/spotRental'
import type { AddressBookEntry } from '../types/addressBook'
import { spotRentalSchema, type SpotRentalFormData } from '../schemas/spotRental'
import { FormError } from './FormError'
import AddressBookAutocomplete from './AddressBookAutocomplete'
import api from '../services/api'
import { toast } from 'sonner'

interface SpotRentalFormProps {
  vin: string
  rental?: SpotRental
  onClose: () => void
  onSuccess: () => void
}

export default function SpotRentalForm({ vin, rental, onClose, onSuccess }: SpotRentalFormProps) {
  const isEdit = !!rental
  const [error, setError] = useState<string | null>(null)
  const [selectedAddressEntry, setSelectedAddressEntry] = useState<AddressBookEntry | null>(null)
  const [showSaveToAddressBook, setShowSaveToAddressBook] = useState(false)
  const [pendingLocationData, setPendingLocationData] = useState<{name: string, address: string} | null>(null)

  // Helper to format date for input[type="date"]
  const formatDateForInput = (dateString?: string): string => {
    if (!dateString) {
      const now = new Date()
      const year = now.getFullYear()
      const month = String(now.getMonth() + 1).padStart(2, '0')
      const day = String(now.getDate()).padStart(2, '0')
      return `${year}-${month}-${day}`
    }
    if (/^\d{4}-\d{2}-\d{2}$/.test(dateString)) {
      return dateString
    }
    const date = new Date(dateString + 'T00:00:00')
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
  }

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<SpotRentalFormData>({
    resolver: zodResolver(spotRentalSchema) as Resolver<SpotRentalFormData>,
    defaultValues: {
      location_name: rental?.location_name || '',
      location_address: rental?.location_address || '',
      check_in_date: formatDateForInput(rental?.check_in_date),
      check_out_date: rental?.check_out_date ? formatDateForInput(rental.check_out_date) : '',
      nightly_rate: rental?.nightly_rate ?? undefined,
      weekly_rate: rental?.weekly_rate ?? undefined,
      monthly_rate: rental?.monthly_rate ?? undefined,
      electric: rental?.electric ?? undefined,
      water: rental?.water ?? undefined,
      waste: rental?.waste ?? undefined,
      total_cost: rental?.total_cost ?? undefined,
      amenities: rental?.amenities || '',
      notes: rental?.notes || '',
    },
  })

  const handleAddressBookSelect = (entry: AddressBookEntry | null) => {
    setSelectedAddressEntry(entry)
    if (entry) {
      // Auto-fill address from selected entry
      const fullAddress = [
        entry.address_line1,
        entry.address_line2,
        entry.city,
        entry.state,
        entry.postal_code,
        entry.country
      ].filter(Boolean).join(', ')

      setValue('location_address', fullAddress)
    }
  }

  const handleSaveToAddressBook = async () => {
    if (!pendingLocationData) return

    try {
      await api.post('/address-book', {
        business_name: pendingLocationData.name,
        address_line1: pendingLocationData.address,
        category: 'RV Park'
      })
      toast.success('Location saved to address book')
    } catch (err) {
      toast.error('Failed to save to address book')
    } finally {
      setShowSaveToAddressBook(false)
      setPendingLocationData(null)
      onSuccess()
      onClose()
    }
  }

  const onSubmit = async (data: SpotRentalFormData) => {
    setError(null)

    try {
      // Zod has already parsed and validated all numeric fields - no parseFloat needed!
      const payload: SpotRentalCreate | SpotRentalUpdate = {
        location_name: data.location_name || undefined,
        location_address: data.location_address || undefined,
        check_in_date: data.check_in_date,
        check_out_date: data.check_out_date || undefined,
        nightly_rate: data.nightly_rate,
        weekly_rate: data.weekly_rate,
        monthly_rate: data.monthly_rate,
        electric: data.electric,
        water: data.water,
        waste: data.waste,
        total_cost: data.total_cost,
        amenities: data.amenities || undefined,
        notes: data.notes || undefined,
      }

      if (isEdit) {
        await api.put(`/vehicles/${vin}/spot-rentals/${rental.id}`, payload)
        onSuccess()
        onClose()
      } else {
        await api.post(`/vehicles/${vin}/spot-rentals`, payload)

        // Check if this is a new location (not from address book)
        if (data.location_name && !selectedAddressEntry) {
          setPendingLocationData({
            name: data.location_name,
            address: data.location_address || ''
          })
          setShowSaveToAddressBook(true)
        } else {
          onSuccess()
          onClose()
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    }
  }

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center p-4 z-50">
      <div className="bg-garage-surface rounded-lg shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto border border-garage-border">
        <div className="sticky top-0 bg-garage-surface border-b border-garage-border px-6 py-4 flex justify-between items-center rounded-t-lg">
          <h2 className="text-xl font-semibold text-garage-text">
            {isEdit ? 'Edit Spot Rental' : 'Add Spot Rental'}
          </h2>
          <button
            onClick={onClose}
            className="text-garage-text-muted hover:text-garage-text"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <label htmlFor="location_name" className="block text-sm font-medium text-garage-text mb-1">
                Location/Facility Name
              </label>
              <AddressBookAutocomplete
                id="location_name"
                value={watch('location_name') || ''}
                onChange={(value) => {
                  setValue('location_name', value)
                  if (!value) {
                    setSelectedAddressEntry(null)
                  }
                }}
                onSelectEntry={handleAddressBookSelect}
                categoryFilter="RV Park"
                placeholder="e.g., Happy Hills RV Park"
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.location_name ? 'border-red-500' : 'border-garage-border'
                }`}
              />
              <FormError error={errors.location_name} />
              <p className="text-xs text-garage-text-muted mt-1">
                Start typing to search from your address book
              </p>
            </div>
          </div>

          <div>
            <label htmlFor="location_address" className="block text-sm font-medium text-garage-text mb-1">
              Address
            </label>
            <textarea
              id="location_address"
              rows={2}
              {...register('location_address')}
              placeholder="Full address of the rental location..."
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.location_address ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <FormError error={errors.location_address} />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="check_in_date" className="block text-sm font-medium text-garage-text mb-1">
                Check-In Date <span className="text-danger">*</span>
              </label>
              <input
                type="date"
                id="check_in_date"
                {...register('check_in_date')}
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.check_in_date ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
              <FormError error={errors.check_in_date} />
            </div>

            <div>
              <label htmlFor="check_out_date" className="block text-sm font-medium text-garage-text mb-1">
                Check-Out Date
              </label>
              <input
                type="date"
                id="check_out_date"
                {...register('check_out_date')}
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.check_out_date ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
              <FormError error={errors.check_out_date} />
              <p className="text-xs text-garage-text-muted mt-1">
                Leave blank if still renting
              </p>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div>
              <label htmlFor="nightly_rate" className="block text-sm font-medium text-garage-text mb-1">
                Nightly Rate
              </label>
              <div className="relative">
                <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
                <input
                  type="number"
                  id="nightly_rate"
                  step="0.01"
                  {...register('nightly_rate')}
                  placeholder="45.00"
                  className={`w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.nightly_rate ? 'border-red-500' : 'border-garage-border'
                  }`}
                  disabled={isSubmitting}
                />
              </div>
              <FormError error={errors.nightly_rate} />
            </div>

            <div>
              <label htmlFor="weekly_rate" className="block text-sm font-medium text-garage-text mb-1">
                Weekly Rate
              </label>
              <div className="relative">
                <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
                <input
                  type="number"
                  id="weekly_rate"
                  step="0.01"
                  {...register('weekly_rate')}
                  placeholder="280.00"
                  className={`w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.weekly_rate ? 'border-red-500' : 'border-garage-border'
                  }`}
                  disabled={isSubmitting}
                />
              </div>
              <FormError error={errors.weekly_rate} />
            </div>

            <div>
              <label htmlFor="monthly_rate" className="block text-sm font-medium text-garage-text mb-1">
                Monthly Rate
              </label>
              <div className="relative">
                <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
                <input
                  type="number"
                  id="monthly_rate"
                  step="0.01"
                  {...register('monthly_rate')}
                  placeholder="950.00"
                  className={`w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.monthly_rate ? 'border-red-500' : 'border-garage-border'
                  }`}
                  disabled={isSubmitting}
                />
              </div>
              <FormError error={errors.monthly_rate} />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div>
              <label htmlFor="electric" className="block text-sm font-medium text-garage-text mb-1">
                Electric
              </label>
              <div className="relative">
                <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
                <input
                  type="number"
                  id="electric"
                  step="0.01"
                  {...register('electric')}
                  placeholder="50.00"
                  className={`w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.electric ? 'border-red-500' : 'border-garage-border'
                  }`}
                  disabled={isSubmitting}
                />
              </div>
              <FormError error={errors.electric} />
            </div>

            <div>
              <label htmlFor="water" className="block text-sm font-medium text-garage-text mb-1">
                Water
              </label>
              <div className="relative">
                <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
                <input
                  type="number"
                  id="water"
                  step="0.01"
                  {...register('water')}
                  placeholder="30.00"
                  className={`w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.water ? 'border-red-500' : 'border-garage-border'
                  }`}
                  disabled={isSubmitting}
                />
              </div>
              <FormError error={errors.water} />
            </div>

            <div>
              <label htmlFor="waste" className="block text-sm font-medium text-garage-text mb-1">
                Waste
              </label>
              <div className="relative">
                <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
                <input
                  type="number"
                  id="waste"
                  step="0.01"
                  {...register('waste')}
                  placeholder="20.00"
                  className={`w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.waste ? 'border-red-500' : 'border-garage-border'
                  }`}
                  disabled={isSubmitting}
                />
              </div>
              <FormError error={errors.waste} />
            </div>
          </div>

          <div>
            <label htmlFor="total_cost" className="block text-sm font-medium text-garage-text mb-1">
              Total Cost
            </label>
            <div className="relative">
              <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
              <input
                type="number"
                id="total_cost"
                step="0.01"
                {...register('total_cost')}
                placeholder="2850.00"
                className={`w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.total_cost ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
            </div>
            <FormError error={errors.total_cost} />
            <p className="text-xs text-garage-text-muted mt-1">
              Total amount paid for this rental period
            </p>
          </div>

          <div>
            <label htmlFor="amenities" className="block text-sm font-medium text-garage-text mb-1">
              Amenities
            </label>
            <textarea
              id="amenities"
              rows={2}
              {...register('amenities')}
              placeholder="e.g., Full hookup, WiFi, Pool, Laundry, Pet friendly..."
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.amenities ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <FormError error={errors.amenities} />
          </div>

          <div>
            <label htmlFor="notes" className="block text-sm font-medium text-garage-text mb-1">
              Notes
            </label>
            <textarea
              id="notes"
              rows={3}
              {...register('notes')}
              placeholder="Additional notes about this rental..."
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.notes ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <FormError error={errors.notes} />
          </div>

          <div className="flex gap-3 pt-4">
            <button
              type="submit"
              disabled={isSubmitting}
              className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Save className="w-4 h-4" />
              <span>{isSubmitting ? 'Saving...' : isEdit ? 'Update' : 'Create'}</span>
            </button>

            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="btn btn-primary rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>

      {/* Save to Address Book Dialog */}
      {showSaveToAddressBook && pendingLocationData && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-[60]">
          <div className="bg-garage-surface rounded-lg shadow-xl max-w-md w-full p-6 border border-garage-border">
            <h3 className="text-lg font-semibold text-garage-text mb-3">
              Save to Address Book?
            </h3>
            <p className="text-sm text-garage-text-muted mb-4">
              Would you like to save "{pendingLocationData.name}" to your address book for quicker access in the future?
            </p>
            <div className="flex gap-3">
              <button
                onClick={handleSaveToAddressBook}
                className="flex-1 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
              >
                Yes, Save
              </button>
              <button
                onClick={() => {
                  setShowSaveToAddressBook(false)
                  setPendingLocationData(null)
                  onSuccess()
                  onClose()
                }}
                className="flex-1 px-4 py-2 bg-garage-bg border border-garage-border text-garage-text rounded-lg hover:bg-garage-bg/80 transition-colors"
              >
                No, Skip
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
