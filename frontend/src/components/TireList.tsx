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
import { Button, IconButton, Card, Chip, Drawer, EmptyState, Input, Field } from './ui'

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

const EMPTY_READING_FORM = {
  recorded_at: '',
  odometer_km: '',
  tread_depth_mm: '',
  pressure_kpa: '',
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

  const [formOpen, setFormOpen] = useState(false)
  const [editingTireId, setEditingTireId] = useState<number | null>(null)
  const [readingTireId, setReadingTireId] = useState<number | null>(null)
  const [form, setForm] = useState<TireFormState>(EMPTY_TIRE_FORM)
  const [readingForm, setReadingForm] = useState(EMPTY_READING_FORM)

  const tires = data?.tires ?? []
  const takenPositions = new Set(tires.map((tire: Tire) => tire.position))
  const freePositions = POSITIONS.filter((p) => !takenPositions.has(p))

  /* Derived from the live list rather than held in state: a mutation refetches
   * and replaces every Tire object, so a captured one would go stale the moment
   * a reading is saved. */
  const readingTire = tires.find((tire: Tire) => tire.id === readingTireId) ?? null

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

  /* Spelled out as five literal t() calls rather than t(`…positions.${p}`):
   * validate-i18n-usage scans for string literals, so a computed key is
   * invisible to it and a typo would ship a raw `tireList.positions.RL` to the
   * user. The Record type keeps the map exhaustive. Chips still show the short
   * codes — these are for the card heading and the drawer titles, where there
   * is room and where "FL" was untranslatable English in every locale. */
  const positionLabels: Record<TirePosition, string> = {
    FL: t('tireList.positions.FL'),
    FR: t('tireList.positions.FR'),
    RL: t('tireList.positions.RL'),
    RR: t('tireList.positions.RR'),
    SPARE: t('tireList.positions.SPARE'),
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
    setFormOpen(true)
  }

  const openEditForm = (tire: Tire) => {
    setEditingTireId(tire.id)
    setForm(formFromTire(tire))
    setFormOpen(true)
  }

  const closeForm = () => {
    setFormOpen(false)
    setEditingTireId(null)
  }

  /* Seeded from the tire's current values so the common case — pressure checked,
   * tread unchanged — is a single edit rather than re-typing both. */
  const openReadingForm = (tire: Tire) => {
    setReadingForm({
      ...EMPTY_READING_FORM,
      recorded_at: new Date().toISOString().slice(0, 10),
      tread_depth_mm: tire.tread_depth_mm != null ? String(tire.tread_depth_mm) : '',
      pressure_kpa: tire.pressure_kpa != null ? String(displayPressure(tire.pressure_kpa)) : '',
    })
    setReadingTireId(tire.id)
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
          closeForm()
        },
        onError: (err) => {
          toast.error(getActionErrorMessage(err, t('tireList.saveAction')))
        },
      }
    )
  }

  /* Only reachable from the edit drawer, so `editingTireId` is the subject.
   * The mutation had no success or error callbacks at all when this lived on
   * the card, which meant a failed delete was completely silent and the row
   * simply stayed put with no explanation. */
  const handleDelete = () => {
    if (editingTireId === null) return
    if (!confirm(t('tireList.confirmDelete'))) return
    remove.mutate(editingTireId, {
      onSuccess: () => {
        toast.success(t('tireList.deleted'))
        closeForm()
      },
      onError: (err) => {
        toast.error(getActionErrorMessage(err, t('tireList.deleteAction')))
      },
    })
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

      {tires.length === 0 && (
        <EmptyState icon={Gauge} title={t('tireList.empty')} description={t('tireList.emptyHint')} />
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        {tires.map((tire: Tire) => (
          <Card key={tire.id} padding="sm" className="space-y-2">
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="font-semibold flex items-center gap-2">
                  {positionLabels[tire.position]}
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
              {/* Delete lives in the edit drawer, not here: it is the one
                  destructive action on a card whose other controls (Edit, Log
                  Reading) are routine, and sitting them side by side invites a
                  mis-tap that costs a tire's whole reading history. */}
              <IconButton
                icon={Pencil}
                label={t('tireList.edit')}
                variant="ghost"
                size="sm"
                onClick={() => openEditForm(tire)}
              />
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
            <Button size="sm" variant="secondary" onClick={() => openReadingForm(tire)}>
              {t('tireList.addReading')}
            </Button>
          </Card>
        ))}
      </div>

      <Drawer
        open={formOpen}
        onClose={closeForm}
        /* Editing names the tire, because position is a tire's whole identity
           and five otherwise-identical rows are indistinguishable without it.
           Adding stays the generic "Add Tire": retitling as the position chips
           are pressed would make a create read like an edit. */
        title={
          editingTireId !== null
            ? t('tireList.editTitleNamed', { position: positionLabels[form.position] })
            : t('tireList.addTitle')
        }
        icon={Gauge}
        width="sm"
        closeLabel={t('common:close')}
        footer={
          <>
            {/* mr-auto against the footer's justify-end: the destructive action
                sits hard left, a full footer's width away from Save. */}
            {editingTireId !== null && (
              <Button
                variant="danger"
                icon={Trash2}
                className="mr-auto"
                onClick={handleDelete}
                disabled={remove.isPending}
              >
                {t('common:delete')}
              </Button>
            )}
            <Button variant="ghost" onClick={closeForm}>
              {t('common:cancel')}
            </Button>
            <Button variant="primary" onClick={handleSave} disabled={upsert.isPending}>
              {t('common:save')}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {/* Push toggles rather than a select: five short fixed options, one tap
              instead of two-plus-a-scroll on mobile, and — the real gain — the
              occupied slots stay visible instead of silently vanishing from a
              collapsed menu.

              role="group" + aria-pressed chips, not a radiogroup: Chip is the
              app's established filter primitive (Address Book categories) and
              matching it beats hand-rolling a roving-tabindex radiogroup for
              five buttons. Field is bypassed on purpose — it renders
              <label htmlFor>, which associates with nothing when the control is
              a group of buttons, so the label is wired via aria-labelledby. */}
          <div className="mb-4">
            <span
              id="tire-position-label"
              className="mb-1 block text-sm font-medium text-text"
            >
              {t('tireList.position')}
            </span>
            <div
              role="group"
              aria-labelledby="tire-position-label"
              className="flex flex-wrap gap-2"
            >
              {POSITIONS.map((p) => {
                const locked = editingTireId !== null
                const taken = takenPositions.has(p)
                // Editing locks every chip; adding leaves occupied slots inert.
                // Chip renders a plain <span> without onClick, so an unavailable
                // slot is shown as state rather than as a dead-looking button.
                const selectable = !locked && !taken
                return (
                  <Chip
                    key={p}
                    tone={taken && !locked ? 'muted' : 'default'}
                    selected={form.position === p}
                    onClick={selectable ? () => setForm({ ...form, position: p }) : undefined}
                  >
                    {p}
                  </Chip>
                )
              })}
            </div>
          </div>
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
        </div>
      </Drawer>

      <Drawer
        open={readingTire !== null}
        onClose={() => setReadingTireId(null)}
        title={t('tireList.readingTitle', {
          position: readingTire ? positionLabels[readingTire.position] : '',
        })}
        icon={Gauge}
        width="xs"
        closeLabel={t('common:close')}
        footer={
          <>
            <Button variant="ghost" onClick={() => setReadingTireId(null)}>
              {t('common:cancel')}
            </Button>
            <Button
              variant="primary"
              disabled={addReading.isPending}
              onClick={() => readingTire && handleReading(readingTire.id)}
            >
              {t('common:save')}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field id="reading-date" label={t('common:date')}>
            <Input
              id="reading-date"
              type="date"
              value={readingForm.recorded_at}
              onChange={(e) => setReadingForm({ ...readingForm, recorded_at: e.target.value })}
            />
          </Field>
          <Field id="reading-tread" label={t('tireList.treadMm')}>
            <Input
              id="reading-tread"
              type="number"
              step="0.1"
              value={readingForm.tread_depth_mm}
              onChange={(e) => setReadingForm({ ...readingForm, tread_depth_mm: e.target.value })}
            />
          </Field>
          <Field id="reading-pressure" label={pressureLabel}>
            <Input
              id="reading-pressure"
              type="number"
              step="0.1"
              value={readingForm.pressure_kpa}
              onChange={(e) => setReadingForm({ ...readingForm, pressure_kpa: e.target.value })}
            />
          </Field>
          <Field id="reading-odo" label={odometerLabel}>
            <Input
              id="reading-odo"
              type="number"
              step="0.1"
              value={readingForm.odometer_km}
              onChange={(e) => setReadingForm({ ...readingForm, odometer_km: e.target.value })}
            />
          </Field>
        </div>
      </Drawer>
    </div>
  )
}
