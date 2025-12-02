export interface Reminder {
  id: number
  vin: string
  description: string
  due_date?: string
  due_mileage?: number
  is_recurring: boolean
  recurrence_days?: number
  recurrence_miles?: number
  is_completed: boolean
  completed_at?: string
  notes?: string
  created_at: string
}

export interface ReminderListResponse {
  reminders: Reminder[]
  total: number
  active: number
  completed: number
}

export interface ReminderCreate {
  vin: string
  description: string
  due_date?: string
  due_mileage?: number
  is_recurring: boolean
  recurrence_days?: number
  recurrence_miles?: number
  notes?: string
}

export interface ReminderUpdate {
  description?: string
  due_date?: string
  due_mileage?: number
  is_recurring?: boolean
  recurrence_days?: number
  recurrence_miles?: number
  is_completed?: boolean
  notes?: string
}
