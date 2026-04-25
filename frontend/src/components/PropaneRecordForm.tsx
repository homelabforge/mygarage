import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Save } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import type { FuelRecord, FuelRecordCreate, FuelRecordUpdate } from '../types/fuel'
import { propaneRecordSchema, type PropaneRecordFormData } from '../schemas/propane'
import { FormError } from './FormError'
import { useCreatePropaneRecord, useUpdatePropaneRecord } from '../hooks/queries/usePropaneRecords'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitConverter, UnitFormatter } from '../utils/units'
import { toCanonicalKg, toCanonicalLiters } from '../utils/decimalSafe'
import { formatDateForInput } from '../utils/dateUtils'
import CurrencyInputPrefix from './common/CurrencyInputPrefix'

// Propane density: 1 kg ≈ 1.968 L (1 gal ≈ 1.923 kg, 1 gal = 3.78541 L).
const KG_TO_LITERS = 1.968

// Tank sizes in kg (canonical). Display label is rendered with locale-aware
// units at render time.
const TANK_SIZES = [
  { kg: 9.07,   labelMetric: '9 kg (portable)',   labelImperial: '20 lb (portable)' },
  { kg: 14.97,  labelMetric: '15 kg (portable)',  labelImperial: '33 lb (portable)' },
  { kg: 45.36,  labelMetric: '45 kg (RV)',        labelImperial: '100 lb (RV)' },
  { kg: 190.51, labelMetric: '190 kg (RV)',       labelImperial: '420 lb (RV)' },
] as const

interface PropaneRecordFormProps {
  vin: string
  record?: FuelRecord
  onClose: () => void
  onSuccess: () => void
}

export default function PropaneRecordForm({
  vin,
  record,
  onClose,
  onSuccess
}: PropaneRecordFormProps) {
  const { t } = useTranslation('forms')
  const isEdit = !!record
  const [error, setError] = useState<string | null>(null)
  const createMutation = useCreatePropaneRecord(vin)
  const updateMutation = useUpdatePropaneRecord(vin)
  const { system } = useUnitPreference()

  // Extract vendor from notes if it was stored there
  const extractVendor = (notes?: string): string => {
    if (!notes) return ''
    const match = notes.match(/^Vendor: (.+?)(?:\n|$)/)
    return match ? match[1] : ''
  }

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    setValue,
    watch,
  } = useForm<PropaneRecordFormData>({
    resolver: zodResolver(propaneRecordSchema) as Resolver<PropaneRecordFormData>,
    defaultValues: {
      date: formatDateForInput(record?.date),
      propane_liters: (() => {
        if (record?.propane_liters == null) return undefined
        const liters = typeof record.propane_liters === 'string'
          ? parseFloat(record.propane_liters)
          : record.propane_liters
        if (isNaN(liters)) return undefined
        return system === 'imperial'
          ? UnitConverter.litersToGallons(liters) ?? undefined
          : liters
      })(),
      price_per_unit: (() => {
        if (!record?.price_per_unit) return undefined
        const price = typeof record.price_per_unit === 'string'
          ? parseFloat(record.price_per_unit)
          : record.price_per_unit
        return isNaN(price) ? undefined : price
      })(),
      cost: (() => {
        if (!record?.cost) return undefined
        const cost = typeof record.cost === 'string'
          ? parseFloat(record.cost)
          : record.cost
        return isNaN(cost) ? undefined : cost
      })(),
      vendor: extractVendor(record?.notes ?? undefined) || '',
      notes: record?.notes?.replace(/^Vendor: .+?\n/, '') || '',
      tank_size_kg: (() => {
        if (record?.tank_size_kg == null) return undefined
        const kg = typeof record.tank_size_kg === 'string'
          ? parseFloat(record.tank_size_kg)
          : record.tank_size_kg
        if (isNaN(kg)) return undefined
        return system === 'imperial' ? UnitConverter.kgToLbs(kg) ?? undefined : kg
      })(),
      tank_quantity: record?.tank_quantity ?? undefined,
    },
  })

  // Watch volume and price for auto-calculation
  const propaneVolume = watch('propane_liters')
  const pricePerUnit = watch('price_per_unit')
  const tankSizeDisplay = watch('tank_size_kg')
  const tankQuantity = watch('tank_quantity')

  const [isInitialMount, setIsInitialMount] = useState(true)

  useEffect(() => {
    if (isInitialMount) {
      setIsInitialMount(false)
      return
    }

    if (propaneVolume && pricePerUnit) {
      const volNum = typeof propaneVolume === 'number' ? propaneVolume : parseFloat(String(propaneVolume))
      const priceNum = typeof pricePerUnit === 'number' ? pricePerUnit : parseFloat(String(pricePerUnit))

      if (!isNaN(volNum) && !isNaN(priceNum)) {
        const total = volNum * priceNum
        setValue('cost', parseFloat(total.toFixed(2)))
      }
    }
  }, [propaneVolume, pricePerUnit, setValue, isInitialMount])

  // Auto-calculate propane volume from tank data.
  // tank_size_kg field actually holds the user's displayed tank weight (kg or lb).
  useEffect(() => {
    if (isInitialMount) return

    if (tankSizeDisplay && tankQuantity) {
      const tankNum = parseFloat(tankSizeDisplay.toString())
      // Convert to canonical kg, then to liters via density, then back to user's
      // displayed volume unit.
      const kg = system === 'imperial' ? (UnitConverter.lbsToKg(tankNum) ?? tankNum) : tankNum
      const totalLiters = kg * tankQuantity * KG_TO_LITERS
      const displayVolume = system === 'imperial'
        ? UnitConverter.litersToGallons(totalLiters)
        : totalLiters
      if (displayVolume !== null && displayVolume !== undefined) {
        setValue('propane_liters', parseFloat(displayVolume.toFixed(3)))
      }
    }
  }, [tankSizeDisplay, tankQuantity, system, setValue, isInitialMount])

  const onSubmit = async (data: PropaneRecordFormData) => {
    setError(null)

    try {
      // Construct notes with vendor prefix if vendor provided
      let finalNotes = data.notes || ''
      if (data.vendor && data.vendor.trim()) {
        finalNotes = `Vendor: ${data.vendor.trim()}\n${finalNotes}`.trim()
      }

      // We're using fuel_records table but ONLY propane_liters field
      const payload: FuelRecordCreate | FuelRecordUpdate = {
        vin,
        date: data.date,
        odometer_km: undefined,  // Never set for propane
        liters: undefined,  // Never set for propane
        propane_liters: toCanonicalLiters(data.propane_liters, system) ?? undefined,
        tank_size_kg: toCanonicalKg(data.tank_size_kg, system) ?? undefined,
        tank_quantity: data.tank_quantity,
        price_per_unit: data.price_per_unit,
        price_basis: 'per_tank',
        cost: data.cost,
        fuel_type: 'Propane',  // Always propane
        is_full_tank: false,  // Not relevant for propane
        missed_fillup: false,
        is_hauling: false,
        notes: finalNotes || undefined,
      }

      if (isEdit && record) {
        await updateMutation.mutateAsync({ id: record.id, ...payload })
      } else {
        await createMutation.mutateAsync(payload as FuelRecordCreate)
      }

      onSuccess()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common:error'))
    }
  }

  return (
    <FormModalWrapper title={isEdit ? t('propane.editTitle') : t('propane.createTitle')} onClose={onClose} maxWidth="max-w-lg">
        <form onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="date" className="block text-sm font-medium text-garage-text mb-1">
                {t('common:date')} <span className="text-danger">*</span>
              </label>
              <input
                type="date"
                id="date"
                {...register('date')}
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.date ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              />
              <FormError error={errors.date} />
            </div>
          </div>

          {/* Tank Information Section */}
          <div className="border-t border-garage-border pt-4 mt-4">
            <h3 className="text-sm font-medium text-garage-text mb-3">
              {t('propane.tankInfo')}
            </h3>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label htmlFor="tank_size_kg" className="block text-sm font-medium text-garage-text mb-1">
                  {t('propane.tankSize')} ({UnitFormatter.getWeightUnit(system)})
                </label>
                <select
                  id="tank_size_kg"
                  {...register('tank_size_kg', { valueAsNumber: true })}
                  className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text border-garage-border"
                  disabled={isSubmitting}
                >
                  <option value="">  {t('propane.selectTankSize')}  </option>
                  {TANK_SIZES.map(tank => {
                    const value = system === 'imperial'
                      ? Math.round(UnitConverter.kgToLbs(tank.kg) ?? 0)
                      : tank.kg
                    const label = system === 'imperial' ? tank.labelImperial : tank.labelMetric
                    return (
                      <option key={tank.kg} value={value}>
                        {label}
                      </option>
                    )
                  })}
                </select>
              </div>

              {/* Tank Quantity */}
              <div>
                <label htmlFor="tank_quantity" className="block text-sm font-medium text-garage-text mb-1">
                  {t('propane.numberOfTanks')}
                </label>
                <input
                  type="number"
                  id="tank_quantity"
                  {...register('tank_quantity', { valueAsNumber: true })}
                  min="1"
                  step="1"
                  className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.tank_quantity ? 'border-red-500' : 'border-garage-border'
                  }`}
                  disabled={isSubmitting}
                />
                <FormError error={errors.tank_quantity} />
              </div>
            </div>

            {/* Calculated volume hint */}
            {tankSizeDisplay && tankQuantity && (() => {
              const tankNum = parseFloat(tankSizeDisplay.toString())
              const kg = system === 'imperial' ? (UnitConverter.lbsToKg(tankNum) ?? tankNum) : tankNum
              const totalLiters = kg * tankQuantity * KG_TO_LITERS
              const display = system === 'imperial'
                ? UnitConverter.litersToGallons(totalLiters)
                : totalLiters
              return (
                <p className="text-xs text-garage-text-muted mt-2">
                  Auto-calculated: {display?.toFixed(2)} {UnitFormatter.getVolumeUnit(system)}
                </p>
              )
            })()}
          </div>

          {/* Propane volume field */}
          <div>
            <label htmlFor="propane_liters" className="block text-sm font-medium text-garage-text mb-1">
              Propane ({UnitFormatter.getVolumeUnit(system)})
            </label>
            <input
              type="number"
              id="propane_liters"
              {...register('propane_liters', { valueAsNumber: true })}
              min="0"
              step="0.001"
              placeholder={system === 'imperial' ? '10.500' : '39.750'}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.propane_liters ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <FormError error={errors.propane_liters} />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="price_per_unit" className="block text-sm font-medium text-garage-text mb-1">
                {t('fuel.pricePer')} {UnitFormatter.getVolumeUnit(system)}
              </label>
              <div className="relative">
                <CurrencyInputPrefix />
                <input
                  type="number"
                  id="price_per_unit"
                  {...register('price_per_unit', { valueAsNumber: true })}
                  min="0"
                  step="0.001"
                  placeholder={system === 'imperial' ? '2.899' : '0.766'}
                  className={`w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.price_per_unit ? 'border-red-500' : 'border-garage-border'
                  }`}
                  disabled={isSubmitting}
                />
              </div>
              <FormError error={errors.price_per_unit} />
            </div>

            <div>
              <label htmlFor="cost" className="block text-sm font-medium text-garage-text mb-1">
                Total Cost
              </label>
              <div className="relative">
                <CurrencyInputPrefix />
                <input
                  type="number"
                  id="cost"
                  {...register('cost', { valueAsNumber: true })}
                  min="0"
                  step="0.01"
                  placeholder="30.44"
                  className={`w-full pl-7 pr-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                    errors.cost ? 'border-red-500' : 'border-garage-border'
                  }`}
                  disabled={isSubmitting}
                />
              </div>
              <FormError error={errors.cost} />
              <p className="text-xs text-garage-text-muted mt-1">
                {t('fuel.autoCalculatedHint')}
              </p>
            </div>
          </div>

          <div>
            <label htmlFor="vendor" className="block text-sm font-medium text-garage-text mb-1">
              {t('propane.vendorLocation')}
            </label>
            <input
              type="text"
              id="vendor"
              {...register('vendor')}
              placeholder="e.g., AmeriGas, U-Haul Propane"
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.vendor ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            />
            <FormError error={errors.vendor} />
          </div>

          <div>
            <label htmlFor="notes" className="block text-sm font-medium text-garage-text mb-1">
              Notes
            </label>
            <textarea
              id="notes"
              rows={3}
              {...register('notes')}
              placeholder={t('common:additionalNotes')}
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
              className="btn btn-primary rounded-lg transition-colors"
              disabled={isSubmitting}
            >
              Cancel
            </button>
          </div>
        </form>
    </FormModalWrapper>
  )
}
