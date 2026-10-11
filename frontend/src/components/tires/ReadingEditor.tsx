import { useState } from 'react'
import { Gauge } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { useUpdateTireReading } from '../../hooks/queries/useTires'
import { useUnitFormat } from '../../hooks/useUnitFormat'
import type { Tire, TirePosition, TireReading } from '../../types/tire'
import { formatDateForDisplay } from '../../utils/dateUtils'
import { getActionErrorMessage } from '../../utils/httpErrorHandler'
import { normaliseTreadEntry } from '../../utils/treadEntry'
import { canonicalFromUnitField, seedUnitField, type UnitFieldOrigin } from '../../utils/unitFormat'
import { Button, Drawer, Field, Input } from '../ui'
import MountEventFields, { type OdometerFieldValue } from './MountEventFields'
import TreadField from './TreadField'

interface ReadingEditorProps {
  vin: string
  tire: Tire
  reading: TireReading
  open: boolean
  onClose: () => void
  labelFor: (position: TirePosition) => string
}

interface EditorState {
  recorded_at: string
  odometer_km: OdometerFieldValue
  tread_depth_mm: string
  pressure_kpa: string
  notes: string
  origins: { tread_depth_mm: UnitFieldOrigin; pressure_kpa: UnitFieldOrigin }
}

/**
 * Correct one reading. A nested drawer, because it opens from the history
 * drawer and a modal opened from a drawer is inert in this app.
 *
 * Before this the only repair for a mistyped reading was to delete it and log
 * it again, which also lost the chance to add an odometer to a reading that
 * was logged without one. Every field is seeded from the reading and every
 * field is sent, so clearing one is a deliberate act; the unit origins make an
 * untouched field send back exactly the value it was seeded from, rather than
 * a rounded round trip. Render with `key={reading.id}` so the state seeds once
 * per reading rather than through an effect.
 */
export default function ReadingEditor({
  vin,
  tire,
  reading,
  open,
  onClose,
  labelFor,
}: ReadingEditorProps) {
  const { t } = useTranslation('vehicles')
  const u = useUnitFormat()
  const update = useUpdateTireReading(vin)
  const num = (v: number | string | null | undefined): number | null =>
    v === null || v === undefined || v === '' ? null : Number(v)

  const [form, setForm] = useState<EditorState>(() => {
    const odometer = seedUnitField(num(reading.odometer_km), u.distance)
    const tread = seedUnitField(num(reading.tread_depth_mm), u.tread)
    const pressure = seedUnitField(num(reading.pressure_kpa), u.pressure)
    return {
      recorded_at: reading.recorded_at,
      odometer_km: { typed: odometer.display, origin: odometer },
      tread_depth_mm: tread.display,
      pressure_kpa: pressure.display,
      notes: reading.notes ?? '',
      origins: { tread_depth_mm: tread, pressure_kpa: pressure },
    }
  })

  const save = () => {
    if (form.recorded_at === '') {
      toast.error(t('tireList.readingDateRequired'))
      return
    }
    const tread = canonicalFromUnitField(
      normaliseTreadEntry(form.tread_depth_mm, u.tread),
      form.origins.tread_depth_mm,
      u.tread
    )
    const pressure = canonicalFromUnitField(form.pressure_kpa, form.origins.pressure_kpa, u.pressure)
    /* The rule `TireReadingUpdate` enforces on the result, checked here so
       the user reads it before a round trip. */
    if (tread === null && pressure === null) {
      toast.error(t('tireList.treadOrPressureRequired'))
      return
    }
    update.mutate(
      {
        tireId: tire.id,
        readingId: reading.id,
        recorded_at: form.recorded_at,
        odometer_km: canonicalFromUnitField(
          form.odometer_km.typed,
          form.odometer_km.origin,
          u.distance
        ),
        tread_depth_mm: tread,
        pressure_kpa: pressure,
        notes: form.notes.trim() || null,
      },
      {
        onSuccess: () => {
          toast.success(t('tireList.readingUpdated'))
          onClose()
        },
        onError: (err: unknown) =>
          toast.error(getActionErrorMessage(err, t('tireList.readingUpdateAction'))),
      }
    )
  }

  return (
    <Drawer
      nested
      open={open}
      onClose={onClose}
      title={t('tireList.editReadingTitle', {
        position: labelFor(tire.position),
        date: formatDateForDisplay(reading.recorded_at),
      })}
      icon={Gauge}
      width="xs"
      closeLabel={t('common:close')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common:cancel')}
          </Button>
          <Button variant="primary" disabled={update.isPending} onClick={save}>
            {t('common:save')}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <MountEventFields
          vin={vin}
          idPrefix="reading-edit"
          dateLabel={t('common:date')}
          date={form.recorded_at}
          onDateChange={(next) => setForm((prev) => ({ ...prev, recorded_at: next }))}
          odometerLabel={t('tireList.odometerWithUnit', { unit: u.distance.label })}
          odometer={form.odometer_km}
          onOdometerChange={(next) => setForm((prev) => ({ ...prev, odometer_km: next }))}
        />
        <TreadField
          id="reading-edit-tread"
          label={t('tireList.treadWithUnit', { unit: u.tread.label })}
          value={form.tread_depth_mm}
          onChange={(next) => setForm((prev) => ({ ...prev, tread_depth_mm: next }))}
        />
        <Field id="reading-edit-pressure" label={t('tireList.pressureWithUnit', { unit: u.pressure.label })}>
          <Input
            id="reading-edit-pressure"
            type="number"
            step={u.pressure.step}
            value={form.pressure_kpa}
            onChange={(e) => setForm((prev) => ({ ...prev, pressure_kpa: e.target.value }))}
          />
        </Field>
        <Field id="reading-edit-notes" label={t('tireList.notes')}>
          <Input
            id="reading-edit-notes"
            value={form.notes}
            onChange={(e) => setForm((prev) => ({ ...prev, notes: e.target.value }))}
          />
        </Field>
      </div>
    </Drawer>
  )
}
