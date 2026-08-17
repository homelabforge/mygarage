import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, Trash2, Gauge, AlertTriangle, Pencil } from 'lucide-react'
import { toast } from 'sonner'
import { formatDateForDisplay } from '../utils/dateUtils'
import type { Tire, TirePosition } from '../types/tire'
import {
  useTires,
  useUpsertTire,
  useAddTireReading,
  useDeleteTire,
} from '../hooks/queries/useTires'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitConverter, UnitFormatter } from '../utils/units'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { Button, IconButton, Card, EmptyState, Input, Field, Select } from './ui'

const POSITIONS: TirePosition[] = ['FL', 'FR', 'RL', 'RR', 'SPARE']

interface TireFormState {
  position: TirePosition
  brand: string
  model_name: string
  size: string
  dot_code: string
  tread_depth_mm: string
  pressure_kpa: string
  min_tread_mm: string
  notes: string
}

const EMPTY_TIRE_FORM: TireFormState = {
  position: 'FL',
  brand: '',
  model_name: '',
  size: '',
  dot_code: '',
  tread_depth_mm: '',
  pressure_kpa: '',
  min_tread_mm: '2.0',
  notes: '',
}

interface TireListProps {
  vin: string
}

export default function TireList({ vin }: TireListProps) {
  const { t } = useTranslation('vehicles')
  const { data, isLoading, error } = useTires(vin)
  const upsert = useUpsertTire(vin)
  const addReading = useAddTireReading(vin)
  const remove = useDeleteTire(vin)
  const { system, showBoth } = useUnitPreference()
  const isImperial = system === 'imperial'

  const [showForm, setShowForm] = useState(false)
  const [editingTireId, setEditingTireId] = useState<number | null>(null)
  const [readingTireId, setReadingTireId] = useState<number | null>(null)
  const [form, setForm] = useState<TireFormState>(EMPTY_TIRE_FORM)
  const [readingForm, setReadingForm] = useState({
    recorded_at: new Date().toISOString().slice(0, 10),
    odometer_km: '',
    tread_depth_mm: '',
    pressure_kpa: '',
    notes: '',
  })

  const tires = data?.tires ?? []
  const takenPositions = new Set(tires.map((tire: Tire) => tire.position))
  const freePositions = POSITIONS.filter((p) => !takenPositions.has(p))

  /** Tire API fields are `number | string | null`; the unit utils take `number | null`. */
  const num = (v: number | string | null | undefined): number | null =>
    v === null || v === undefined || v === '' ? null : Number(v)

  /* Storage is metric-canonical kPa. Imperial users type PSI; metric users type
   * kPa directly. Note we do NOT use UnitFormatter.getPressureUnit here: it
   * returns 'bar' for metric, and passing a bar value into a kPa column would be
   * a 100x error. */
  const displayPressure = (kpa: number | string | null | undefined): number | null =>
    isImperial ? UnitConverter.kPaToPsi(num(kpa)) : num(kpa)

  /** Blank clears the field, so return null: `undefined` is dropped from the
   *  JSON body and the partial update would then preserve the old value. */
  const canonicalPressure = (typed: string): number | null => {
    if (!typed) return null
    return isImperial ? UnitConverter.psiToKPa(Number(typed)) : Number(typed)
  }

  const canonicalOdometer = (typed: string): number | null => {
    if (!typed) return null
    return isImperial ? UnitConverter.milesToKm(Number(typed)) : Number(typed)
  }

  const pressureLabel = t('tireList.pressureWithUnit', {
    unit: isImperial ? 'PSI' : 'kPa',
  })
  const odometerLabel = isImperial ? t('tireList.odometerMi') : t('tireList.odometerKm')

  const formFromTire = (tire: Tire): TireFormState => ({
    position: tire.position,
    brand: tire.brand ?? '',
    model_name: tire.model_name ?? '',
    size: tire.size ?? '',
    dot_code: tire.dot_code ?? '',
    tread_depth_mm: tire.tread_depth_mm != null ? String(tire.tread_depth_mm) : '',
    pressure_kpa: tire.pressure_kpa != null ? String(displayPressure(tire.pressure_kpa)) : '',
    min_tread_mm: tire.min_tread_mm != null ? String(tire.min_tread_mm) : '2.0',
    notes: tire.notes ?? '',
  })

  /* Add and Edit are deliberately separate intents. The form is one mutable
   * object holding every in-progress field, so reloading it when the position
   * dropdown changes would silently discard whatever the user had typed.
   * Instead, Add only offers unoccupied positions and Edit locks the position. */
  const openAddForm = () => {
    setEditingTireId(null)
    setForm({ ...EMPTY_TIRE_FORM, position: freePositions[0] ?? 'FL' })
    setShowForm(true)
  }

  const openEditForm = (tire: Tire) => {
    setEditingTireId(tire.id)
    setForm(formFromTire(tire))
    setShowForm(true)
  }

  const handleSave = () => {
    upsert.mutate(
      {
        vin,
        position: form.position,
        brand: form.brand || null,
        model_name: form.model_name || null,
        size: form.size || null,
        dot_code: form.dot_code || null,
        tread_depth_mm: form.tread_depth_mm ? Number(form.tread_depth_mm) : null,
        pressure_kpa: canonicalPressure(form.pressure_kpa),
        min_tread_mm: form.min_tread_mm ? Number(form.min_tread_mm) : 2.0,
        notes: form.notes || null,
      },
      {
        onSuccess: () => {
          toast.success(t('tireList.saved'))
          setShowForm(false)
          setEditingTireId(null)
        },
        onError: (err) => {
          toast.error(getActionErrorMessage(err, t('tireList.saveAction')))
        },
      }
    )
  }

  const handleReading = (tireId: number) => {
    if (!readingForm.tread_depth_mm) {
      toast.error(t('tireList.treadRequired'))
      return
    }
    addReading.mutate(
      {
        tireId,
        recorded_at: readingForm.recorded_at,
        odometer_km: canonicalOdometer(readingForm.odometer_km),
        tread_depth_mm: Number(readingForm.tread_depth_mm),
        pressure_kpa: canonicalPressure(readingForm.pressure_kpa),
        notes: readingForm.notes || null,
      },
      {
        onSuccess: () => {
          toast.success(t('tireList.readingSaved'))
          setReadingTireId(null)
        },
        onError: (err) => {
          toast.error(getActionErrorMessage(err, t('tireList.saveReadingAction')))
        },
      }
    )
  }

  if (isLoading) {
    return <div className="text-text-mute">{t('common:loading')}</div>
  }
  if (error) {
    return (
      <div className="rounded-panel border border-danger bg-danger/10 p-4 text-danger">
        {getActionErrorMessage(error, t('tireList.loadAction'))}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <Gauge className="h-5 w-5" />
          {t('tireList.title')}
        </h2>
        <Button
          variant="primary"
          size="sm"
          onClick={openAddForm}
          disabled={freePositions.length === 0}
          icon={Plus}
        >
          {t('tireList.add')}
        </Button>
      </div>

      {tires.length === 0 && !showForm && (
        <EmptyState
          icon={Gauge}
          title={t('tireList.empty')}
          description={t('tireList.emptyHint')}
        />
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        {tires.map((tire: Tire) => (
          <Card key={tire.id} padding="sm" className="space-y-2">
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="font-semibold flex items-center gap-2">
                  {tire.position}
                  {tire.below_threshold && (
                    <span className="inline-flex items-center gap-1 text-xs text-danger">
                      <AlertTriangle className="h-3.5 w-3.5" />
                      {t('tireList.lowTread')}
                    </span>
                  )}
                </div>
                <div className="text-sm text-text-mute">
                  {[tire.brand, tire.model_name, tire.size].filter(Boolean).join(' · ') || '—'}
                </div>
              </div>
              <div className="flex items-center gap-1">
                <IconButton
                  icon={Pencil}
                  label={t('tireList.edit')}
                  variant="ghost"
                  size="sm"
                  onClick={() => openEditForm(tire)}
                />
                <IconButton
                  icon={Trash2}
                  label={t('common:delete')}
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    if (confirm(t('tireList.confirmDelete'))) {
                      remove.mutate(tire.id)
                    }
                  }}
                />
              </div>
            </div>
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
              <dt className="text-text-mute">{t('tireList.dot')}</dt>
              <dd className="font-mono">{tire.dot_code || '—'}</dd>
              <dt className="text-text-mute">{t('tireList.tread')}</dt>
              <dd className="font-mono">
                {tire.tread_depth_mm != null ? `${tire.tread_depth_mm} mm` : '—'}
              </dd>
              <dt className="text-text-mute">{t('tireList.pressure')}</dt>
              <dd className="font-mono">
                {tire.pressure_kpa != null
                  ? UnitFormatter.formatPressure(num(tire.pressure_kpa), system, showBoth)
                  : '—'}
              </dd>
              <dt className="text-text-mute">{t('tireList.projection')}</dt>
              <dd className="font-mono text-xs">
                {tire.projected_km_remaining != null
                  ? `~${UnitFormatter.formatDistance(num(tire.projected_km_remaining), system, showBoth)}`
                  : '—'}
                {tire.projected_wear_date
                  ? ` · ${formatDateForDisplay(tire.projected_wear_date)}`
                  : ''}
              </dd>
            </dl>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setReadingTireId(tire.id)
                setReadingForm((f) => ({
                  ...f,
                  tread_depth_mm: tire.tread_depth_mm != null ? String(tire.tread_depth_mm) : '',
                  pressure_kpa:
                    tire.pressure_kpa != null ? String(displayPressure(tire.pressure_kpa)) : '',
                }))
              }}
            >
              {t('tireList.addReading')}
            </Button>

            {readingTireId === tire.id && (
              <div className="mt-2 space-y-2 rounded-control border border-border p-3">
                <Field id={`reading-date-${tire.id}`} label={t('common:date')}>
                  <Input
                    id={`reading-date-${tire.id}`}
                    type="date"
                    value={readingForm.recorded_at}
                    onChange={(e) => setReadingForm({ ...readingForm, recorded_at: e.target.value })}
                  />
                </Field>
                <Field id={`reading-tread-${tire.id}`} label={t('tireList.treadMm')}>
                  <Input
                    id={`reading-tread-${tire.id}`}
                    type="number"
                    step="0.1"
                    value={readingForm.tread_depth_mm}
                    onChange={(e) =>
                      setReadingForm({ ...readingForm, tread_depth_mm: e.target.value })
                    }
                  />
                </Field>
                <Field id={`reading-pressure-${tire.id}`} label={pressureLabel}>
                  <Input
                    id={`reading-pressure-${tire.id}`}
                    type="number"
                    step="0.1"
                    value={readingForm.pressure_kpa}
                    onChange={(e) =>
                      setReadingForm({ ...readingForm, pressure_kpa: e.target.value })
                    }
                  />
                </Field>
                <Field id={`reading-odo-${tire.id}`} label={odometerLabel}>
                  <Input
                    id={`reading-odo-${tire.id}`}
                    type="number"
                    step="0.1"
                    value={readingForm.odometer_km}
                    onChange={(e) =>
                      setReadingForm({ ...readingForm, odometer_km: e.target.value })
                    }
                  />
                </Field>
                <div className="flex gap-2">
                  <Button size="sm" variant="primary" onClick={() => handleReading(tire.id)}>
                    {t('common:save')}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setReadingTireId(null)}>
                    {t('common:cancel')}
                  </Button>
                </div>
              </div>
            )}
          </Card>
        ))}
      </div>

      {showForm && (
        <Card padding="sm" className="space-y-3">
          <h3 className="font-semibold">{t('tireList.formTitle')}</h3>
          <Field id="tire-position" label={t('tireList.position')}>
            <Select
              id="tire-position"
              value={form.position}
              disabled={editingTireId !== null}
              onChange={(e) => setForm({ ...form, position: e.target.value as TirePosition })}
              options={(editingTireId !== null ? POSITIONS : freePositions).map((p) => ({
                value: p,
                label: p,
              }))}
            />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="tire-brand" label={t('tireList.brand')}>
              <Input
                id="tire-brand"
                value={form.brand}
                onChange={(e) => setForm({ ...form, brand: e.target.value })}
              />
            </Field>
            <Field id="tire-model" label={t('tireList.model')}>
              <Input
                id="tire-model"
                value={form.model_name}
                onChange={(e) => setForm({ ...form, model_name: e.target.value })}
              />
            </Field>
            <Field id="tire-size" label={t('tireList.size')}>
              <Input
                id="tire-size"
                value={form.size}
                onChange={(e) => setForm({ ...form, size: e.target.value })}
              />
            </Field>
            <Field id="tire-dot" label={t('tireList.dot')}>
              <Input
                id="tire-dot"
                value={form.dot_code}
                onChange={(e) => setForm({ ...form, dot_code: e.target.value })}
              />
            </Field>
            <Field id="tire-tread" label={t('tireList.treadMm')}>
              <Input
                id="tire-tread"
                type="number"
                step="0.1"
                value={form.tread_depth_mm}
                onChange={(e) => setForm({ ...form, tread_depth_mm: e.target.value })}
              />
            </Field>
            <Field id="tire-pressure" label={pressureLabel}>
              <Input
                id="tire-pressure"
                type="number"
                step="0.1"
                value={form.pressure_kpa}
                onChange={(e) => setForm({ ...form, pressure_kpa: e.target.value })}
              />
            </Field>
            <Field id="tire-min" label={t('tireList.minTreadMm')}>
              <Input
                id="tire-min"
                type="number"
                step="0.1"
                value={form.min_tread_mm}
                onChange={(e) => setForm({ ...form, min_tread_mm: e.target.value })}
              />
            </Field>
          </div>
          <div className="flex gap-2">
            <Button variant="primary" onClick={handleSave} disabled={upsert.isPending}>
              {t('common:save')}
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setShowForm(false)
                setEditingTireId(null)
              }}
            >
              {t('common:cancel')}
            </Button>
          </div>
        </Card>
      )}
    </div>
  )
}
