import { useEffect, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { Disc, Plus, Settings2, Wrench } from 'lucide-react'

import { useBrakes } from '../../hooks/queries/useBrakes'
import {
  AXLE_OF,
  type BrakeAxleName,
  type BrakeJob,
  type BrakeMeasurement,
  type BrakePosition,
} from '../../types/brake'
import { getActionErrorMessage } from '../../utils/httpErrorHandler'
import { Button, Chip } from '../ui'
import AxleSetupDrawer from './AxleSetupDrawer'
import BrakeCornerCard from './BrakeCornerCard'
import { JobEditor, MeasurementEditor } from './BrakeEditors'
import BrakeHistoryDrawer from './BrakeHistoryDrawer'
import BrakeJobDrawer from './BrakeJobDrawer'
import LogBrakeMeasurementsDrawer from './LogBrakeMeasurementsDrawer'
import { useBrakeText } from './useBrakeText'

interface BrakeListProps {
  vin: string
  /** Open Log measurements straight away: the Tires page sent us here after a rotation. */
  logOnOpen?: boolean
  /** Told once that `logOnOpen` was acted on, so a later visit opens the page as usual. */
  onLogOpened?: () => void
}

/**
 * The Brakes tab (#202): four corners grouped by axle, each with its pads,
 * rotor or drum, wear estimate and history. Brake data belongs to the corner,
 * not the tire, so a rotation on the Tires tab never moves anything here.
 */
export default function BrakeList({ vin, logOnOpen = false, onLogOpened }: BrakeListProps): ReactElement {
  const { t } = useTranslation('vehicles')
  const text = useBrakeText()
  const { data, isLoading, error } = useBrakes(vin)
  /* Each drawer's key moves on every open, so its form seeds afresh, and it
     stays mounted after closing so its exit transition plays. */
  const [logOpen, setLogOpen] = useState(logOnOpen)
  const [logKey, setLogKey] = useState(0)
  const [jobOpen, setJobOpen] = useState(false)
  const [jobKey, setJobKey] = useState(0)
  const [jobCorners, setJobCorners] = useState<BrakePosition[]>([])
  const [setupOpen, setSetupOpen] = useState(false)
  const [setupKey, setSetupKey] = useState(0)
  /* The position outlives the close, like the other drawers' state, so the
     history keeps its corner through the exit transition instead of flashing empty. */
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyPosition, setHistoryPosition] = useState<BrakePosition | null>(null)
  const [editingMeasurement, setEditingMeasurement] = useState<BrakeMeasurement | null>(null)
  const [editingJob, setEditingJob] = useState<BrakeJob | null>(null)

  useEffect(() => {
    if (logOnOpen) onLogOpened?.()
  }, [logOnOpen, onLogOpened])

  if (isLoading) return <p className="text-sm text-text-mute">{t('common:loading')}</p>
  if (error || !data) {
    return <p className="text-sm text-danger">{getActionErrorMessage(error, t('brakes.loadAction'))}</p>
  }

  const openLog = (): void => {
    setLogKey((k) => k + 1)
    setLogOpen(true)
  }
  const openJob = (corners: BrakePosition[]): void => {
    setJobCorners(corners)
    setJobKey((k) => k + 1)
    setJobOpen(true)
  }
  const openSetup = (): void => {
    setSetupKey((k) => k + 1)
    setSetupOpen(true)
  }
  const openHistory = (position: BrakePosition): void => {
    setHistoryPosition(position)
    setHistoryOpen(true)
  }
  const axleOf = (name: BrakeAxleName) => data.axles.find((axle) => axle.axle === name) ?? data.axles[0]
  const historyCorner = data.corners.find((corner) => corner.position === historyPosition) ?? null
  const nothingYet = data.corners.every(
    (corner) => (corner.measurements ?? []).length === 0 && (corner.jobs ?? []).length === 0
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-lg font-semibold">
          <Disc className="h-5 w-5" aria-hidden="true" />
          {t('brakes.title')}
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" size="sm" icon={Settings2} onClick={openSetup}>
            {t('brakes.axleSetup')}
          </Button>
          <Button variant="secondary" size="sm" icon={Wrench} onClick={() => openJob([])}>
            {t('brakes.brakeJob')}
          </Button>
          <Button variant="primary" size="sm" icon={Plus} onClick={openLog}>
            {t('brakes.logMeasurements')}
          </Button>
        </div>
      </div>

      {nothingYet && <p className="text-sm text-text-mute">{t('brakes.emptyHint')}</p>}

      {(['front', 'rear'] as const).map((name) => {
        const axle = axleOf(name)
        const corners = data.corners.filter((corner) => AXLE_OF[corner.position] === name)
        return (
          <section key={name} className="space-y-2">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-text-mute">
              {name === 'front' ? t('brakes.frontAxle') : t('brakes.rearAxle')}
              <Chip>{text.typeLabel(axle.brake_type)}</Chip>
            </h3>
            <div className="grid gap-3 sm:grid-cols-2">
              {corners.map((corner) => (
                <BrakeCornerCard
                  key={corner.position}
                  corner={corner}
                  axle={axle}
                  overview={data}
                  onLog={openLog}
                  onJob={() => openJob(corners.map((c) => c.position))}
                  onHistory={() => openHistory(corner.position)}
                />
              ))}
            </div>
          </section>
        )
      })}

      <LogBrakeMeasurementsDrawer
        key={`log-${logKey}`}
        vin={vin}
        overview={data}
        open={logOpen}
        onClose={() => setLogOpen(false)}
      />
      <BrakeJobDrawer
        key={`job-${jobKey}`}
        vin={vin}
        overview={data}
        open={jobOpen}
        onClose={() => setJobOpen(false)}
        initialCorners={jobCorners}
      />
      <AxleSetupDrawer
        key={`setup-${setupKey}`}
        vin={vin}
        axles={data.axles}
        open={setupOpen}
        onClose={() => setSetupOpen(false)}
      />

      <BrakeHistoryDrawer
        vin={vin}
        overview={data}
        corner={historyCorner}
        open={historyOpen && historyCorner !== null}
        onClose={() => {
          setEditingMeasurement(null)
          setEditingJob(null)
          setHistoryOpen(false)
        }}
        onEditMeasurement={setEditingMeasurement}
        onEditJob={setEditingJob}
      />
      {historyCorner && editingMeasurement && (
        <MeasurementEditor
          key={editingMeasurement.id}
          vin={vin}
          overview={data}
          measurement={editingMeasurement}
          brakeType={historyCorner.brake_type}
          open
          onClose={() => setEditingMeasurement(null)}
        />
      )}
      {historyCorner && editingJob && (
        <JobEditor
          key={editingJob.id}
          vin={vin}
          overview={data}
          job={editingJob}
          open
          onClose={() => setEditingJob(null)}
        />
      )}
    </div>
  )
}
