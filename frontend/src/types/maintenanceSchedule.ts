/**
 * Maintenance Schedule type definitions
 */

// Component categories for maintenance items
export type ComponentCategory =
  | 'Engine'
  | 'Transmission'
  | 'Brakes'
  | 'Tires'
  | 'Electrical'
  | 'HVAC'
  | 'Fluids'
  | 'Drivetrain'
  | 'Suspension'
  | 'Emissions'
  | 'Body/Exterior'
  | 'Interior'
  | 'Exhaust'
  | 'Fuel System'
  | 'General'
  | 'Towing'
  | 'Other'

export const COMPONENT_CATEGORIES: ComponentCategory[] = [
  'Engine',
  'Transmission',
  'Brakes',
  'Tires',
  'Electrical',
  'HVAC',
  'Fluids',
  'Drivetrain',
  'Suspension',
  'Emissions',
  'Body/Exterior',
  'Interior',
  'Exhaust',
  'Fuel System',
  'General',
  'Towing',
  'Other',
]

// Schedule item type
export type ScheduleItemType = 'service' | 'inspection'

// Schedule item status (calculated based on due dates/mileage)
export type ScheduleItemStatus = 'never_performed' | 'overdue' | 'due_soon' | 'on_track'

// Source of the schedule item
export type ScheduleItemSource = 'template' | 'custom'

export interface MaintenanceScheduleItem {
  id: number
  vin: string
  name: string
  component_category: ComponentCategory
  item_type: ScheduleItemType
  interval_months?: number
  interval_miles?: number
  source: ScheduleItemSource
  template_item_id?: string
  last_performed_date?: string
  last_performed_mileage?: number
  last_service_line_item_id?: number
  next_due_date?: string
  next_due_mileage?: number
  status: ScheduleItemStatus
  days_until_due?: number
  miles_until_due?: number
  created_at: string
  updated_at?: string
}

export interface MaintenanceScheduleItemCreate {
  name: string
  component_category: ComponentCategory
  item_type: ScheduleItemType
  interval_months?: number
  interval_miles?: number
  source?: ScheduleItemSource
  template_item_id?: string
}

export interface MaintenanceScheduleItemUpdate {
  name?: string
  component_category?: ComponentCategory
  item_type?: ScheduleItemType
  interval_months?: number
  interval_miles?: number
  last_performed_date?: string
  last_performed_mileage?: number
  last_service_line_item_id?: number
}

export interface MaintenanceScheduleListResponse {
  items: MaintenanceScheduleItem[]
  total: number
  due_soon_count: number
  overdue_count: number
  on_track_count: number
  never_performed_count: number
}

// Grouped schedule items for display
export interface GroupedScheduleItems {
  overdue: MaintenanceScheduleItem[]
  dueSoon: MaintenanceScheduleItem[]
  onTrack: MaintenanceScheduleItem[]
  neverPerformed: MaintenanceScheduleItem[]
}
