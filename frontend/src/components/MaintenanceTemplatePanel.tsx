import { useState, useEffect, useCallback } from 'react'
import { FileText, ExternalLink, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import type { MaintenanceTemplate, MaintenanceTemplateListResponse } from '../types/maintenanceTemplate'
import type { Vehicle } from '../types/vehicle'
import api from '../services/api'
import { formatDateForDisplay } from '../utils/dateUtils'
import { useDateLocale } from '../hooks/useDateLocale'

interface MaintenanceTemplatePanelProps {
  vin: string
  vehicle?: Vehicle
}

// Template APPLICATION was removed with the schedule system (backend returns
// 410 Gone). This panel now only shows historical application records; the
// templates themselves remain browsable on GitHub as reference schedules.
export default function MaintenanceTemplatePanel({ vin, vehicle }: MaintenanceTemplatePanelProps) {
  const dateLocale = useDateLocale()
  const [templates, setTemplates] = useState<MaintenanceTemplate[]>([])
  const [loading, setLoading] = useState(true)

  const fetchTemplates = useCallback(async () => {
    try {
      const response = await api.get(`/maintenance-templates/vehicles/${vin}`)
      const data: MaintenanceTemplateListResponse = response.data
      setTemplates(data.templates || [])
    } catch (err) {
      console.error('Failed to fetch templates:', err)
    } finally {
      setLoading(false)
    }
  }, [vin])

  useEffect(() => {
    fetchTemplates()
  }, [fetchTemplates])

  const handleDeleteTemplate = async (templateId: number) => {
    if (!confirm('Are you sure you want to delete this template record? This will not delete the schedule items that were created.')) {
      return
    }

    try {
      await api.delete(`/maintenance-templates/vehicles/${vin}/${templateId}`)
      await fetchTemplates()
      toast.success('Template record deleted')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete template')
    }
  }

  const formatDate = (dateString: string) => {
    return formatDateForDisplay(dateString, {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    }, dateLocale)
  }

  if (loading) {
    return (
      <div className="bg-garage-surface rounded-lg border border-garage-border p-6 mb-6">
        <div className="animate-pulse">
          <div className="h-4 bg-garage-border rounded w-1/4 mb-4"></div>
          <div className="h-4 bg-garage-border rounded w-3/4"></div>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-garage-surface rounded-lg border border-garage-border p-6 mb-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-garage-text flex items-center gap-2">
          <FileText className="h-5 w-5 text-garage-text-muted" />
          Maintenance Templates
        </h3>
      </div>

      {templates.length === 0 ? (
        <div className="text-center py-8 text-garage-text-muted">
          <FileText className="h-12 w-12 mx-auto mb-3 opacity-50" />
          <p className="text-sm">Template application has been retired.</p>
          {vehicle && (
            <p className="text-xs mt-2">
              Use Reminders (Tracking &rarr; Reminders) to schedule maintenance for your {vehicle.year} {vehicle.make} {vehicle.model}. Manufacturer schedules remain available as reference on GitHub.
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {templates.map((template) => (
            <div
              key={template.id}
              className="flex items-start justify-between p-4 rounded-lg border border-garage-border hover:bg-garage-bg transition-colors"
            >
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium text-garage-text">
                    {(template.template_data as Record<string, Record<string, string>>)?.metadata?.make || 'Unknown'} {(template.template_data as Record<string, Record<string, string>>)?.metadata?.model || 'Unknown'}
                  </span>
                  {template.template_version && (
                    <span className="text-xs px-2 py-1 rounded bg-garage-bg text-garage-text-muted">
                      v{template.template_version}
                    </span>
                  )}
                </div>
                <div className="text-sm text-garage-text-muted space-y-1">
                  <p>Applied: {formatDate(template.applied_at)}</p>
                  <p>Created {template.reminders_created} schedule item{template.reminders_created !== 1 ? 's' : ''}</p>
                  {(template.template_data as Record<string, Record<string, string>>)?.metadata?.duty_type && (
                    <p className="capitalize">{(template.template_data as Record<string, Record<string, string>>).metadata.duty_type} duty schedule</p>
                  )}
                </div>
                {template.template_source.startsWith('github:') && (
                  <a
                    href={`https://github.com/homelabforge/mygarage/blob/main/maintenance-templates/templates/${template.template_source.replace('github:', '')}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 hover:underline mt-2"
                  >
                    <ExternalLink className="h-3 w-3" />
                    View on GitHub
                  </a>
                )}
              </div>
              <button
                onClick={() => handleDeleteTemplate(template.id)}
                className="ml-4 p-2 text-red-400 hover:bg-red-900/20 rounded transition-colors"
                title="Delete template record"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
