/**
 * Apply a reminder pack with a preview first.
 *
 * The backend computes, without writing, what applying would do per item:
 * the rule it reuses or creates, the service the reminder would count from
 * ("Existing maintenance history found"), the loose reminders it adopts or
 * supersedes, and the resulting due values. The owner can point an item at
 * an untyped line item (which types it) or say the work was done today, and
 * then confirm. Nothing is written until Apply.
 *
 * The intervals are editable here too (issue #165: "define a standard, and then
 * override it upon creating a reminder"). An override is not a display tweak: it
 * is re-previewed, because the plan reads the intervals and the anchor proposal
 * or a skip reason can change with them. So Apply waits for the preview to catch
 * up rather than acting on a stale plan.
 */

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Package } from 'lucide-react'
import { toast } from 'sonner'
import FormModalWrapper from './FormModalWrapper'
import { Button, Chip, Mono } from './ui'
import RecurrenceFields, { describeDue } from './RecurrenceFields'
import { useApplyPack, usePackPreview } from '../hooks/useReminders'
import { useUnitFormat } from '../hooks/useUnitFormat'
import { useDateLocale } from '../hooks/useDateLocale'
import { formatDateForDisplay } from '../utils/dateUtils'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { readNumber } from '../utils/decimalSafe'
import type { AnchorChoices, IntervalOverrides } from '../services/reminderService'
import type {
  AnchorCandidate,
  AnchorChoice,
  PackItemPlan,
  RecurrenceDraft,
} from '../types/reminder'
import { withUnitSession } from '../contexts/UnitSession'

/**
 * The item's planned intervals as a recurrence draft.
 *
 * `readNumber` rather than `Number`: the wire sends decimals as strings so no
 * precision is lost in transit, and it maps both empty and unparseable to
 * undefined where `Number` would hand `0` and `NaN` to a unit converter.
 */
const draftOf = (item: PackItemPlan): RecurrenceDraft => ({
  interval_km: readNumber(item.interval_km),
  interval_months: readNumber(item.interval_months),
  interval_days: readNumber(item.interval_days),
  interval_hours: readNumber(item.interval_hours),
})

/** A draft as the wire wants it: the form leaves a cleared field undefined, the
 *  API expects an explicit null. */
const overrideOf = (draft: RecurrenceDraft): NonNullable<IntervalOverrides[string]> => ({
  interval_km: draft.interval_km ?? null,
  interval_months: draft.interval_months ?? null,
  interval_days: draft.interval_days ?? null,
  interval_hours: draft.interval_hours ?? null,
})

/** Debounce a value so typing does not fire a preview request per keystroke. */
function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms)
    return () => clearTimeout(timer)
  }, [value, ms])
  return settled
}

interface ApplyPackDialogProps {
  vin: string
  packId: string
  packName: string
  onClose: () => void
  onApplied: () => void
}

function ApplyPackDialog({ vin, packId, packName, onClose, onApplied }: ApplyPackDialogProps) {
  const { t } = useTranslation('vehicles')
  const u = useUnitFormat()
  const dateLocale = useDateLocale()
  const [anchors, setAnchors] = useState<AnchorChoices>({})
  const [overrides, setOverrides] = useState<IntervalOverrides>({})
  const [error, setError] = useState<string | null>(null)
  const settledOverrides = useDebounced(overrides, 300)
  const settling = settledOverrides !== overrides
  const {
    data: preview,
    isLoading,
    error: previewError,
    isFetching,
  } = usePackPreview(vin, packId, anchors, settledOverrides)
  const applyMutation = useApplyPack(vin)
  // Applying against a plan that has not caught up is how a skip reason gets
  // ignored, so the button waits for both the debounce and the refetch.
  const planIsStale = settling || isFetching

  const fmtDate = (value: string | null | undefined) =>
    value ? formatDateForDisplay(value, undefined, dateLocale) : null
  const fmtKm = (value: string | number | null | undefined) =>
    value == null ? null : u.distance.format(Number(value))

  /** `undefined` keeps the backend's proposal; anything else is sent as given. */
  const setChoice = (key: string, choice: AnchorChoice | undefined) => {
    setAnchors((prev) => {
      const next = { ...prev }
      if (choice) next[key] = choice
      else delete next[key]
      return next
    })
  }

  /**
   * Record the intervals the user typed for one item.
   *
   * `RecurrenceFields` emits the whole draft, so an override always carries all
   * four intervals and there is no way to null the three the user did not touch.
   *
   * A draft with nothing left in it drops the override entirely rather than
   * sending an empty one: the schema refuses that (a rule with no interval
   * cannot exist), and reverting to the pack's value is the only other reading
   * of "I cleared it all".
   */
  const setOverride = (key: string, draft: RecurrenceDraft) => {
    setOverrides((prev) => {
      const next = { ...prev }
      if (Object.values(draft).some((v) => v != null)) next[key] = overrideOf(draft)
      else delete next[key]
      return next
    })
  }

  const handleApply = async () => {
    setError(null)
    try {
      await applyMutation.mutateAsync({ packId, anchors, overrides })
      toast.success(t('reminderList.packApplied'))
      onApplied()
    } catch (err) {
      setError(getActionErrorMessage(err, t('applyPack.action')))
    }
  }

  const candidateLabel = (c: AnchorCandidate) =>
    [fmtDate(c.date), fmtKm(c.odometer_km), c.description].filter(Boolean).join(' · ')

  const renderItem = (item: PackItemPlan) => {
    const choice = anchors[item.key] ?? undefined
    // What the user has typed for this item, if anything. The preview already
    // reflects it, so `draftOf(item)` is the same values; reading the override
    // first keeps the fields steady while a re-preview is in flight.
    const typed = overrides[item.key]
    const overridden: RecurrenceDraft | undefined = typed
      ? {
          interval_km: typed.interval_km == null ? undefined : Number(typed.interval_km),
          interval_months: typed.interval_months ?? undefined,
          interval_days: typed.interval_days ?? undefined,
          interval_hours: typed.interval_hours == null ? undefined : Number(typed.interval_hours),
        }
      : undefined
    const supersedes = item.supersede_reminder_ids ?? []
    const untyped = item.untyped_candidates ?? []
    const due = describeDue(item, (km) => u.distance.format(km), (iso) => fmtDate(iso) ?? '', t)
    return (
      <li key={item.key} className="rounded-lg border border-border bg-surface-2 p-3 space-y-2">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <span className="text-sm font-medium text-text">{item.title}</span>
          <Chip tone={item.rule_action === 'skip' ? 'warning' : 'default'}>
            {t(`applyPack.ruleAction.${item.rule_action}`)}
          </Chip>
        </div>
        {item.rule_action === 'skip' ? (
          <p className="text-xs text-warning">{t('applyPack.skipTwoRules')}</p>
        ) : (
          <>
            {item.anchor?.origin === 'history' && item.anchor.kind === 'service' && (
              <p className="text-xs text-text">
                {t('applyPack.historyFound')}{' '}
                <Mono size="xs" tone="muted">
                  {[fmtDate(item.anchor.date), fmtKm(item.anchor.odometer_km)].filter(Boolean).join(' · ')}
                </Mono>
              </p>
            )}
            {item.keep_reminder_id != null && (
              <p className="text-xs text-text-mute">
                {item.adopted ? t('applyPack.adopts') : t('applyPack.keepsExisting')}
                {supersedes.length > 0 && ` ${t('applyPack.supersedes', { count: supersedes.length })}`}
              </p>
            )}
            {item.newer_service && (
              <p className="text-xs text-text-mute">
                {t('applyPack.newerService', { when: candidateLabel(item.newer_service) })}
              </p>
            )}
            {item.anchor?.note && <p className="text-xs text-text-mute">{t(`applyPack.notes.${item.anchor.origin}`)}</p>}
            <fieldset className="space-y-1">
              <legend className="text-xs font-medium text-text-mute">{t('applyPack.countFrom')}</legend>
              <label className="flex items-center gap-2 text-xs text-text">
                <input
                  type="radio"
                  name={`anchor-${item.key}`}
                  checked={!choice}
                  onChange={() => setChoice(item.key, undefined)}
                />
                {t('applyPack.choiceProposed')}
              </label>
              {untyped.map((c) => (
                <label key={c.line_item_id} className="flex items-center gap-2 text-xs text-text">
                  <input
                    type="radio"
                    name={`anchor-${item.key}`}
                    checked={choice?.line_item_id === c.line_item_id}
                    onChange={() => setChoice(item.key, { done_today: false, line_item_id: c.line_item_id })}
                  />
                  {t('applyPack.choiceLineItem', { label: candidateLabel(c) })}
                </label>
              ))}
              <label className="flex items-center gap-2 text-xs text-text">
                <input
                  type="radio"
                  name={`anchor-${item.key}`}
                  checked={!!choice?.done_today}
                  onChange={() => setChoice(item.key, { done_today: true })}
                />
                {t('applyPack.choiceDoneToday')}
              </label>
            </fieldset>
            {/* The rule form's own interval editor, not a copy of it: same
                labels, same units, same rounding, and it keeps each field's
                typed text internally so a half-typed value survives the
                re-preview. `key` is the item, so the fields remount only when
                the plan is for a different item. */}
            <RecurrenceFields
              key={item.key}
              idPrefix={`override-${item.key}`}
              value={overridden ?? draftOf(item)}
              onChange={(draft) => setOverride(item.key, draft)}
              tracksDistance={item.interval_hours == null}
              tracksHours={item.interval_hours != null}
              disabled={applyMutation.isPending}
            />
            {due && (
              <p className="text-xs text-text">
                {t('reminderList.due')}: <Mono size="xs" tone="accent">{due}</Mono>
              </p>
            )}
          </>
        )}
      </li>
    )
  }

  return (
    <FormModalWrapper
      title={t('applyPack.title', { pack: packName })}
      icon={Package}
      onClose={onClose}
      width="md"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={applyMutation.isPending}>
            {t('common:cancel')}
          </Button>
          <Button
            onClick={() => void handleApply()}
            loading={applyMutation.isPending}
            disabled={applyMutation.isPending || !preview || planIsStale}
          >
            {t('reminderList.applyPack')}
          </Button>
        </>
      }
    >
      <div className="p-6 space-y-4">
        <p className="text-sm text-text-mute">{t('applyPack.intro')}</p>
        {error && (
          <p role="alert" className="text-sm text-danger bg-danger/10 border border-danger rounded-lg p-3">
            {error}
          </p>
        )}
        {isLoading && <p className="text-sm text-text-mute">{t('applyPack.loading')}</p>}
        {!isLoading && planIsStale && (
          <p className="text-sm text-text-mute">{t('applyPack.recalculating')}</p>
        )}
        {previewError && <p role="alert" className="text-sm text-danger">{t('applyPack.previewFailed')}</p>}
        {preview && <ul className="space-y-3">{preview.items.map(renderItem)}</ul>}
      </div>
    </FormModalWrapper>
  )
}

// Pins its units for as long as it is open, so the interval fields in every
// row share one capture (R4).
export default withUnitSession(ApplyPackDialog)
