/**
 * Calendar event type definitions
 */

export type EventType = 'reminder' | 'insurance' | 'warranty' | 'service'
export type EventUrgency = 'overdue' | 'high' | 'medium' | 'low' | 'historical'
export type EventCategory = 'maintenance' | 'legal' | 'financial' | 'history'

export interface CalendarEvent {
  id: string // Format: 'type-id'
  type: EventType
  title: string
  description?: string
  date: string // ISO date string
  vehicle_vin: string
  vehicle_nickname?: string
  vehicle_color?: string // Phase 3: Custom vehicle color
  urgency: EventUrgency
  is_recurring: boolean
  is_completed: boolean
  is_estimated: boolean // Phase 3: Date estimated from mileage
  category: EventCategory
  notes?: string // Phase 3: Event notes
  due_mileage?: number // Phase 3: Mileage-based reminders
}

export interface CalendarSummary {
  total: number
  overdue: number
  upcoming_7_days: number
  upcoming_30_days: number
}

export interface CalendarResponse {
  events: CalendarEvent[]
  summary: CalendarSummary
}
