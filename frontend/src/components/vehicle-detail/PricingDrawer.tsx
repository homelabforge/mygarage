import { useEffect, useRef, useState, type ChangeEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { DollarSign } from 'lucide-react'
import { toast } from 'sonner'
import FormModalWrapper from '../FormModalWrapper'
import { Button, Field, Input, NumberInput } from '../ui'
import vehicleService from '../../services/vehicleService'
import { withoutFieldError } from '../../utils/apiFormErrors'
import { moneyTextError } from '../../schemas/shared'
import { parseOptionalDecimal } from '../../utils/decimalInput'
import { str, dateStr, emptyToNull } from '../../utils/formUtils'
import type { Vehicle, VehicleUpdate } from '../../types/vehicle'

interface PricingDrawerProps {
  open: boolean
  onClose: () => void
  vehicle: Vehicle
  vin: string
  /** Receives the server's updated vehicle after a successful save. */
  onUpdated: (vehicle: Vehicle) => void
}

/** All eight pricing fields, held as strings while editing (empty = unset). */
type PricingForm = {
  purchase_date: string
  purchase_price: string
  sold_date: string
  sold_price: string
  msrp_base: string
  msrp_options: string
  destination_charge: string
  msrp_total: string
}

const DATE_FIELDS = ['purchase_date', 'sold_date'] as const satisfies readonly (keyof PricingForm)[]
const PRICE_FIELDS = [
  'purchase_price',
  'sold_price',
  'msrp_base',
  'msrp_options',
  'destination_charge',
  'msrp_total',
] as const satisfies readonly (keyof PricingForm)[]

type PriceField = (typeof PRICE_FIELDS)[number]

const EMPTY_FORM: PricingForm = {
  purchase_date: '',
  purchase_price: '',
  sold_date: '',
  sold_price: '',
  msrp_base: '',
  msrp_options: '',
  destination_charge: '',
  msrp_total: '',
}

function seedForm(v: Vehicle): PricingForm {
  return {
    purchase_date: dateStr(v.purchase_date),
    purchase_price: str(v.purchase_price),
    sold_date: dateStr(v.sold_date),
    sold_price: str(v.sold_price),
    msrp_base: str(v.msrp_base),
    msrp_options: str(v.msrp_options),
    destination_charge: str(v.destination_charge),
    msrp_total: str(v.msrp_total),
  }
}

/**
 * Edit-pricing sidecar: purchase, sale, and MSRP in one form. Opened from the
 * combined Pricing card's Edit button. Unlike the equipment drawer's per-change
 * auto-save, this is a multi-field form — edits are local until Save commits
 * them in one partial PUT, then the drawer closes.
 *
 * Only the fields the user changed go in the PUT, the same dirty-diff as
 * VehicleFieldsDrawer (an emptied field sends null). Posting all eight made a
 * legacy negative purchase price, which the API now refuses, fail every
 * unrelated MSRP or sale edit on that vehicle.
 */
export default function PricingDrawer({ open, onClose, vehicle, vin, onUpdated }: PricingDrawerProps) {
  const { t } = useTranslation('vehicles')
  const [form, setForm] = useState<PricingForm>(EMPTY_FORM)
  const [errors, setErrors] = useState<Partial<Record<PriceField, string>>>({})
  const [saving, setSaving] = useState(false)
  // What the form was seeded with, so save can tell what changed.
  const seededRef = useRef<PricingForm>(EMPTY_FORM)

  useEffect(() => {
    // Reseed from the vehicle each time the drawer opens. Save closes it, so
    // there is no open-state reseed race (unlike the auto-saving equipment drawer).
    if (open) {
      const seeded = seedForm(vehicle)
      seededRef.current = seeded
      setForm(seeded)
      setErrors({})
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const set =
    (key: keyof PricingForm) =>
    (e: ChangeEvent<HTMLInputElement>): void => {
      setForm((f) => ({ ...f, [key]: e.target.value }))
      setErrors((prev) => withoutFieldError(prev, key))
    }

  const changed = (key: keyof PricingForm): boolean => form[key] !== seededRef.current[key]

  const handleSave = async (): Promise<void> => {
    // Checked by hand, and only where the user typed: an untouched legacy
    // value isn't this save's business.
    const problems: Partial<Record<PriceField, string>> = {}
    for (const key of PRICE_FIELDS) {
      const problem = changed(key) ? moneyTextError(t, form[key]) : undefined
      if (problem) problems[key] = problem
    }
    setErrors(problems)
    if (Object.keys(problems).length > 0) return

    const payload: VehicleUpdate = {}
    for (const key of DATE_FIELDS) {
      if (changed(key)) payload[key] = emptyToNull(form[key])
    }
    for (const key of PRICE_FIELDS) {
      if (changed(key)) payload[key] = parseOptionalDecimal(form[key]) ?? null
    }
    if (Object.keys(payload).length === 0) {
      onClose()
      return
    }

    setSaving(true)
    try {
      const updated = await vehicleService.update(vin, payload)
      onUpdated(updated)
      onClose()
    } catch {
      toast.error(t('detail.pricing.saveError'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <FormModalWrapper
      isOpen={open}
      onClose={onClose}
      title={t('detail.pricing.editTitle')}
      icon={DollarSign}
      width="md"
      footer={
        <Button variant="primary" onClick={handleSave} loading={saving}>
          {t('common:save')}
        </Button>
      }
    >
      <div className="space-y-6">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field id="pricing_purchase_date" label={t('edit.purchaseDate')}>
            <Input id="pricing_purchase_date" type="date" value={form.purchase_date} onChange={set('purchase_date')} />
          </Field>
          <Field id="pricing_purchase_price" label={t('edit.purchasePrice')} error={errors.purchase_price}>
            <NumberInput id="pricing_purchase_price" value={form.purchase_price} onChange={set('purchase_price')} invalid={!!errors.purchase_price} />
          </Field>
          <Field id="pricing_sold_date" label={t('detail.misc.saleDate')}>
            <Input id="pricing_sold_date" type="date" value={form.sold_date} onChange={set('sold_date')} />
          </Field>
          <Field id="pricing_sold_price" label={t('detail.misc.salePrice')} error={errors.sold_price}>
            <NumberInput id="pricing_sold_price" value={form.sold_price} onChange={set('sold_price')} invalid={!!errors.sold_price} />
          </Field>
        </div>

        <section className="space-y-4 border-t border-border pt-5">
          <div>
            <p className="text-sm font-semibold text-text">{t('detail.msrpPricing')}</p>
            <p className="text-xs text-text-mute">{t('detail.pricing.msrpHint')}</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field id="pricing_msrp_base" label={t('detail.misc.basePrice')} error={errors.msrp_base}>
              <NumberInput id="pricing_msrp_base" value={form.msrp_base} onChange={set('msrp_base')} invalid={!!errors.msrp_base} />
            </Field>
            <Field id="pricing_msrp_options" label={t('detail.misc.options')} error={errors.msrp_options}>
              <NumberInput id="pricing_msrp_options" value={form.msrp_options} onChange={set('msrp_options')} invalid={!!errors.msrp_options} />
            </Field>
            <Field id="pricing_destination_charge" label={t('detail.misc.destination')} error={errors.destination_charge}>
              <NumberInput id="pricing_destination_charge" value={form.destination_charge} onChange={set('destination_charge')} invalid={!!errors.destination_charge} />
            </Field>
            <Field id="pricing_msrp_total" label={t('detail.misc.totalMsrp')} error={errors.msrp_total}>
              <NumberInput id="pricing_msrp_total" value={form.msrp_total} onChange={set('msrp_total')} invalid={!!errors.msrp_total} />
            </Field>
          </div>
        </section>
      </div>
    </FormModalWrapper>
  )
}
