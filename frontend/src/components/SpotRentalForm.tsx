import { useTranslation } from 'react-i18next'
import { useState, useEffect } from 'react'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Save } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import type { SpotRental, SpotRentalCreate, SpotRentalUpdate } from '../types/spotRental'
import type { AddressBookEntry } from '../types/addressBook'
import { spotRentalSchema, type SpotRentalFormData } from '../schemas/spotRental'
import { FormError } from './FormError'
import AddressBookAutocomplete from './AddressBookAutocomplete'
import api from '../services/api'
import { useCreateSpotRental, useUpdateSpotRental } from '../hooks/queries/useSpotRentals'
import { toast } from 'sonner'
import { formatDateForInput } from '../utils/dateUtils'

interface SpotRentalFormProps {
  vin: string
  rental?: SpotRental
  onClose: () => void
  onSuccess: () => void
}

export default function SpotRentalForm({ vin, rental, onClose, onSuccess }: SpotRentalFormProps) {
  const { t } = useTranslation('forms')
  const isEdit = !!rental
  const [error, setError] = useState<string | null>(null)
  const createMutation = useCreateSpotRental(vin)
  const updateMutation = useUpdateSpotRental(vin)
  const [selectedAddressEntry, setSelectedAddressEntry] = useState<AddressBookEntry | null>(null)
  const [showSaveToAddressBook, setShowSaveToAddressBook] = useState(false)
  const [pendingLocationData, setPendingLocationData] = useState<{name: string, address: string} | null>(null)
  const [rateType, setRateType] = useState<'nightly' | 'weekly' | 'monthly'>(() => {
    if (rental?.monthly_rate) return 'monthly'
    if (rental?.weekly_rate) return 'weekly'
    return 'nightly'
  })

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
      nightly_rate: rental?.nightly_rate != null ? Number(rental.nightly_rate) : undefined,
      weekly_rate: rental?.weekly_rate != null ? Number(rental.weekly_rate) : undefined,
      monthly_rate: rental?.monthly_rate != null ? Number(rental.monthly_rate) : undefined,
      electric: rental?.electric != null ? Number(rental.electric) : undefined,
      water: rental?.water != null ? Number(rental.water) : undefined,
      waste: rental?.waste != null ? Number(rental.waste) : undefined,
      total_cost: rental?.total_cost != null ? Number(rental.total_cost) : undefined,
      amenities: rental?.amenities || '',
      notes: rental?.notes || '',
    },
  })

  // Auto-calculate total cost from rate + utilities
  const nightlyRate = watch('nightly_rate')
  const weeklyRate = watch('weekly_rate')
  const monthlyRate = watch('monthly_rate')
  const electric = watch('electric')
  const water = watch('water')
  const waste = watch('waste')

  useEffect(() => {
    // Convert all values to numbers, handling both string and number inputs
    const toNumber = (val: number | string | undefined): number => {
      if (!val) return 0
      const num = typeof val === 'string' ? parseFloat(val) : val
      return isNaN(num) ? 0 : num
    }

    let baseRate = 0

    if (rateType === 'nightly' && nightlyRate) {
      baseRate = toNumber(nightlyRate)
    } else if (rateType === 'weekly' && weeklyRate) {
      baseRate = toNumber(weeklyRate)
    } else if (rateType === 'monthly' && monthlyRate) {
      baseRate = toNumber(monthlyRate)
    }

    const elec = toNumber(electric)
    const wat = toNumber(water)
    const wst = toNumber(waste)
    const calculatedTotal = baseRate + elec + wat + wst

    if (calculatedTotal > 0) {
      setValue('total_cost', parseFloat(calculatedTotal.toFixed(2)))
    }
  }, [rateType, nightlyRate, weeklyRate, monthlyRate, electric, water, waste, setValue])

  const handleAddressBookSelect = (entry: AddressBookEntry | null) => {
    setSelectedAddressEntry(entry)
    if (entry) {
      // Auto-fill address from selected entry
      const fullAddress = [
        entry.address,
        entry.city,
        entry.state,
        entry.zip_code
      ].filter(Boolean).join(', ')

      setValue('location_address', fullAddress)
    }
  }

  const handleSaveToAddressBook = async () => {
    if (!pendingLocationData) return

    try {
      await api.post('/address-book', {
        business_name: pendingLocationData.name,
        address: pendingLocationData.address,
        category: 'RV Park'
      })
      toast.success(t('spotRental.locationSaved'))
    } catch {
      toast.error(t('spotRental.failedToSaveLocation'))
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
        await updateMutation.mutateAsync({ id: rental.id, ...payload })
        onSuccess()
        onClose()
      } else {
        await createMutation.mutateAsync(payload as SpotRentalCreate)

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
      setError(err instanceof Error ? err.message : t('common:error'))
    }
  }

  return (
    <>
    <FormModalWrapper title={isEdit ? t('spotRental.editTitle') : t('spotRental.createTitle')} onClose={onClose}>
        <form onSubmit={handleSubmit(onSubmit as Parameters<typeof handleSubmit>[0])} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <label htmlFor="location_name" className="block text-sm font-medium text-garage-text mb-1">
                {t('spotRental.locationName')}
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
                placeholder="e.g., Happy Hills RV Park"
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.location_name ? 'border-red-500' : 'border-garage-border'
                }`}
              />
              <FormError error={errors.location_name} />
              <p className="text-xs text-garage-text-muted mt-1">
                {t('spotRental.addressBookHint')}
              </p>
            </div>
          </div>

          <div>
            <label htmlFor="location_address" className="block text-sm font-medium text-garage-text mb-1">
              {t('spotRental.address')}
            </label>
            <textarea
              id="location_address"
              rows={2}
              {...register('location_address')}
              placeholder={t('spotRental.addressPlaceholder')}
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
                {t('spotRental.checkInDate')} <span className="text-danger">*</span>
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
                {t('spotRental.checkOutDate')}
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
                {t('spotRental.leaveBlankHint')}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="rate_type" className="block text-sm font-medium text-garage-text mb-1">
                {t('spotRental.rateType')}
              </label>
              <select
                id="rate_type"
                value={rateType}
                onChange={(e) => {
                  const newType = e.target.value as 'nightly' | 'weekly' | 'monthly'
                  setRateType(newType)
                  // Clear other rate fields when switching
                  if (newType === 'nightly') {
                    setValue('weekly_rate', undefined)
                    setValue('monthly_rate', undefined)
                  } else if (newType === 'weekly') {
                    setValue('nightly_rate', undefined)
                    setValue('monthly_rate', undefined)
                  } else {
                    setValue('nightly_rate', undefined)
                    setValue('weekly_rate', undefined)
                  }
                }}
                className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text border-garage-border"
                disabled={isSubmitting}
              >
                <option value="nightly">{t('spotRental.nightly')}</option>
                <option value="weekly">{t('spotRental.weekly')}</option>
                <option value="monthly">{t('spotRental.monthly')}</option>
              </select>
            </div>

            <div>
              <label htmlFor="rate_amount" className="block text-sm font-medium text-garage-text mb-1">
                {rateType === 'nightly' ? 'Nightly' : rateType === 'weekly' ? 'Weekly' : 'Monthly'} Rate
              </label>
              <div className="relative">
                <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
                <input
                  type="number"
                  id="rate_amount"
                  step="0.01"
                  {...register(rateType === 'nightly' ? 'nightly_rate' : rateType === 'weekly' ? 'weekly_rate' : 'monthly_rate', { valueAsNumber: true })}
                  placeholder={rateType === 'nightly' ? '45.00' : rateType === 'weekly' ? '280.00' : '950.00'}
                  className={`w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    (rateType === 'nightly' && errors.nightly_rate) ||
                    (rateType === 'weekly' && errors.weekly_rate) ||
                    (rateType === 'monthly' && errors.monthly_rate)
                      ? 'border-red-500'
                      : 'border-garage-border'
                  }`}
                  disabled={isSubmitting}
                />
              </div>
              {rateType === 'nightly' && <FormError error={errors.nightly_rate} />}
              {rateType === 'weekly' && <FormError error={errors.weekly_rate} />}
              {rateType === 'monthly' && <FormError error={errors.monthly_rate} />}
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div>
              <label htmlFor="electric" className="block text-sm font-medium text-garage-text mb-1">
                {t('spotRental.electric')}
              </label>
              <div className="relative">
                <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
                <input
                  type="number"
                  id="electric"
                  step="0.01"
                  {...register('electric', { valueAsNumber: true })}
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
                {t('spotRental.water')}
              </label>
              <div className="relative">
                <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
                <input
                  type="number"
                  id="water"
                  step="0.01"
                  {...register('water', { valueAsNumber: true })}
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
                {t('spotRental.waste')}
              </label>
              <div className="relative">
                <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
                <input
                  type="number"
                  id="waste"
                  step="0.01"
                  {...register('waste', { valueAsNumber: true })}
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
              {t('common:totalCost')}
            </label>
            <div className="relative">
              <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
              <input
                type="number"
                id="total_cost"
                step="0.01"
                {...register('total_cost', { valueAsNumber: true })}
                placeholder="Auto-calculated"
                className="w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg/50 text-garage-text border-garage-border"
                readOnly
              />
            </div>
            <FormError error={errors.total_cost} />
            <p className="text-xs text-garage-text-muted mt-1">
              {t('spotRental.autoCalculatedHint')}
            </p>
          </div>

          <div>
            <label htmlFor="amenities" className="block text-sm font-medium text-garage-text mb-1">
              {t('spotRental.amenities')}
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
              {t('common:notes')}
            </label>
            <textarea
              id="notes"
              rows={3}
              {...register('notes')}
              placeholder={t('spotRental.notesPlaceholder')}
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
              <span>{isSubmitting ? t('common:saving') : isEdit ? t('common:update') : t('common:create')}</span>
            </button>

            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="btn btn-primary rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {t('common:cancel')}
            </button>
          </div>
        </form>
    </FormModalWrapper>

      {/* Save to Address Book Dialog */}
      {showSaveToAddressBook && pendingLocationData && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-[60]">
          <div className="bg-garage-surface rounded-lg shadow-xl max-w-md w-full p-6 border border-garage-border">
            <h3 className="text-lg font-semibold text-garage-text mb-3">
              {t('spotRental.saveToAddressBook')}
            </h3>
            <p className="text-sm text-garage-text-muted mb-4">
              {t('spotRental.saveToAddressBookPrompt', { name: pendingLocationData.name })}
            </p>
            <div className="flex gap-3">
              <button
                onClick={handleSaveToAddressBook}
                className="flex-1 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
              >
                {t('spotRental.yesSave')}
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
                {t('spotRental.noSkip')}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
