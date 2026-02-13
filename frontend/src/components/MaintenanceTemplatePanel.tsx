import { useState, useEffect, useCallback } from 'react'
import { FileText, ExternalLink, Trash2, Plus } from 'lucide-react'
import { toast } from 'sonner'
import type { MaintenanceTemplate, MaintenanceTemplateListResponse, TemplateApplyResponse } from '../types/maintenanceTemplate'
import type { Vehicle } from '../types/vehicle'
import api from '../services/api'

interface MaintenanceTemplatePanelProps {
  vin: string
  vehicle?: Vehicle
}

export default function MaintenanceTemplatePanel({ vin, vehicle }: MaintenanceTemplatePanelProps) {
  const [templates, setTemplates] = useState<MaintenanceTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [applying, setApplying] = useState(false)

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

  const handleApplyTemplate = async () => {
    if (!vehicle) {
      toast.error('Vehicle information not available')
      return
    }

    setApplying(true)
    try {
      const response = await api.post('/maintenance-templates/apply', {
        vin: vin,
        duty_type: 'normal'
        // Note: current_mileage is optional - template will create time-based reminders only
        // Mileage-based reminders require manual setup
      })
      const data: TemplateApplyResponse = response.data

      if (data.success) {
        toast.success(`Successfully applied template! Created ${data.items_created} schedule items.`)
        await fetchTemplates()
        // Trigger schedule refresh
        window.dispatchEvent(new Event('reminders-refresh'))
      } else {
        toast.error(data.error || 'Failed to apply template')
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to apply template')
    } finally {
      setApplying(false)
    }
  }

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
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    })
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
        {vehicle && templates.length === 0 && (
          <button
            onClick={handleApplyTemplate}
            disabled={applying}
            className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Plus className="h-4 w-4" />
            {applying ? 'Applying...' : 'Apply Template'}
          </button>
        )}
      </div>

      {templates.length === 0 ? (
        <div className="text-center py-8 text-garage-text-muted">
          <FileText className="h-12 w-12 mx-auto mb-3 opacity-50" />
          <p className="text-sm">No maintenance templates applied yet.</p>
          {vehicle && (
            <p className="text-xs mt-2">
              Apply a manufacturer template to automatically create a recommended maintenance schedule for your {vehicle.year} {vehicle.make} {vehicle.model}.
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
                    {template.template_data?.metadata?.make || 'Unknown'} {template.template_data?.metadata?.model || 'Unknown'}
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
                  {template.template_data?.metadata?.duty_type && (
                    <p className="capitalize">{template.template_data.metadata.duty_type} duty schedule</p>
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
