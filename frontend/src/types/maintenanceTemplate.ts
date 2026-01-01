export interface MaintenanceTemplate {
  id: number
  vin: string
  template_source: string
  template_version?: string
  template_data: MaintenanceTemplateData
  applied_at: string
  created_by: string
  reminders_created: number
  created_at: string
  updated_at?: string
}

export interface MaintenanceTemplateData {
  metadata: {
    make: string
    model: string
    year_start: number
    year_end: number
    duty_type: string
    source?: string
    contributor?: string
    version?: string
  }
  maintenance_items: MaintenanceItem[]
}

export interface MaintenanceItem {
  description: string
  interval_months?: number
  interval_miles?: number
  category: string
  severity: string
  notes?: string
}

export interface MaintenanceTemplateListResponse {
  templates: MaintenanceTemplate[]
  total: number
}

export interface TemplateSearchResponse {
  found: boolean
  template_url?: string
  template_path?: string
  template_data?: MaintenanceTemplateData
  error?: string
}

export interface TemplateApplyRequest {
  vin: string
  duty_type?: string
  current_mileage?: number
}

export interface TemplateApplyResponse {
  success: boolean
  reminders_created: number
  template_source: string
  template_version?: string
  error?: string
}
