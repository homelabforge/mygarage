import { CheckCircle, XCircle, AlertTriangle } from 'lucide-react'
import type { InspectionResult as InspectionResultType, InspectionSeverity } from '../types/serviceVisit'

interface InspectionResultProps {
  result: InspectionResultType | ''
  severity: InspectionSeverity | ''
  onResultChange: (result: InspectionResultType | '') => void
  onSeverityChange: (severity: InspectionSeverity | '') => void
  disabled?: boolean
}

const RESULT_OPTIONS: { value: InspectionResultType; label: string; icon: typeof CheckCircle; color: string }[] = [
  { value: 'passed', label: 'Passed', icon: CheckCircle, color: 'text-success' },
  { value: 'needs_attention', label: 'Needs Attention', icon: AlertTriangle, color: 'text-warning' },
  { value: 'failed', label: 'Failed', icon: XCircle, color: 'text-danger' },
]

const SEVERITY_OPTIONS: { value: InspectionSeverity; label: string; bgClass: string }[] = [
  { value: 'green', label: 'Minor', bgClass: 'bg-success/20 border-success text-success' },
  { value: 'yellow', label: 'Moderate', bgClass: 'bg-warning/20 border-warning text-warning' },
  { value: 'red', label: 'Severe', bgClass: 'bg-danger/20 border-danger text-danger' },
]

export default function InspectionResult({
  result,
  severity,
  onResultChange,
  onSeverityChange,
  disabled = false,
}: InspectionResultProps) {
  const showSeverity = result === 'failed' || result === 'needs_attention'

  return (
    <div className="space-y-3">
      {/* Result selection */}
      <div>
        <label className="block text-xs font-medium text-garage-text-muted mb-2">
          Inspection Result
        </label>
        <div className="flex gap-2">
          {RESULT_OPTIONS.map((option) => {
            const Icon = option.icon
            const isSelected = result === option.value
            return (
              <button
                key={option.value}
                type="button"
                onClick={() => {
                  onResultChange(isSelected ? '' : option.value)
                  // Reset severity when result changes
                  if (!isSelected && option.value === 'passed') {
                    onSeverityChange('')
                  }
                }}
                disabled={disabled}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-md transition-colors ${
                  isSelected
                    ? `border-current ${option.color} bg-current/10`
                    : 'border-garage-border text-garage-text-muted hover:border-garage-text hover:text-garage-text'
                } disabled:opacity-50 disabled:cursor-not-allowed`}
              >
                <Icon className="w-4 h-4" />
                <span>{option.label}</span>
              </button>
            )
          })}
        </div>
      </div>

      {/* Severity selection (only for failed/needs_attention) */}
      {showSeverity && (
        <div>
          <label className="block text-xs font-medium text-garage-text-muted mb-2">
            Severity Level
          </label>
          <div className="flex gap-2">
            {SEVERITY_OPTIONS.map((option) => {
              const isSelected = severity === option.value
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => onSeverityChange(isSelected ? '' : option.value)}
                  disabled={disabled}
                  className={`px-3 py-1.5 text-sm border rounded-md transition-colors ${
                    isSelected
                      ? option.bgClass
                      : 'border-garage-border text-garage-text-muted hover:border-garage-text hover:text-garage-text'
                  } disabled:opacity-50 disabled:cursor-not-allowed`}
                >
                  {option.label}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
