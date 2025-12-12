export interface VehicleStatistics {
  vin: string
  year: number
  make: string
  model: string
  main_photo_url?: string

  // Counts
  total_service_records: number
  total_fuel_records: number
  total_odometer_records: number
  total_reminders: number
  total_documents: number
  total_notes: number
  total_photos: number

  // Recent activity
  latest_service_date?: string
  latest_fuel_date?: string
  latest_odometer_reading?: number
  latest_odometer_date?: string

  // Upcoming reminders
  upcoming_reminders_count: number
  overdue_reminders_count: number

  // Fuel statistics
  average_mpg?: number
  recent_mpg?: number

  // Archive status
  archived_at?: string
  archived_visible: boolean
}

export interface DashboardResponse {
  total_vehicles: number
  vehicles: VehicleStatistics[]

  // Fleet-wide totals
  total_service_records: number
  total_fuel_records: number
  total_reminders: number
  total_documents: number
  total_notes: number
  total_photos: number
}
