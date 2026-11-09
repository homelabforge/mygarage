import { useTranslation } from 'react-i18next'
import { useMemo, useState } from 'react'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Save } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import { Button, Drawer, Field, Input, Select, Textarea, registerDecimal } from './ui'
import CurrencyInput from './common/CurrencyInput'
import type { SpotRental, SpotRentalCreate, SpotRentalUpdate } from '../types/spotRental'
import type { AddressBookEntry } from '../types/addressBook'
import { makeSpotRentalSchema, type SpotRentalFormData } from '../schemas/spotRental'
import AddressBookAutocomplete from './AddressBookAutocomplete'
import api from '../services/api'
import { useCreateSpotRental, useUpdateSpotRental } from '../hooks/queries/useSpotRentals'
import { toast } from 'sonner'
import { formatDateForInput } from '../utils/dateUtils'
import { applyServerErrors } from '../utils/apiFormErrors'
import { actionErrorMessage } from '../utils/httpErrorHandler'
import { useOnUserEdit } from '../hooks/useOnUserEdit'

type RateType = 'nightly' | 'weekly' | 'monthly'

const RATE_FIELD = {
  nightly: 'nightly_rate',
  weekly: 'weekly_rate',
  monthly: 'monthly_rate',
} as const satisfies Record<RateType, keyof SpotRentalFormData>

// Inputs the suggested total is built from. A user edit to any of them
// recomputes it; opening a record never does.
const TOTAL_INPUTS = [
  'nightly_rate',
  'weekly_rate',
  'monthly_rate',
  'electric',
  'water',
  'waste',
  'check_in_date',
  'check_out_date',
] as const

const toAmount = (value: unknown): number | undefined => {
  if (value == null || value === '') return undefined
  const num = typeof value === 'number' ? value : parseFloat(String(value))
  return Number.isFinite(num) ? num : undefined
}

// Whole nights between two YYYY-MM-DD dates, or 0 when either is missing.
const nightsBetween = (checkIn: string | undefined, checkOut: string | undefined): number => {
  if (!checkIn || !checkOut) return 0
  const days = (Date.parse(`${checkOut}T00:00:00Z`) - Date.parse(`${checkIn}T00:00:00Z`)) / 86_400_000
  return Number.isFinite(days) ? Math.round(days) : 0
}

/**
 * The rate plus utilities, or undefined when none of them is entered. A
 * nightly stay with both dates is charged per night; an ongoing one, and
 * weekly or monthly rates, suggest one period because a part period is the
 * user's call.
 */
function suggestTotal(values: SpotRentalFormData, rateType: RateType): number | undefined {
  const rate = toAmount(values[RATE_FIELD[rateType]])
  const utilities = [values.electric, values.water, values.waste].map(toAmount)
  if (rate === undefined && utilities.every((u) => u === undefined)) return undefined
  const nights = rateType === 'nightly' ? nightsBetween(values.check_in_date, values.check_out_date) : 0
  const base = (rate ?? 0) * (nights > 0 ? nights : 1)
  const total = utilities.reduce<number>((sum, u) => sum + (u ?? 0), base)
  return parseFloat(total.toFixed(2))
}

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
  const [rateType, setRateType] = useState<RateType>(() => {
    if (rental?.monthly_rate) return 'monthly'
    if (rental?.weekly_rate) return 'weekly'
    return 'nightly'
  })

  // Zod bakes its messages in at construction, so the schema is rebuilt when
  // the language changes. Only the resolver depends on it — no fetch, no
  // reset() — so a rebuild can't discard what the user typed.
  const schema = useMemo(() => makeSpotRentalSchema(t), [t])

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    getValues,
    subscribe,
    formState: { errors, isSubmitting },
    setError: setFieldError,
  } = useForm<SpotRentalFormData>({
    resolver: zodResolver(schema) as Resolver<SpotRentalFormData>,
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

  // total_cost is read-only and derived, but only from what the user changes.
  // Recomputing on open replaced a ten-night total with one night's rate.
  useOnUserEdit(subscribe, TOTAL_INPUTS, (values) => {
    setValue('total_cost', suggestTotal(values, rateType))
  })

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

  // The save already succeeded before the prompt shows; "Skip" is the No path.
  // The nested Drawer routes its Esc / close button / backdrop click here.
  const skipSaveToAddressBook = () => {
    setShowSaveToAddressBook(false)
    setPendingLocationData(null)
    onSuccess()
    onClose()
  }

  const onSubmit = async (data: SpotRentalFormData) => {
    setError(null)

    try {
      // The update route keeps any key that isn't sent, so on edit an emptied
      // field must be null or it keeps its old value. Create stays as it was.
      const cleared = isEdit ? null : undefined
      const payload: SpotRentalCreate | SpotRentalUpdate = {
        location_name: data.location_name || cleared,
        location_address: data.location_address || cleared,
        check_in_date: data.check_in_date,
        check_out_date: data.check_out_date || cleared,
        nightly_rate: data.nightly_rate ?? cleared,
        weekly_rate: data.weekly_rate ?? cleared,
        monthly_rate: data.monthly_rate ?? cleared,
        electric: data.electric ?? cleared,
        water: data.water ?? cleared,
        waste: data.waste ?? cleared,
        total_cost: data.total_cost ?? cleared,
        amenities: data.amenities || cleared,
        notes: data.notes || cleared,
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
      // attached.length === 0 catches a non-422 failure (network drop, 500):
      // it carries no field problems at all, so `unhandled` alone would stay
      // empty and this banner would never show.
      const { parsed, attached, unhandled } = applyServerErrors<SpotRentalFormData>(setFieldError, err, [
        'location_name',
        'location_address',
        'check_in_date',
        'check_out_date',
        'nightly_rate',
        'weekly_rate',
        'monthly_rate',
        'electric',
        'water',
        'waste',
        'total_cost',
        'amenities',
        'notes',
      ])
      if (attached.length === 0 || unhandled.length > 0) {
        setError(actionErrorMessage(parsed, t('spotRental.saveAction')))
      }
    }
  }

  return (
    <>
    <FormModalWrapper
      title={isEdit ? t('spotRental.editTitle') : t('spotRental.createTitle')}
      onClose={onClose}
      width="md"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            {t('common:cancel')}
          </Button>
          <Button type="submit" form="spot-rental-form" variant="primary" icon={Save} loading={isSubmitting} disabled={isSubmitting}>
            {isSubmitting ? t('common:saving') : isEdit ? t('common:update') : t('common:create')}
          </Button>
        </>
      }
    >
        <form id="spot-rental-form" onSubmit={handleSubmit(onSubmit as Parameters<typeof handleSubmit>[0])} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <Field id="location_name" label={t('spotRental.locationName')} hint={t('spotRental.addressBookHint')} error={errors.location_name}>
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
              placeholder={t('spotRentalForm.locationNamePlaceholder')}
              className={`ui-focus-input ui-motion w-full rounded-control border bg-surface-2 px-3 py-2 text-sm text-text ${
                errors.location_name ? 'border-danger' : 'border-border'
              }`}
            />
          </Field>

          <Field id="location_address" label={t('spotRental.address')} error={errors.location_address}>
            <Textarea
              id="location_address"
              rows={2}
              {...register('location_address')}
              placeholder={t('spotRental.addressPlaceholder')}
              invalid={!!errors.location_address}
              disabled={isSubmitting}
            />
          </Field>

          <div className="grid grid-cols-2 gap-4">
            <Field id="check_in_date" label={t('spotRental.checkInDate')} required error={errors.check_in_date}>
              <Input id="check_in_date" type="date" {...register('check_in_date')} invalid={!!errors.check_in_date} disabled={isSubmitting} />
            </Field>

            <Field id="check_out_date" label={t('spotRental.checkOutDate')} hint={t('spotRental.leaveBlankHint')} error={errors.check_out_date}>
              <Input id="check_out_date" type="date" {...register('check_out_date')} invalid={!!errors.check_out_date} disabled={isSubmitting} />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Field id="rate_type" label={t('spotRental.rateType')}>
              <Select
                id="rate_type"
                value={rateType}
                onChange={(e) => {
                  const newType = e.target.value as RateType
                  setRateType(newType)
                  for (const type of ['nightly', 'weekly', 'monthly'] as const) {
                    if (type !== newType) setValue(RATE_FIELD[type], undefined)
                  }
                  // setValue isn't a user edit, so useOnUserEdit won't see the
                  // switch. Recompute here, and let an empty sum clear the total.
                  setValue('total_cost', suggestTotal(getValues(), newType))
                }}
                disabled={isSubmitting}
                options={[
                  { value: 'nightly', label: t('spotRental.nightly') },
                  { value: 'weekly', label: t('spotRental.weekly') },
                  { value: 'monthly', label: t('spotRental.monthly') },
                ]}
              />
            </Field>

            <Field
              id="rate_amount"
              label={t(
                rateType === 'nightly'
                  ? 'spotRentalForm.nightlyRate'
                  : rateType === 'weekly'
                    ? 'spotRentalForm.weeklyRate'
                    : 'spotRentalForm.monthlyRate'
              )}
              error={rateType === 'nightly' ? errors.nightly_rate : rateType === 'weekly' ? errors.weekly_rate : errors.monthly_rate}
            >
              <CurrencyInput
                id="rate_amount"
                {...registerDecimal(register, rateType === 'nightly' ? 'nightly_rate' : rateType === 'weekly' ? 'weekly_rate' : 'monthly_rate')}
                placeholder={rateType === 'nightly' ? '45.00' : rateType === 'weekly' ? '280.00' : '950.00'}
                invalid={
                  !!(
                    (rateType === 'nightly' && errors.nightly_rate) ||
                    (rateType === 'weekly' && errors.weekly_rate) ||
                    (rateType === 'monthly' && errors.monthly_rate)
                  )
                }
                disabled={isSubmitting}
              />
            </Field>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <Field id="electric" label={t('spotRental.electric')} error={errors.electric}>
              <CurrencyInput
                id="electric"
                {...registerDecimal(register, 'electric')}
                placeholder="50.00"
                invalid={!!errors.electric}
                disabled={isSubmitting}
              />
            </Field>

            <Field id="water" label={t('spotRental.water')} error={errors.water}>
              <CurrencyInput
                id="water"
                {...registerDecimal(register, 'water')}
                placeholder="30.00"
                invalid={!!errors.water}
                disabled={isSubmitting}
              />
            </Field>

            <Field id="waste" label={t('spotRental.waste')} error={errors.waste}>
              <CurrencyInput
                id="waste"
                {...registerDecimal(register, 'waste')}
                placeholder="20.00"
                invalid={!!errors.waste}
                disabled={isSubmitting}
              />
            </Field>
          </div>

          <Field id="total_cost" label={t('common:totalCost')} hint={t('spotRental.autoCalculatedHint')} error={errors.total_cost}>
            <CurrencyInput
              id="total_cost"
              {...registerDecimal(register, 'total_cost')}
              placeholder={t('spotRentalForm.autoCalculatedPlaceholder')}
              readOnly
            />
          </Field>

          <Field id="amenities" label={t('spotRental.amenities')} error={errors.amenities}>
            <Textarea
              id="amenities"
              rows={2}
              {...register('amenities')}
              placeholder={t('spotRentalForm.amenitiesPlaceholder')}
              invalid={!!errors.amenities}
              disabled={isSubmitting}
            />
          </Field>

          <Field id="notes" label={t('common:notes')} error={errors.notes}>
            <Textarea
              id="notes"
              rows={3}
              {...register('notes')}
              placeholder={t('spotRental.notesPlaceholder')}
              invalid={!!errors.notes}
              disabled={isSubmitting}
            />
          </Field>
        </form>
    </FormModalWrapper>

      {/* Save to Address Book — nested drawer above the parent (+10). Esc /
         close / backdrop all route to skipSaveToAddressBook (the "No" path). */}
      <Drawer
        open={showSaveToAddressBook && !!pendingLocationData}
        nested
        onClose={skipSaveToAddressBook}
        title={t('spotRental.saveToAddressBook')}
        width="2xs"
        closeLabel={t('common:close')}
        footer={
          <>
            <Button variant="secondary" onClick={skipSaveToAddressBook}>
              {t('spotRental.noSkip')}
            </Button>
            <Button variant="primary" onClick={handleSaveToAddressBook}>
              {t('spotRental.yesSave')}
            </Button>
          </>
        }
      >
        <p className="text-sm text-text-mute">
          {t('spotRental.saveToAddressBookPrompt', { name: pendingLocationData?.name ?? '' })}
        </p>
      </Drawer>
    </>
  )
}
