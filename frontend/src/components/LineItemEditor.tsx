import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Trash2, ChevronDown, ChevronUp, Clipboard, Wrench, Bell } from 'lucide-react'
import type { ServiceVisitFormLineItem } from '../types/serviceVisit'
import type { ReminderDraft } from '../types/reminder'
import InspectionResult from './InspectionResult'
import CurrencyInputPrefix from './common/CurrencyInputPrefix'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitConverter, UnitFormatter } from '../utils/units'

// Service suggestions per category
const SERVICE_SUGGESTIONS: Record<string, string[]> = {
  Maintenance: ['Oil Change', 'Tire Rotation', 'Tire Replacement', 'Air Filter', 'Cabin Air Filter', 'Brake Pad Replacement', 'Brake Rotor Replacement', 'Spark Plug Replacement', 'Battery Replacement', 'Alternator Replacement', 'Starter Replacement', 'Coolant Flush', 'Transmission Fluid Change', 'Differential Fluid Change', 'Fuel Filter Replacement', 'Serpentine Belt', 'Timing Belt/Chain', 'Power Steering Flush', 'Wheel Alignment', 'Wheel Balancing', 'TPMS Reset', 'Wiper Blades', 'Thermostat Replacement', 'Oxygen Sensor', 'PCV Valve', 'Hose Replacement', 'Fluid Top-Off'],
  Inspection: ['Multi-Point Inspection', 'Safety Inspection', 'Emissions Test', 'State/Annual Inspection', 'Pre-Purchase Inspection', 'Pre-Trip Inspection', 'Brake Inspection', 'Tire Tread Check', 'Suspension Inspection', 'Exhaust Inspection', 'Fluid Level Check', 'Battery/Charging System Test', 'Alignment Check', '4WD/AWD System Check'],
  Collision: ['Paintless Dent Repair (PDR)', 'Paint Repair', 'Body Panel Replacement', 'Bumper Replacement', 'Fender Replacement', 'Hood Replacement', 'Door Panel Replacement', 'Windshield Replacement', 'Side Window Replacement', 'Rear Glass Replacement', 'Structural/Frame Repair', 'Airbag Replacement', 'Radiator Replacement', 'Headlight Replacement', 'Taillight Replacement'],
  Upgrades: ['Aftermarket Exhaust', 'Cold Air Intake', 'Performance Tune/ECU Flash', 'Suspension Lift Kit', 'Lowering Kit', 'Wheels and Tires', 'Window Tint', 'Audio Upgrade', 'Remote Start', 'Dash Cam', 'Running Boards', 'Bed Liner', 'Trailer Hitch', 'Roof Rack', 'LED Lighting', 'Interior Upholstery'],
  Detailing: ['Full Detail', 'Interior Detail', 'Exterior Detail', 'Hand Wash and Wax', 'Paint Correction', 'Ceramic Coating', 'Paint Protection Film (PPF)', 'Upholstery Cleaning', 'Odor Elimination', 'Engine Bay Cleaning'],
}

interface LineItemEditorProps {
  item: ServiceVisitFormLineItem
  index: number
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
  failedInspections,
  onChange,
  onRemove,
  disabled = false,
  categories = [],
  isNewItem = true,
  currentMileage,
}: LineItemEditorProps) {
  const { t } = useTranslation('vehicles')
  const { system } = useUnitPreference()
  const [expanded, setExpanded] = useState(true)
  const [showSuggestions, setShowSuggestions] = useState(false)
  // currentMileage is in canonical km; show user's display unit.
  const currentDisplay = currentMileage != null
    ? (system === 'imperial' ? UnitConverter.kmToMiles(currentMileage) ?? currentMileage : currentMileage)
    : null

  const suggestions = item.category ? SERVICE_SUGGESTIONS[item.category] || [] : []
  const filteredSuggestions = suggestions.filter(s =>
    s.toLowerCase().includes(item.description.toLowerCase())
  )

  const handleReminderToggle = (enabled: boolean) => {
    if (enabled) {
      const draft: ReminderDraft = {
        enabled: true,
        title: item.description || 'Service reminder',
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
            {item.description || `Line Item ${index + 1}`}
          </span>
          {item.is_inspection && (
            <span className="px-2 py-0.5 text-xs bg-primary/20 text-primary rounded">Inspection</span>
          )}
          {item.category && (
            <span className="px-2 py-0.5 text-xs bg-garage-bg text-garage-text-muted rounded">{item.category}</span>
          )}
        </div>

        {item.cost !== undefined && item.cost > 0 && (
          <span className="text-sm text-garage-text-muted">${item.cost.toFixed(2)}</span>
        )}

        <button
          type="button"
          onClick={() => onRemove(index)}
          disabled={disabled}
          className="p-1 text-danger hover:bg-danger/10 rounded disabled:opacity-50"
          title="Remove line item"
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
                Category
              </label>
              <select
                value={item.category}
                onChange={(e) => onChange(index, 'category', e.target.value)}
                disabled={disabled}
                className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
              >
                <option value="">Select...</option>
                {categories.map((cat) => (
                  <option key={cat} value={cat}>{cat}</option>
                ))}
              </select>
            </div>

            <div className="md:col-span-2 relative">
              <label className="block text-sm font-medium text-garage-text mb-1">
                Description <span className="text-danger">*</span>
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
                placeholder={item.category ? 'Type or select a service...' : 'Select a category first...'}
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
              This is an inspection item
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
                Triggered by Failed Inspection
              </label>
              <select
                value={item.triggered_by_inspection_id ?? ''}
                onChange={(e) =>
                  onChange(index, 'triggered_by_inspection_id', e.target.value ? parseInt(e.target.value) : undefined)
                }
                disabled={disabled}
                className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
              >
                <option value="">Not triggered by inspection</option>
                {failedInspections.map((inspection) => (
                  <option key={inspection.refId} value={inspection.refId}>
                    {inspection.description}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Notes */}
          <div>
            <label className="block text-sm font-medium text-garage-text mb-1">{t('lineItemEditor.notes')}</label>
            <textarea
              value={item.notes}
              onChange={(e) => onChange(index, 'notes', e.target.value)}
              placeholder="Additional details..."
              rows={2}
              disabled={disabled}
              className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
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
                  Set a reminder for next service
                </label>
              </div>

              {item.reminderDraft?.enabled && (
                <div className="mt-3 ml-6 space-y-3 p-3 bg-garage-bg rounded-md border border-garage-border">
                  <div>
                    <label className="block text-xs font-medium text-garage-text mb-1">Reminder Title</label>
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
                      <label className="block text-xs font-medium text-garage-text mb-1">Type</label>
                      <select
                        value={item.reminderDraft.reminder_type}
                        onChange={(e) => handleReminderFieldChange('reminder_type', e.target.value)}
                        disabled={disabled}
                        className="w-full px-2 py-1.5 text-sm border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-surface text-garage-text"
                      >
                        <option value="date">Date</option>
                        <option value="mileage">Mileage</option>
                        <option value="both">Both</option>
                        <option value="smart">Smart</option>
                      </select>
                    </div>
                    {['date', 'both', 'smart'].includes(item.reminderDraft.reminder_type) && (
                      <div>
                        <label className="block text-xs font-medium text-garage-text mb-1">Due Date</label>
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
                          {currentMileage ? `Distance Until Due (${UnitFormatter.getDistanceUnit(system)})` : `Due Odometer (${UnitFormatter.getDistanceUnit(system)})`}
                        </label>
                        <input
                          type="number"
                          value={(() => {
                            const km = item.reminderDraft?.due_mileage_km
                            if (km == null) return ''
                            const num = typeof km === 'string' ? parseFloat(km) : km
                            if (isNaN(num)) return ''
                            return system === 'imperial'
                              ? Math.round(UnitConverter.kmToMiles(num) ?? num)
                              : Math.round(num)
                          })()}
                          onChange={(e) => {
                            const val = e.target.value ? parseInt(e.target.value) : undefined
                            // Convert user-entered display value to canonical km.
                            const km = val != null
                              ? (system === 'imperial' ? UnitConverter.milesToKm(val) ?? val : val)
                              : undefined
                            handleReminderFieldChange('due_mileage_km', km)
                          }}
                          min="1"
                          placeholder={currentMileage ? 'e.g., 5000' : (system === 'imperial' ? 'e.g., 92000' : 'e.g., 148000')}
                          disabled={disabled}
                          className="w-full px-2 py-1.5 text-sm border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-surface text-garage-text"
                        />
                        {currentMileage && item.reminderDraft.due_mileage_km != null && currentDisplay != null ? (() => {
                          const dueKmRaw = item.reminderDraft.due_mileage_km
                          const dueKm = typeof dueKmRaw === 'string' ? parseFloat(dueKmRaw) : dueKmRaw
                          if (dueKm == null || isNaN(dueKm)) return null
                          const intervalDisplay = system === 'imperial'
                            ? Math.round(UnitConverter.kmToMiles(dueKm) ?? dueKm)
                            : Math.round(dueKm)
                          return (
                            <p className="text-xs text-garage-text-muted mt-1">
                              Current: {Math.round(currentDisplay).toLocaleString()} + {intervalDisplay.toLocaleString()} = {(Math.round(currentDisplay) + intervalDisplay).toLocaleString()} {UnitFormatter.getDistanceUnit(system)} target
                            </p>
                          )
                        })() : !currentMileage ? (
                          <p className="text-xs text-warning mt-1">No odometer data — enter absolute target distance</p>
                        ) : null}
                      </div>
                    )}
                  </div>
                  {item.reminderDraft.reminder_type === 'smart' && (
                    <p className="text-xs text-garage-text-muted">
                      Smart mode uses your driving history to estimate when you'll hit the mileage target.
                      The date acts as a hard cap — you'll be notified by whichever comes first.
                    </p>
                  )}
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-garage-text-muted border-t border-garage-border pt-3">
              To manage reminders for this service, go to the Tracking tab.
            </p>
          )}
        </div>
      )}
    </div>
  )
}
