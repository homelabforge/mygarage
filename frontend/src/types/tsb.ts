export interface TSB {
  id: number
  vin: string
  tsb_number?: string
  component: string
  summary: string
  status: 'pending' | 'acknowledged' | 'applied' | 'not_applicable' | 'ignored'
  applied_at?: string
  related_service_id?: number
  source: 'manual' | 'nhtsa'
  created_at: string
  updated_at?: string
}

export interface TSBCreate {
  vin: string
  tsb_number?: string
  component: string
  summary: string
  status?: 'pending' | 'acknowledged' | 'applied' | 'not_applicable' | 'ignored'
  related_service_id?: number
  source?: 'manual' | 'nhtsa'
}

export interface TSBUpdate {
  tsb_number?: string
  component?: string
  summary?: string
  status?: 'pending' | 'acknowledged' | 'applied' | 'not_applicable' | 'ignored'
  applied_at?: string
  related_service_id?: number
}

export interface TSBListResponse {
  tsbs: TSB[]
  total: number
}

export interface NHTSATSBSearchResponse {
  found: boolean
  count: number
  tsbs: Record<string, unknown>[]
  error?: string
}
