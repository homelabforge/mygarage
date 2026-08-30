import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Trash2, ChevronDown, ChevronUp, Clipboard, Wrench, Bell } from 'lucide-react'
import type { ServiceVisitFormLineItem } from '../types/serviceVisit'
import type { ReminderDraft } from '../types/reminder'
import type { Supply } from '../types/supplies'
import InspectionResult from './InspectionResult'
import CurrencyInputPrefix from './common/CurrencyInputPrefix'
import SupplyUsedPicker from './SupplyUsedPicker'
import { Select } from './ui'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'
import { useUnitFormat } from '../hooks/useUnitFormat'
import { readNumber } from '../utils/decimalSafe'
import { getActiveLocale } from '@/constants/i18n'

// Service suggestions per category. Module scope can't reach `t`, so these are
// translation-key suffixes under `lineItemEditor.misc.suggestions.*`, resolved
// at render. The record keys are service-category IDs — never translate those.
const SERVICE_SUGGESTION_KEYS: Record<string, string[]> = {
  Maintenance: ['oilChange', 'tireRotation', 'tireReplacement', 'airFilter', 'cabinAirFilter', 'brakePadReplacement', 'brakeRotorReplacement', 'sparkPlugReplacement', 'batteryReplacement', 'alternatorReplacement', 'starterReplacement', 'coolantFlush', 'transmissionFluidChange', 'differentialFluidChange', 'fuelFilterReplacement', 'serpentineBelt', 'timingBeltChain', 'powerSteeringFlush', 'wheelAlignment', 'wheelBalancing', 'tpmsReset', 'wiperBlades', 'thermostatReplacement', 'oxygenSensor', 'pcvValve', 'hoseReplacement', 'fluidTopOff'],
  Inspection: ['multiPointInspection', 'safetyInspection', 'emissionsTest', 'stateAnnualInspection', 'prePurchaseInspection', 'preTripInspection', 'brakeInspection', 'tireTreadCheck', 'suspensionInspection', 'exhaustInspection', 'fluidLevelCheck', 'batteryChargingSystemTest', 'alignmentCheck', 'fourWdAwdSystemCheck'],
  Collision: ['paintlessDentRepairPdr', 'paintRepair', 'bodyPanelReplacement', 'bumperReplacement', 'fenderReplacement', 'hoodReplacement', 'doorPanelReplacement', 'windshieldReplacement', 'sideWindowReplacement', 'rearGlassReplacement', 'structuralFrameRepair', 'airbagReplacement', 'radiatorReplacement', 'headlightReplacement', 'taillightReplacement'],
  Upgrades: ['aftermarketExhaust', 'coldAirIntake', 'performanceTuneEcuFlash', 'suspensionLiftKit', 'loweringKit', 'wheelsAndTires', 'windowTint', 'audioUpgrade', 'remoteStart', 'dashCam', 'runningBoards', 'bedLiner', 'trailerHitch', 'roofRack', 'ledLighting', 'interiorUpholstery'],
  Detailing: ['fullDetail', 'interiorDetail', 'exteriorDetail', 'handWashAndWax', 'paintCorrection', 'ceramicCoating', 'paintProtectionFilmPpf', 'upholsteryCleaning', 'odorElimination', 'engineBayCleaning'],
}

interface LineItemEditorProps {
  item: ServiceVisitFormLineItem
  index: number
  // The visit's vehicle VIN — scopes SupplyUsedPicker's ADDABLE options to
  // shared + this-vehicle supplies.
  vin: string
  // Full (active + archived, UNFILTERED by vin) supplies list, resolved once by
  // ServiceVisitForm and threaded through — see SupplyUsedPicker for why this
  // isn't fetched here. Unfiltered so existing usages of an archived/repinned
  // supply still resolve their name.
  supplies: Supply[]
  failedInspections: { refId: number; description: string }[]
  onChange: (index: number, field: keyof ServiceVisitFormLineItem, value: unknown) => void
  onRemove: (index: number) => void
  disabled?: boolean
  categories?: string[]
  isNewItem?: boolean
  currentMileage?: number | null
}

export default function LineItemEditor({
  item,
  index,
  vin,
  supplies,
  failedInspections,
  onChange,
  onRemove,
  disabled = false,
  categories = [],
  isNewItem = true,
  currentMileage,
}: LineItemEditorProps) {
  const { t } = useTranslation('vehicles')
  const { formatCurrency } = useCurrencyPreference()
  const u = useUnitFormat()
  const [expanded, setExpanded] = useState(true)
  const [showSuggestions, setShowSuggestions] = useState(false)
  // ★ This component WRITES canonical storage, which an earlier plan revision
  // missed: the mileage typed below is converted here and lands in
  // `reminderDraft.due_mileage_km`, which ServiceVisitForm posts as canonical
  // kilometres. It used to convert on `useUnitPreference().system`, which spec
  // D8 collapses from VOLUME, so a `{volume: 'L', distance: 'mi'}` account
  // entering a 500-mile reminder stored 500 km instead of 804.67.
  //
  // There is no origin to preserve here. The draft is created empty
  // (`due_mileage_km: undefined`) and only ever holds what this control just
  // converted, so `toInputValue` and `toCanonical` are the whole round trip and
  // the tests pin it as a fixed point rather than a re-conversion of history.
  //
  // currentMileage is in canonical km; show it in the client's distance unit.
  const currentDisplay = u.distance.toDisplay(currentMileage)

  const suggestions = useMemo(
    () =>
      item.category
        ? (SERVICE_SUGGESTION_KEYS[item.category] ?? []).map((key) =>
            t(`lineItemEditor.misc.suggestions.${key}`)
          )
        : [],
    [item.category, t]
  )
  const filteredSuggestions = suggestions.filter(s =>
    s.toLowerCase().includes(item.description.toLowerCase())
  )

  const handleReminderToggle = (enabled: boolean) => {
    if (enabled) {
      const draft: ReminderDraft = {
        enabled: true,
        title: item.description || t('lineItemEditor.misc.defaultReminderTitle'),
        reminder_type: 'date',
        due_date: undefined,
        due_mileage_km: undefined,
        notes: undefined,
      }
      onChange(index, 'reminderDraft', draft)
    } else {
      onChange(index, 'reminderDraft', undefined)
    }
  }

  const handleReminderFieldChange = (field: keyof ReminderDraft, value: unknown) => {
    if (!item.reminderDraft) return
    onChange(index, 'reminderDraft', { ...item.reminderDraft, [field]: value })
  }

  return (
    <div className="border border-garage-border rounded-lg bg-garage-surface">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-garage-border">
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="p-1 text-garage-text-muted hover:text-garage-text"
        >
          {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>

        <div className="flex-1 flex items-center gap-2">
          {item.is_inspection ? (
            <Clipboard className="w-4 h-4 text-primary" />
          ) : (
            <Wrench className="w-4 h-4 text-garage-text-muted" />
          )}
          <span className="text-sm text-garage-text font-medium truncate">
            {item.description || t('lineItemEditor.misc.lineItem', { number: index + 1 })}
          </span>
          {item.is_inspection && (
            <span className="px-2 py-0.5 text-xs bg-primary/20 text-primary rounded">{t('lineItemEditor.misc.inspectionBadge')}</span>
          )}
          {item.category && (
            <span className="px-2 py-0.5 text-xs bg-garage-bg text-garage-text-muted rounded">{item.category}</span>
          )}
        </div>

        {item.cost !== undefined && item.cost > 0 && (
          <span className="text-sm text-garage-text-muted">{formatCurrency(item.cost)}</span>
        )}

        <button
          type="button"
          onClick={() => onRemove(index)}
          disabled={disabled}
          className="p-1 text-danger hover:bg-danger/10 rounded disabled:opacity-50"
          title={t('lineItemEditor.misc.removeLineItem')}
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      {/* Content */}
      {expanded && (
        <div className="p-4 space-y-4">
          {/* Category and Description */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div>
              <label className="block text-sm font-medium text-garage-text mb-1">
                {t('lineItemEditor.misc.categoryLabel')}
              </label>
              <Select
                value={item.category}
                onChange={(e) => onChange(index, 'category', e.target.value)}
                disabled={disabled}
                placeholder={t('lineItemEditor.misc.selectPlaceholder')}
                options={categories.map((cat) => ({ value: cat, label: cat }))}
              />
            </div>

            <div className="md:col-span-2 relative">
              <label className="block text-sm font-medium text-garage-text mb-1">
                {t('lineItemEditor.misc.descriptionLabel')} <span className="text-danger">*</span>
              </label>
              <input
                type="text"
                value={item.description}
                onChange={(e) => {
                  onChange(index, 'description', e.target.value)
                  setShowSuggestions(true)
                }}
                onFocus={() => setShowSuggestions(true)}
                onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
                placeholder={
                  item.category
                    ? t('lineItemEditor.misc.typeOrSelect')
                    : t('lineItemEditor.misc.selectCategoryFirst')
                }
                disabled={disabled}
                className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
              />
              {/* Service suggestions dropdown */}
              {showSuggestions && item.category && filteredSuggestions.length > 0 && item.description.length < 50 && (
                <div className="absolute z-10 w-full mt-1 bg-garage-surface border border-garage-border rounded-md shadow-lg max-h-48 overflow-y-auto">
                  {filteredSuggestions.slice(0, 8).map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      onMouseDown={(e) => {
                        e.preventDefault()
                        onChange(index, 'description', suggestion)
                        setShowSuggestions(false)
                      }}
                      className="w-full text-left px-3 py-2 text-sm text-garage-text hover:bg-primary/10 transition-colors"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium text-garage-text mb-1">{t('lineItemEditor.cost')}</label>
              <div className="relative">
                <CurrencyInputPrefix />
                <input
                  type="number"
                  value={item.cost ?? ''}
                  onChange={(e) => onChange(index, 'cost', e.target.value ? parseFloat(e.target.value) : undefined)}
                  min="0"
                  step="0.01"
                  placeholder="0.00"
                  disabled={disabled}
                  className="w-full pl-7 pr-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                />
              </div>
            </div>
          </div>

          {/* Inspection toggle */}
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id={`inspection-${index}`}
              checked={item.is_inspection}
              onChange={(e) => {
                onChange(index, 'is_inspection', e.target.checked)
                if (!e.target.checked) {
                  onChange(index, 'inspection_result', '')
                  onChange(index, 'inspection_severity', '')
                }
              }}
              disabled={disabled}
              className="w-4 h-4 text-primary focus:ring-2 focus:ring-primary border-garage-border rounded"
            />
            <label htmlFor={`inspection-${index}`} className="text-sm text-garage-text">
              {t('lineItemEditor.misc.isInspectionItem')}
            </label>
          </div>

          {/* Inspection result (if inspection) */}
          {item.is_inspection && (
            <InspectionResult
              result={item.inspection_result}
              severity={item.inspection_severity}
              onResultChange={(val) => onChange(index, 'inspection_result', val)}
              onSeverityChange={(val) => onChange(index, 'inspection_severity', val)}
              disabled={disabled}
            />
          )}

          {/* Triggered by inspection (for repair items) — uses refId instead of array index */}
          {!item.is_inspection && failedInspections.length > 0 && (
            <div>
              <label className="block text-sm font-medium text-garage-text mb-1">
                {t('lineItemEditor.misc.triggeredByFailedInspection')}
              </label>
              <Select
                value={item.triggered_by_inspection_id ?? ''}
                onChange={(e) =>
                  onChange(index, 'triggered_by_inspection_id', e.target.value ? parseInt(e.target.value) : undefined)
                }
                disabled={disabled}
                placeholder={t('lineItemEditor.misc.notTriggeredByInspection')}
                options={failedInspections.map((inspection) => ({
                  value: String(inspection.refId),
                  label: inspection.description,
                }))}
              />
            </div>
          )}

          {/* Notes */}
          <div>
            <label className="block text-sm font-medium text-garage-text mb-1">{t('lineItemEditor.notes')}</label>
            <textarea
              value={item.notes}
              onChange={(e) => onChange(index, 'notes', e.target.value)}
              placeholder={t('lineItemEditor.misc.notesPlaceholder')}
              rows={2}
              disabled={disabled}
              className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
            />
          </div>

          {/* Supplies used — consume-picker so supply cost rolls into this repair */}
          <div className="border-t border-garage-border pt-4">
            <SupplyUsedPicker
              vin={vin}
              supplies={supplies}
              value={item.supplies_used ?? []}
              onChange={(next) => onChange(index, 'supplies_used', next)}
              disabled={disabled}
            />
          </div>

          {/* Reminder toggle — only for new items */}
          {isNewItem ? (
            <div className="border-t border-garage-border pt-4">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id={`reminder-${index}`}
                  checked={item.reminderDraft?.enabled ?? false}
                  onChange={(e) => handleReminderToggle(e.target.checked)}
                  disabled={disabled}
                  className="w-4 h-4 text-primary focus:ring-2 focus:ring-primary border-garage-border rounded"
                />
                <Bell className="w-4 h-4 text-garage-text-muted" />
                <label htmlFor={`reminder-${index}`} className="text-sm text-garage-text">
                  {t('lineItemEditor.misc.setReminder')}
                </label>
              </div>

              {item.reminderDraft?.enabled && (
                <div className="mt-3 ml-6 space-y-3 p-3 bg-garage-bg rounded-md border border-garage-border">
                  <div>
                    <label className="block text-xs font-medium text-garage-text mb-1">{t('lineItemEditor.misc.reminderTitle')}</label>
                    <input
                      type="text"
                      value={item.reminderDraft.title}
                      onChange={(e) => handleReminderFieldChange('title', e.target.value)}
                      disabled={disabled}
                      className="w-full px-2 py-1.5 text-sm border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-surface text-garage-text"
                    />
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-garage-text mb-1">{t('lineItemEditor.misc.reminderTypeLabel')}</label>
                      <Select
                        value={item.reminderDraft.reminder_type}
                        onChange={(e) => handleReminderFieldChange('reminder_type', e.target.value)}
                        disabled={disabled}
                        options={[
                          { value: 'date', label: t('lineItemEditor.misc.reminderTypeDate') },
                          { value: 'mileage', label: t('lineItemEditor.misc.reminderTypeMileage') },
                          { value: 'both', label: t('lineItemEditor.misc.reminderTypeBoth') },
                          { value: 'smart', label: t('lineItemEditor.misc.reminderTypeSmart') },
                        ]}
                      />
                    </div>
                    {['date', 'both', 'smart'].includes(item.reminderDraft.reminder_type) && (
                      <div>
                        <label className="block text-xs font-medium text-garage-text mb-1">{t('lineItemEditor.misc.dueDate')}</label>
                        <input
                          type="date"
                          value={item.reminderDraft.due_date ?? ''}
                          onChange={(e) => handleReminderFieldChange('due_date', e.target.value || undefined)}
                          disabled={disabled}
                          className="w-full px-2 py-1.5 text-sm border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-surface text-garage-text"
                        />
                      </div>
                    )}
                    {['mileage', 'both', 'smart'].includes(item.reminderDraft.reminder_type) && (
                      <div>
                        <label className="block text-xs font-medium text-garage-text mb-1">
                          {currentMileage
                            ? t('lineItemEditor.misc.distanceUntilDue', { unit: u.distance.label })
                            : t('lineItemEditor.misc.dueOdometer', { unit: u.distance.label })}
                        </label>
                        <input
                          type="number"
                          value={u.distance.toInputValue(readNumber(item.reminderDraft?.due_mileage_km))}
                          onChange={(e) => {
                            const val = e.target.value ? parseInt(e.target.value) : undefined
                            // Display -> canonical km, through the client's own
                            // distance token rather than a system collapsed
                            // from its volume choice.
                            const km = val != null ? u.distance.toCanonical(val) ?? undefined : undefined
                            handleReminderFieldChange('due_mileage_km', km)
                          }}
                          min="1"
                          /* One example for every account. R5 calls a
                             placeholder an EXAMPLE value with nothing canonical
                             to convert, and it was still being chosen by the
                             collapsed system, so a litres-and-miles account read
                             "148000" beside a `mi` label. Both an interval and a
                             reading that read plausibly in either unit need no
                             branch, which is what WarrantyForm's own mileage
                             hint has always done. */
                          placeholder={t('lineItemEditor.misc.egValue', {
                            value: currentMileage ? '5000' : '100000',
                          })}
                          disabled={disabled}
                          className="w-full px-2 py-1.5 text-sm border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-surface text-garage-text"
                        />
                        {currentMileage && item.reminderDraft.due_mileage_km != null && currentDisplay != null ? (() => {
                          const dueKm = readNumber(item.reminderDraft.due_mileage_km)
                          if (dueKm == null) return null
                          // Read back through `toInputValue`, the same function
                          // the field above renders, so the hint can never quote
                          // a different number than the input shows.
                          const intervalDisplay = readNumber(u.distance.toInputValue(dueKm))
                          if (intervalDisplay == null) return null
                          return (
                            <p className="text-xs text-garage-text-muted mt-1">
                              {t('lineItemEditor.misc.targetCalc', {
                                current: Math.round(currentDisplay).toLocaleString(getActiveLocale()),
                                interval: intervalDisplay.toLocaleString(getActiveLocale()),
                                target: (Math.round(currentDisplay) + intervalDisplay).toLocaleString(getActiveLocale()),
                                unit: u.distance.label,
                              })}
                            </p>
                          )
                        })() : !currentMileage ? (
                          <p className="text-xs text-warning mt-1">{t('lineItemEditor.misc.noOdometerData')}</p>
                        ) : null}
                      </div>
                    )}
                  </div>
                  {item.reminderDraft.reminder_type === 'smart' && (
                    <p className="text-xs text-garage-text-muted">
                      {t('lineItemEditor.misc.smartModeHelp')}
                    </p>
                  )}
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-garage-text-muted border-t border-garage-border pt-3">
              {t('lineItemEditor.misc.manageRemindersHint')}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
