import { useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { Pencil } from 'lucide-react'
import { toast } from 'sonner'

import { useUpdateBrakeJob, useUpdateBrakeMeasurement } from '../../hooks/queries/useBrakes'
import { useUnitFormat } from '../../hooks/useUnitFormat'
import type {
  BrakeJob,
  BrakeMeasurement,
  BrakeMeasurementUpdate,
  BrakeOverview,
  BrakeSurface,
  BrakeType,
} from '../../types/brake'
import { formatDateForDisplay } from '../../utils/dateUtils'
import { hoursFromField } from '../../utils/hoursFormat'
import { getActionErrorMessage } from '../../utils/httpErrorHandler'
import { canonicalFromUnitField, seedUnitField } from '../../utils/unitFormat'
import MountEventFields, { type OdometerFieldValue } from '../tires/MountEventFields'
import { Button, Chip, Drawer, Field, Input, Toggle } from '../ui'
import { formatMm, num } from './useBrakeText'

type Figure = 'inner_pad_mm' | 'outer_pad_mm' | 'rotor_mm' | 'shoe_mm' | 'drum_mm'

const FIGURES: Record<BrakeType, Figure[]> = {
  disc: ['inner_pad_mm', 'outer_pad_mm', 'rotor_mm'],
  drum: ['shoe_mm', 'drum_mm'],
}

const typed = (v: number | string | null | undefined): string => (v == null ? '' : String(Number(v)))

const mm = (text: string): number | null => {
  const trimmed = text.trim()
  if (trimmed === '') return null
  const n = Number(trimmed)
  return Number.isFinite(n) ? n : null
}

interface MeasurementEditorProps {
  vin: string
  overview: BrakeOverview
  measurement: BrakeMeasurement
  /** The corner's brake type now. Figures of the other type stay as they are. */
  brakeType: BrakeType
  open: boolean
  onClose: () => void
}

/**
 * Correct one measurement, in a nested drawer over the history. One a brake
 * job wrote keeps the job's date and odometer; change those on the job.
 * Render with `key={measurement.id}` so it seeds once per measurement.
 */
export function MeasurementEditor({
  vin,
  overview,
  measurement,
  brakeType,
  open,
  onClose,
}: MeasurementEditorProps): ReactElement {
  const { t } = useTranslation('vehicles')
  const u = useUnitFormat()
  const update = useUpdateBrakeMeasurement(vin)
  const linked = measurement.brake_job_id != null
  const [date, setDate] = useState(measurement.recorded_at)
  const [odometer, setOdometer] = useState<OdometerFieldValue>(() => {
    const seed = seedUnitField(num(measurement.odometer_km), u.distance)
    return { typed: seed.display, origin: seed }
  })
  const [hours, setHours] = useState(
    measurement.engine_hours != null ? Number(measurement.engine_hours).toFixed(1) : ''
  )
  const [values, setValues] = useState<Record<Figure, string>>({
    inner_pad_mm: typed(measurement.inner_pad_mm),
    outer_pad_mm: typed(measurement.outer_pad_mm),
    rotor_mm: typed(measurement.rotor_mm),
    shoe_mm: typed(measurement.shoe_mm),
    drum_mm: typed(measurement.drum_mm),
  })
  const [notes, setNotes] = useState(measurement.notes ?? '')

  const labels: Record<Figure, string> = {
    inner_pad_mm: t('brakes.innerPad'),
    outer_pad_mm: t('brakes.outerPad'),
    rotor_mm: t('brakes.rotor'),
    shoe_mm: t('brakes.shoe'),
    drum_mm: t('brakes.drumDiameter'),
  }

  const save = (): void => {
    if (date === '') {
      toast.error(t('tireList.eventDateRequired'))
      return
    }
    const payload: BrakeMeasurementUpdate & { id: number } = { id: measurement.id, notes: notes.trim() || null }
    for (const name of FIGURES[brakeType]) payload[name] = mm(values[name])
    if (!linked) {
      payload.recorded_at = date
      if (overview.tracks_distance) {
        payload.odometer_km = canonicalFromUnitField(odometer.typed, odometer.origin, u.distance)
      }
      if (overview.tracks_hours) payload.engine_hours = hoursFromField(hours)
    }
    update.mutate(payload, {
      onSuccess: () => {
        toast.success(t('brakes.measurementUpdated'))
        onClose()
      },
      onError: (err: unknown) => toast.error(getActionErrorMessage(err, t('brakes.updateAction'))),
    })
  }

  return (
    <Drawer
      nested
      open={open}
      onClose={onClose}
      title={t('brakes.editMeasurementTitle', { date: formatDateForDisplay(measurement.recorded_at) })}
      icon={Pencil}
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
        {linked ? (
          <p className="text-sm text-text-mute">{t('brakes.linkedMeasurementHint')}</p>
        ) : (
          <MountEventFields
            vin={vin}
            idPrefix="brake-measurement-edit"
            dateLabel={t('common:date')}
            date={date}
            onDateChange={setDate}
            odometerLabel={t('brakes.odometerWithUnit', { unit: u.distance.label })}
            odometer={odometer}
            onOdometerChange={setOdometer}
            tracksDistance={overview.tracks_distance}
            tracksHours={overview.tracks_hours}
            hours={hours}
            onHoursChange={setHours}
          />
        )}
        {/* Figures from before the axle's type changed are kept and shown, but
            the server refuses a figure of the other type, so they aren't fields. */}
        {FIGURES[brakeType === 'disc' ? 'drum' : 'disc']
          .filter((name) => measurement[name] != null)
          .map((name) => (
            <p key={name} className="text-sm text-text-mute">
              {t('brakes.otherTypeFigure', { figure: labels[name], value: formatMm(measurement[name] ?? 0) })}
            </p>
          ))}
        {FIGURES[brakeType].map((name) => {
          const id = `brake-measurement-edit-${name}`
          return (
            <Field key={name} id={id} label={labels[name]} unit="mm">
              <Input
                id={id}
                type="number"
                step="0.1"
                value={values[name]}
                onChange={(e) => setValues((prev) => ({ ...prev, [name]: e.target.value }))}
              />
            </Field>
          )
        })}
        <Field id="brake-measurement-edit-notes" label={t('brakes.notes')}>
          <Input id="brake-measurement-edit-notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
      </div>
    </Drawer>
  )
}

interface JobEditorProps {
  vin: string
  overview: BrakeOverview
  job: BrakeJob
  open: boolean
  onClose: () => void
}

/**
 * Correct one corner's brake job. The new-pads figure it wrote moves with
 * its date and odometer, and goes if the pads come off the job.
 */
export function JobEditor({ vin, overview, job, open, onClose }: JobEditorProps): ReactElement {
  const { t } = useTranslation('vehicles')
  const u = useUnitFormat()
  const update = useUpdateBrakeJob(vin)
  const drum = job.brake_type === 'drum'
  const [date, setDate] = useState(job.performed_on)
  const [odometer, setOdometer] = useState<OdometerFieldValue>(() => {
    const seed = seedUnitField(num(job.odometer_km), u.distance)
    return { typed: seed.display, origin: seed }
  })
  const [hours, setHours] = useState(job.engine_hours != null ? Number(job.engine_hours).toFixed(1) : '')
  const [friction, setFriction] = useState(job.friction_replaced)
  const [surface, setSurface] = useState<BrakeSurface | null>(job.surface ?? null)
  const [notes, setNotes] = useState(job.notes ?? '')

  const save = (): void => {
    if (date === '') {
      toast.error(t('tireList.eventDateRequired'))
      return
    }
    if (!friction && surface === null) {
      toast.error(t('brakes.jobDoesNothing'))
      return
    }
    update.mutate(
      {
        id: job.id,
        performed_on: date,
        friction_replaced: friction,
        surface,
        notes: notes.trim() || null,
        ...(overview.tracks_distance
          ? { odometer_km: canonicalFromUnitField(odometer.typed, odometer.origin, u.distance) }
          : {}),
        ...(overview.tracks_hours ? { engine_hours: hoursFromField(hours) } : {}),
      },
      {
        onSuccess: () => {
          toast.success(t('brakes.jobUpdated'))
          onClose()
        },
        onError: (err: unknown) => toast.error(getActionErrorMessage(err, t('brakes.updateAction'))),
      }
    )
  }

  return (
    <Drawer
      nested
      open={open}
      onClose={onClose}
      title={t('brakes.editJobTitle', { date: formatDateForDisplay(job.performed_on) })}
      icon={Pencil}
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
          idPrefix="brake-job-edit"
          dateLabel={t('common:date')}
          date={date}
          onDateChange={setDate}
          odometerLabel={t('brakes.odometerWithUnit', { unit: u.distance.label })}
          odometer={odometer}
          onOdometerChange={setOdometer}
          tracksDistance={overview.tracks_distance}
          tracksHours={overview.tracks_hours}
          hours={hours}
          onHoursChange={setHours}
        />
        <Toggle
          id="brake-job-edit-friction"
          label={drum ? t('brakes.shoesReplaced') : t('brakes.padsReplaced')}
          checked={friction}
          onChange={setFriction}
        />
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">{drum ? t('brakes.drums') : t('brakes.rotors')}</legend>
          <div className="flex flex-wrap gap-2">
            <Chip selected={surface === null} onClick={() => setSurface(null)}>
              {t('brakes.surfaceNone')}
            </Chip>
            <Chip selected={surface === 'replaced'} onClick={() => setSurface('replaced')}>
              {t('brakes.surfaceReplaced')}
            </Chip>
            <Chip selected={surface === 'resurfaced'} onClick={() => setSurface('resurfaced')}>
              {t('brakes.surfaceResurfaced')}
            </Chip>
          </div>
        </fieldset>
        <Field id="brake-job-edit-notes" label={t('brakes.notes')}>
          <Input id="brake-job-edit-notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
      </div>
    </Drawer>
  )
}
