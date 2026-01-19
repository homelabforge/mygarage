export interface MonthlyCostSummary {
  year: number
  month: number
  month_name: string
  total_service_cost: string
  total_fuel_cost: string
  total_spot_rental_cost: string
  total_cost: string
  service_count: number
  fuel_count: number
  spot_rental_count: number
}

export interface ServiceTypeCostBreakdown {
  service_type: string
  total_cost: string
  count: number
  average_cost: string
  last_service_date: string | null
}

export interface FuelEconomyDataPoint {
  date: string
  mpg: string
  mileage: number
  gallons: string
  cost: string
}

export interface FuelEconomyTrend {
  average_mpg: string | null
  best_mpg: string | null
  worst_mpg: string | null
  recent_mpg: string | null
  trend: 'improving' | 'declining' | 'stable'
  data_points: FuelEconomyDataPoint[]
}

export interface ServiceHistoryItem {
  date: string
  service_type: string
  description: string | null
  mileage: number | null
  cost: string | null
  vendor_name: string | null
  days_since_last: number | null
  miles_since_last: number | null
}

export interface MaintenancePrediction {
  service_type: string
  predicted_date: string | null
  predicted_mileage: number | null
  days_until_due: number | null
  miles_until_due: number | null
  average_interval_days: number | null
  average_interval_miles: number | null
  confidence: 'high' | 'medium' | 'low'
  has_manual_reminder: boolean
  manual_reminder_date: string | null
  manual_reminder_mileage: number | null
}

export interface CostAnalysis {
  total_service_cost: string
  total_fuel_cost: string
  total_cost: string
  average_monthly_cost: string
  service_count: number
  fuel_count: number
  months_tracked: number
  cost_per_mile: string | null
  rolling_avg_3m: string | null
  rolling_avg_6m: string | null
  rolling_avg_12m: string | null
  trend_direction: 'increasing' | 'decreasing' | 'stable'
  monthly_breakdown: MonthlyCostSummary[]
  service_type_breakdown: ServiceTypeCostBreakdown[]
  anomalies: AnomalyAlert[]
}

export interface CostProjection {
  monthly_average: string
  six_month_projection: string
  twelve_month_projection: string
  assumptions: string
}

export type FuelAlertSeverity = 'info' | 'warning' | 'critical'

export interface FuelEfficiencyAlert {
  title: string
  severity: FuelAlertSeverity
  message: string
  recent_mpg: string | null
  baseline_mpg: string | null
}

export type AnomalySeverity = 'warning' | 'critical'

export interface AnomalyAlert {
  month: string
  amount: string
  baseline: string
  deviation_percent: string
  severity: AnomalySeverity
  message: string
}

export interface VehicleAnalytics {
  vin: string
  vehicle_name: string
  vehicle_type: string
  cost_analysis: CostAnalysis
  cost_projection: CostProjection
  fuel_economy: FuelEconomyTrend
  fuel_alerts: FuelEfficiencyAlert[]
  service_history: ServiceHistoryItem[]
  predictions: MaintenancePrediction[]
  total_miles_driven: number | null
  average_miles_per_month: number | null
  days_owned: number | null
  propane_analysis?: {
    total_spent: string
    total_gallons: string
    avg_price_per_gallon: string | null
    record_count: number
    monthly_trend: Array<{
      year: number
      month: number
      month_name: string
      total_cost: number
      total_gallons: number
      avg_price_per_gallon: number
    }>
  }
  spot_rental_analysis?: {
    total_cost: string
    billing_count: number
    monthly_average: string
    monthly_trend: Array<{
      year: number
      month: number
      month_name: string
      total_cost: number
      monthly_rate: number
      electric: number
      water: number
      waste: number
    }>
  }
}

export interface GarageCostTotals {
  total_garage_value: string
  total_maintenance: string
  total_fuel: string
  total_insurance: string
  total_taxes: string
}

export interface GarageCostByCategory {
  category: string
  amount: string
}

export interface GarageVehicleCost {
  vin: string
  name: string
  purchase_price: string
  total_maintenance: string
  total_fuel: string
  total_cost: string
}

export interface GarageMonthlyTrend {
  month: string
  maintenance: string
  fuel: string
  total: string
}

export interface GarageAnalytics {
  total_costs: GarageCostTotals
  cost_breakdown_by_category: GarageCostByCategory[]
  cost_by_vehicle: GarageVehicleCost[]
  monthly_trends: GarageMonthlyTrend[]
  vehicle_count: number
}

// New analytics types

export interface VendorAnalysis {
  vendor_name: string
  total_spent: string
  service_count: number
  average_cost: string
  service_types: string[]
  last_service_date: string | null
}

export interface VendorAnalyticsSummary {
  vendors: VendorAnalysis[]
  total_vendors: number
  most_used_vendor: string | null
  highest_spending_vendor: string | null
}

export interface SeasonalAnalysis {
  season: string
  total_cost: string
  average_cost: string
  service_count: number
  variance_from_annual: string
  common_services: string[]
}

export interface SeasonalAnalyticsSummary {
  seasons: SeasonalAnalysis[]
  highest_cost_season: string | null
  lowest_cost_season: string | null
  annual_average: string
}

export interface CategoryChange {
  category: string
  period1_value: string
  period2_value: string
  change_amount: string
  change_percent: string
}

export interface PeriodComparison {
  period1_label: string
  period2_label: string
  period1_start: string
  period1_end: string
  period2_start: string
  period2_end: string
  period1_total_cost: string
  period2_total_cost: string
  cost_change_amount: string
  cost_change_percent: string
  period1_service_count: number
  period2_service_count: number
  service_count_change: number
  category_changes: CategoryChange[]
  period1_avg_mpg: string | null
  period2_avg_mpg: string | null
  mpg_change_percent: string | null
}
