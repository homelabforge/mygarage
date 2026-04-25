// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type MonthlyCostSummary = components['schemas']['MonthlyCostSummary']
export type ServiceTypeCostBreakdown = components['schemas']['ServiceTypeCostBreakdown']
export type FuelEconomyDataPoint = components['schemas']['FuelEconomyDataPoint']
export type FuelEconomyTrend = components['schemas']['FuelEconomyTrend']
export type ServiceHistoryItem = components['schemas']['ServiceHistoryItem']
export type MaintenancePrediction = components['schemas']['MaintenancePrediction']
export type CostAnalysis = components['schemas']['CostAnalysis']
export type CostProjection = components['schemas']['CostProjection']
export type FuelEfficiencyAlert = components['schemas']['FuelEfficiencyAlert']
export type AnomalyAlert = components['schemas']['AnomalyAlert']
export type VehicleAnalytics = components['schemas']['VehicleAnalytics']
export type GarageCostTotals = components['schemas']['GarageCostTotals']
export type GarageCostByCategory = components['schemas']['GarageCostByCategory']
export type GarageVehicleCost = components['schemas']['GarageVehicleCost']
export type GarageMonthlyTrend = components['schemas']['GarageMonthlyTrend']
export type GarageAnalytics = components['schemas']['GarageAnalytics']
export type VendorAnalysis = components['schemas']['VendorAnalysis']
export type VendorAnalyticsSummary = components['schemas']['VendorAnalyticsSummary']
export type SeasonalAnalysis = components['schemas']['SeasonalAnalysis']
export type SeasonalAnalyticsSummary = components['schemas']['SeasonalAnalyticsSummary']
export type CategoryChange = components['schemas']['CategoryChange']
export type PeriodComparison = components['schemas']['PeriodComparison']

// Derive union types from generated schema fields
export type FuelAlertSeverity = NonNullable<FuelEfficiencyAlert['severity']>
export type AnomalySeverity = NonNullable<AnomalyAlert['severity']>

// ============================================================================
// Section B: Hand-maintained frontend-only types
// The generated schema types propane_analysis, spot_rental_analysis, and
// def_analysis as { [key: string]: unknown } because the backend returns
// unstructured dicts. These typed interfaces mirror the actual response shape
// and are used via type assertions in consumer code.
// ============================================================================

export interface PropaneAnalysis {
  total_spent: string
  total_liters: string
  avg_price_per_liter: string | null
  record_count: number
  monthly_trend: Array<{
    year: number
    month: number
    month_name: string
    total_cost: number
    total_liters: number
    avg_price_per_liter: number
  }>
}

export interface SpotRentalAnalysis {
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

export interface DEFAnalysis {
  total_spent: string
  total_liters: string
  avg_cost_per_liter: string | null
  liters_per_1000_km: string | null
  record_count: number
}
