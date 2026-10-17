import { useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { Settings2 } from 'lucide-react'
import { toast } from 'sonner'

import { useUpdateBrakeAxle } from '../../hooks/queries/useBrakes'
import type { BrakeAxle, BrakeAxleName, BrakeType } from '../../types/brake'
import { getActionErrorMessage } from '../../utils/httpErrorHandler'
import { Button, Chip, Drawer, Field, Input } from '../ui'

/** What a fresh axle of each type starts from: the server's defaults. */
const DEFAULTS: Record<BrakeType, { min: string; new: string }> = {
  disc: { min: '3', new: '10' },
  drum: { min: '1.5', new: '5' },
}

interface AxleForm {
  brake_type: BrakeType
  min: string
  new: string
  /** The rotor's minimum thickness (disc) or the drum's maximum diameter (drum). */
  limit: string
}

const seed = (axle: BrakeAxle): AxleForm => ({
  brake_type: axle.brake_type,
  min: String(Number(axle.min_thickness_mm)),
  new: String(Number(axle.new_thickness_mm)),
  limit:
    axle.brake_type === 'drum'
      ? axle.drum_max_mm != null
        ? String(Number(axle.drum_max_mm))
        : ''
      : axle.rotor_min_mm != null
        ? String(Number(axle.rotor_min_mm))
        : '',
})

const mm = (typed: string): number | null => {
  const trimmed = typed.trim()
  if (trimmed === '') return null
  const n = Number(trimmed)
  return Number.isFinite(n) ? n : null
}

interface AxleSetupDrawerProps {
  vin: string
  axles: BrakeAxle[]
  open: boolean
  onClose: () => void
}

/** Disc or drum per axle, and the limits the cards and the reminder judge against. */
export default function AxleSetupDrawer({ vin, axles, open, onClose }: AxleSetupDrawerProps): ReactElement {
  const { t } = useTranslation('vehicles')
  const update = useUpdateBrakeAxle(vin)
  const [forms, setForms] = useState<Record<BrakeAxleName, AxleForm>>(() => {
    const byAxle = Object.fromEntries(axles.map((axle) => [axle.axle, seed(axle)]))
    return {
      front: byAxle.front ?? { brake_type: 'disc', ...DEFAULTS.disc, limit: '' },
      rear: byAxle.rear ?? { brake_type: 'disc', ...DEFAULTS.disc, limit: '' },
    }
  })

  const set = (axle: BrakeAxleName, next: Partial<AxleForm>): void =>
    setForms((prev) => ({ ...prev, [axle]: { ...prev[axle], ...next } }))

  /* A type change starts that axle's limits from the new type's defaults: a
     3 mm pad minimum makes no sense for a 4.5 mm shoe. */
  const changeType = (axle: BrakeAxleName, type: BrakeType): void => {
    if (forms[axle].brake_type === type) return
    set(axle, { brake_type: type, ...DEFAULTS[type], limit: '' })
  }

  const handleSave = async (): Promise<void> => {
    for (const axle of ['front', 'rear'] as const) {
      const form = forms[axle]
      const min = mm(form.min)
      const fresh = mm(form.new)
      if (min === null || fresh === null) {
        toast.error(t('brakes.limitsRequired'))
        return
      }
      if (fresh <= min) {
        toast.error(t('brakes.newAboveMinimum'))
        return
      }
    }
    try {
      for (const axle of ['front', 'rear'] as const) {
        const form = forms[axle]
        const limit = mm(form.limit)
        await update.mutateAsync({
          axle,
          brake_type: form.brake_type,
          min_thickness_mm: mm(form.min) ?? 0,
          new_thickness_mm: mm(form.new) ?? 0,
          rotor_min_mm: form.brake_type === 'disc' ? limit : null,
          drum_max_mm: form.brake_type === 'drum' ? limit : null,
        })
      }
      toast.success(t('brakes.setupSaved'))
      onClose()
    } catch (err: unknown) {
      toast.error(getActionErrorMessage(err, t('brakes.setupAction')))
    }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('brakes.setupTitle')}
      icon={Settings2}
      width="sm"
      closeLabel={t('common:close')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common:cancel')}
          </Button>
          <Button variant="primary" disabled={update.isPending} onClick={() => void handleSave()}>
            {t('common:save')}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        {(['front', 'rear'] as const).map((axle) => {
          const form = forms[axle]
          const drum = form.brake_type === 'drum'
          return (
            <section key={axle} className="space-y-3">
              <h3 className="text-sm font-semibold">
                {axle === 'front' ? t('brakes.frontAxle') : t('brakes.rearAxle')}
              </h3>
              <div className="flex gap-2">
                <Chip selected={!drum} onClick={() => changeType(axle, 'disc')}>
                  {t('brakes.disc')}
                </Chip>
                <Chip selected={drum} onClick={() => changeType(axle, 'drum')}>
                  {t('brakes.drum')}
                </Chip>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Field
                  id={`brake-setup-${axle}-new`}
                  label={drum ? t('brakes.newShoe') : t('brakes.newPad')}
                  unit="mm"
                >
                  <Input
                    id={`brake-setup-${axle}-new`}
                    type="number"
                    step="0.1"
                    value={form.new}
                    onChange={(e) => set(axle, { new: e.target.value })}
                  />
                </Field>
                <Field
                  id={`brake-setup-${axle}-min`}
                  label={drum ? t('brakes.minShoe') : t('brakes.minPad')}
                  unit="mm"
                >
                  <Input
                    id={`brake-setup-${axle}-min`}
                    type="number"
                    step="0.1"
                    value={form.min}
                    onChange={(e) => set(axle, { min: e.target.value })}
                  />
                </Field>
              </div>
              <Field
                id={`brake-setup-${axle}-limit`}
                label={drum ? t('brakes.drumMax') : t('brakes.rotorMin')}
                unit="mm"
                hint={drum ? t('brakes.drumMaxHint') : t('brakes.rotorMinHint')}
              >
                <Input
                  id={`brake-setup-${axle}-limit`}
                  type="number"
                  step="0.01"
                  value={form.limit}
                  onChange={(e) => set(axle, { limit: e.target.value })}
                />
              </Field>
            </section>
          )
        })}
      </div>
    </Drawer>
  )
}
