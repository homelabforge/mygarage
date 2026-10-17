import { useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { Wrench } from 'lucide-react'
import { toast } from 'sonner'

import { useCreateBrakeJob } from '../../hooks/queries/useBrakes'
import { useUnitFormat } from '../../hooks/useUnitFormat'
import {
  AXLE_OF,
  BRAKE_POSITIONS,
  type BrakeAxleName,
  type BrakeOverview,
  type BrakePosition,
  type BrakeSurface,
} from '../../types/brake'
import { formatDateForInput } from '../../utils/dateUtils'
import { hoursFromField } from '../../utils/hoursFormat'
import { getActionErrorMessage } from '../../utils/httpErrorHandler'
import { canonicalFromUnitField } from '../../utils/unitFormat'
import MountEventFields, { EMPTY_ODOMETER, type OdometerFieldValue } from '../tires/MountEventFields'
import { Button, Chip, Drawer, Field, Input, Textarea, Toggle } from '../ui'
import { useBrakeText } from './useBrakeText'

interface BrakeJobDrawerProps {
  vin: string
  overview: BrakeOverview
  open: boolean
  onClose: () => void
  /** The corners ticked when it opens: the card's axle, or none from the page header. */
  initialCorners: BrakePosition[]
}

const AXLE_CORNERS: Record<BrakeAxleName, BrakePosition[]> = {
  front: ['FL', 'FR'],
  rear: ['RL', 'RR'],
}

/**
 * Record work on one to four corners: pads or shoes, and the rotor or drum.
 * New pads start the corner's wear estimate over, from the new thickness when
 * it's filled in. Remount it (with a `key`) to start the form over.
 */
export default function BrakeJobDrawer({
  vin,
  overview,
  open,
  onClose,
  initialCorners,
}: BrakeJobDrawerProps): ReactElement {
  const { t } = useTranslation('vehicles')
  const u = useUnitFormat()
  const text = useBrakeText()
  const create = useCreateBrakeJob(vin)
  const [date, setDate] = useState(() => formatDateForInput())
  const [odometer, setOdometer] = useState<OdometerFieldValue>(EMPTY_ODOMETER)
  const [hours, setHours] = useState('')
  const [corners, setCorners] = useState<BrakePosition[]>(initialCorners)
  const [friction, setFriction] = useState(true)
  const [surface, setSurface] = useState<BrakeSurface | null>(null)
  const [notes, setNotes] = useState('')
  const axleOf = (axle: BrakeAxleName) => overview.axles.find((a) => a.axle === axle)
  const [newThickness, setNewThickness] = useState<Record<BrakeAxleName, string>>(() => ({
    front: String(Number(axleOf('front')?.new_thickness_mm ?? 10)),
    rear: String(Number(axleOf('rear')?.new_thickness_mm ?? 10)),
  }))

  const axles = (['front', 'rear'] as const).filter((axle) =>
    corners.some((position) => AXLE_OF[position] === axle)
  )
  const types = new Set(axles.map((axle) => axleOf(axle)?.brake_type ?? 'disc'))
  const onlyDrum = types.size === 1 && types.has('drum')
  const onlyDisc = types.size === 1 && types.has('disc')

  const toggleCorner = (position: BrakePosition): void =>
    setCorners((prev) =>
      prev.includes(position) ? prev.filter((p) => p !== position) : [...prev, position]
    )

  const frictionLabel = onlyDrum
    ? t('brakes.shoesReplaced')
    : onlyDisc
      ? t('brakes.padsReplaced')
      : t('brakes.padsOrShoesReplaced')
  const surfaceLabel = onlyDrum ? t('brakes.drums') : onlyDisc ? t('brakes.rotors') : t('brakes.rotorsOrDrums')

  const handleSave = (): void => {
    if (!date) {
      toast.error(t('tireList.eventDateRequired'))
      return
    }
    if (corners.length === 0) {
      toast.error(t('brakes.pickACorner'))
      return
    }
    if (!friction && surface === null) {
      toast.error(t('brakes.jobDoesNothing'))
      return
    }
    const thickness = (position: BrakePosition): number | null => {
      if (!friction) return null
      const typed = newThickness[AXLE_OF[position]].trim()
      const n = Number(typed)
      return typed !== '' && Number.isFinite(n) ? n : null
    }
    create.mutate(
      {
        performed_on: date,
        friction_replaced: friction,
        surface,
        notes: notes.trim() || null,
        corners: BRAKE_POSITIONS.filter((p) => corners.includes(p)).map((position) => ({
          position,
          new_thickness_mm: thickness(position),
        })),
        ...(overview.tracks_distance
          ? { odometer_km: canonicalFromUnitField(odometer.typed, odometer.origin, u.distance) }
          : {}),
        ...(overview.tracks_hours ? { engine_hours: hoursFromField(hours) } : {}),
      },
      {
        onSuccess: () => {
          toast.success(t('brakes.jobSaved'))
          onClose()
        },
        onError: (err: unknown) => toast.error(getActionErrorMessage(err, t('brakes.jobAction'))),
      }
    )
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('brakes.jobTitle')}
      icon={Wrench}
      width="sm"
      closeLabel={t('common:close')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common:cancel')}
          </Button>
          <Button variant="primary" disabled={create.isPending} onClick={handleSave}>
            {t('common:save')}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <MountEventFields
          vin={vin}
          idPrefix="brake-job"
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

        <div className="space-y-2">
          <div className="text-sm font-medium">{t('brakes.corners')}</div>
          <div className="flex flex-wrap gap-2">
            {BRAKE_POSITIONS.map((position) => (
              <Chip
                key={position}
                selected={corners.includes(position)}
                onClick={() => toggleCorner(position)}
              >
                {text.labelFor(position)}
              </Chip>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="ghost" onClick={() => setCorners(AXLE_CORNERS.front)}>
              {t('brakes.frontAxle')}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setCorners(AXLE_CORNERS.rear)}>
              {t('brakes.rearAxle')}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setCorners([...BRAKE_POSITIONS])}>
              {t('brakes.allFour')}
            </Button>
          </div>
        </div>

        <Toggle id="brake-job-friction" label={frictionLabel} checked={friction} onChange={setFriction} />

        {friction &&
          axles.map((axle) => {
            const id = `brake-job-new-${axle}`
            const drum = axleOf(axle)?.brake_type === 'drum'
            return (
              <Field
                key={axle}
                id={id}
                label={
                  axle === 'front'
                    ? drum
                      ? t('brakes.newShoesFront')
                      : t('brakes.newPadsFront')
                    : drum
                      ? t('brakes.newShoesRear')
                      : t('brakes.newPadsRear')
                }
                unit="mm"
                hint={t('brakes.newThicknessHint')}
              >
                <Input
                  id={id}
                  type="number"
                  step="0.1"
                  value={newThickness[axle]}
                  onChange={(e) => setNewThickness((prev) => ({ ...prev, [axle]: e.target.value }))}
                />
              </Field>
            )
          })}

        <div className="space-y-2">
          <div className="text-sm font-medium">{surfaceLabel}</div>
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
        </div>

        <Field id="brake-job-notes" label={t('brakes.notes')}>
          <Textarea id="brake-job-notes" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
      </div>
    </Drawer>
  )
}
