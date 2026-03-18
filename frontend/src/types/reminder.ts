/**
 * Vehicle Reminder type definitions
 */

export type ReminderType = 'date' | 'mileage' | 'both' | 'smart'
export type ReminderStatus = 'pending' | 'done' | 'dismissed'

export interface Reminder {
  id: number
  vin: string
  line_item_id: number | null
  title: string
  reminder_type: ReminderType
  due_date: string | null
  due_mileage: number | null
  status: ReminderStatus
  notes: string | null
  estimated_due_date: string | null
  last_notified_at: string | null
  created_at: string
  updated_at: string
}

export interface ReminderCreate {
  title: string
  reminder_type: ReminderType
  due_date?: string
  due_mileage?: number
  notes?: string
  line_item_id?: number
}

export interface ReminderUpdate {
  title?: string
  reminder_type?: ReminderType
  due_date?: string
  due_mileage?: number
  notes?: string
}

export interface ReminderDraft extends ReminderCreate {
  enabled: boolean
}
