/**
 * Service Record type definitions
 */

// Service category (high-level grouping)
export type ServiceCategory = 'Maintenance' | 'Inspection' | 'Collision' | 'Upgrades'

// Predefined service types organized by category
export const SERVICE_TYPES_BY_CATEGORY = {
  Maintenance: [
    'General Service',
    'Oil Change',
    'Tire Rotation',
    'Brake Service',
    'Transmission Service',
    'Coolant Flush',
    'Air Filter Replacement',
    'Cabin Filter Replacement',
    'Spark Plug Replacement',
    'Battery Replacement',
    'Wiper Blade Replacement',
    'Wheel Alignment',
    'Tire Replacement',
    'Suspension Service',
    'Exhaust Repair',
    'Fuel System Service',
    'Differential Service',
    'Transfer Case Service',
    'Engine Tune-Up',
    'Belt Replacement',
    'Hose Replacement',
  ],
  Inspection: [
    'General Inspection',
    'Annual Safety Inspection',
    'Emissions Test',
    'Pre-Purchase Inspection',
    'Brake Inspection',
    'Tire Inspection',
    'Suspension Inspection',
    'Steering Inspection',
    'Electrical System Inspection',
    'Diagnostic Scan',
  ],
  Collision: [
    'General Collision Repair',
    'Front End Repair',
    'Rear End Repair',
    'Side Impact Repair',
    'Frame Straightening',
    'Paint Repair',
    'Glass Replacement',
    'Bumper Repair',
    'Dent Removal',
    'Scratch Repair',
  ],
  Upgrades: [
    'General Upgrade',
    'Performance Upgrade',
    'Suspension Upgrade',
    'Exhaust Upgrade',
    'Intake Upgrade',
    'Audio System Upgrade',
    'Navigation System',
    'Backup Camera',
    'Remote Start',
    'Towing Package',
    'Lift Kit',
    'Wheels/Rims',
    'Lighting Upgrade',
    'Interior Upgrade',
  ],
} as const

// All service types (flat list for dropdowns)
export const ALL_SERVICE_TYPES = Object.values(SERVICE_TYPES_BY_CATEGORY).flat()

export interface ServiceRecord {
  id: number
  vin: string
  date: string
  mileage?: number
  service_type: string              // Specific service type (e.g., "Oil Change")
  cost?: number
  notes?: string
  vendor_name?: string
  vendor_location?: string
  service_category?: ServiceCategory  // Optional category grouping
  insurance_claim?: string
  created_at: string
  attachment_count?: number
}

export interface ServiceRecordCreate {
  vin: string
  date: string
  mileage?: number
  service_type: string              // Required specific service type
  cost?: number
  notes?: string
  vendor_name?: string
  vendor_location?: string
  service_category?: ServiceCategory  // Optional category
  insurance_claim?: string
}

export interface ServiceRecordUpdate {
  date?: string
  mileage?: number
  service_type?: string              // Specific service type
  cost?: number
  notes?: string
  vendor_name?: string
  vendor_location?: string
  service_category?: ServiceCategory  // Optional category
  insurance_claim?: string
}

export interface ServiceRecordListResponse {
  records: ServiceRecord[]
  total: number
}
