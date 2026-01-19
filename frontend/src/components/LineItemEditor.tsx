import { useState } from 'react'
import { Trash2, ChevronDown, ChevronUp, Clipboard, Wrench } from 'lucide-react'
import type { ServiceVisitFormLineItem } from '../types/serviceVisit'
import type { MaintenanceScheduleItem } from '../types/maintenanceSchedule'
import InspectionResult from './InspectionResult'

interface LineItemEditorProps {
  item: ServiceVisitFormLineItem
  index: number
  scheduleItems: MaintenanceScheduleItem[]
  failedInspections: { id: number; description: string }[]
  onChange: (index: number, field: keyof ServiceVisitFormLineItem, value: unknown) => void
  onRemove: (index: number) => void
  disabled?: boolean
}

export default function LineItemEditor({
  item,
  index,
  scheduleItems,
  failedInspections,
  onChange,
  onRemove,
  disabled = false,
}: LineItemEditorProps) {
  const [expanded, setExpanded] = useState(true)

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
          {/* Description and Cost */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-garage-text mb-1">
                Description <span className="text-danger">*</span>
              </label>
              <input
                type="text"
                value={item.description}
                onChange={(e) => onChange(index, 'description', e.target.value)}
                placeholder="Service performed..."
                disabled={disabled}
                className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-garage-text mb-1">Cost</label>
              <div className="relative">
                <span className="absolute left-3 top-2 text-garage-text-muted">$</span>
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

          {/* Schedule Item Link */}
          <div>
            <label className="block text-sm font-medium text-garage-text mb-1">
              Link to Schedule Item
            </label>
            <select
              value={item.schedule_item_id ?? ''}
              onChange={(e) => onChange(index, 'schedule_item_id', e.target.value ? parseInt(e.target.value) : undefined)}
              disabled={disabled}
              className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
            >
              <option value="">No link (standalone service)</option>
              {scheduleItems.map((scheduleItem) => (
                <option key={scheduleItem.id} value={scheduleItem.id}>
                  {scheduleItem.name} ({scheduleItem.component_category})
                </option>
              ))}
            </select>
            <p className="text-xs text-garage-text-muted mt-1">
              Linking updates the schedule item's "last performed" date and mileage
            </p>
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

          {/* Triggered by inspection (for repair items) */}
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
                  <option key={inspection.id} value={inspection.id}>
                    {inspection.description}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Notes */}
          <div>
            <label className="block text-sm font-medium text-garage-text mb-1">Notes</label>
            <textarea
              value={item.notes}
              onChange={(e) => onChange(index, 'notes', e.target.value)}
              placeholder="Additional details..."
              rows={2}
              disabled={disabled}
              className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
            />
          </div>
        </div>
      )}
    </div>
  )
}
