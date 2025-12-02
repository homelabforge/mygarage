export interface Recall {
  id: number
  vin: string
  nhtsa_campaign_number?: string
  component: string
  summary: string
  consequence?: string
  remedy?: string
  date_announced?: string
  is_resolved: boolean
  resolved_at?: string
  notes?: string
  created_at: string
}

export interface RecallCreate {
  vin: string
  nhtsa_campaign_number?: string
  component: string
  summary: string
  consequence?: string
  remedy?: string
  date_announced?: string
  is_resolved?: boolean
  notes?: string
}

export interface RecallUpdate {
  nhtsa_campaign_number?: string
  component?: string
  summary?: string
  consequence?: string
  remedy?: string
  date_announced?: string
  is_resolved?: boolean
  notes?: string
}

export interface RecallListResponse {
  recalls: Recall[]
  total: number
  active_count: number
  resolved_count: number
}
