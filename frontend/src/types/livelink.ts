/**
 * LiveLink type definitions for WiCAN OBD2 telemetry integration
 *
 * Section A: Generated aliases from openapi-typescript
 * Section B: Manual types (backend uses str, frontend-only, or no schema)
 */

import type { components } from './api.generated'

// =============================================================================
// Section A — Generated aliases
// =============================================================================

// -- Device Types --
export type LiveLinkDevice = components['schemas']['LiveLinkDeviceResponse']
export type LiveLinkDeviceUpdate = components['schemas']['LiveLinkDeviceUpdate']
export type LiveLinkDeviceListResponse = components['schemas']['LiveLinkDeviceListResponse']

/** Derived from the generated LiveLinkDeviceResponse device_status enum */
export type DeviceStatus = NonNullable<LiveLinkDevice['device_status']>
/** Derived from the generated LiveLinkDeviceResponse ecu_status enum */
export type ECUStatus = NonNullable<LiveLinkDevice['ecu_status']>

// -- Token Types --
export type TokenGenerateResponse = components['schemas']['TokenGenerateResponse']
export type TokenInfoResponse = components['schemas']['TokenInfoResponse']

// -- Parameter Types --
export type LiveLinkParameter = components['schemas']['LiveLinkParameterResponse']
export type LiveLinkParameterUpdate = components['schemas']['LiveLinkParameterUpdate']
export type LiveLinkParameterListResponse = components['schemas']['LiveLinkParameterListResponse']

// -- Settings Types --
export type LiveLinkSettings = components['schemas']['LiveLinkSettingsResponse']
export type LiveLinkSettingsUpdate = components['schemas']['LiveLinkSettingsUpdate']

// -- Firmware Types --
export type FirmwareInfo = components['schemas']['FirmwareInfoResponse']
export type DeviceFirmwareStatus = components['schemas']['DeviceFirmwareStatus']

// -- Live Status Types --
export type TelemetryLatestValue = components['schemas']['TelemetryLatestValue']
export type VehicleLiveLinkStatus = components['schemas']['VehicleLiveLinkStatus']

// -- Historical Telemetry Types --
export type TelemetryDataPoint = components['schemas']['TelemetryDataPoint']
export type TelemetrySeries = components['schemas']['TelemetrySeriesResponse']
export type TelemetryQueryResponse = components['schemas']['TelemetryQueryResponse']

// -- Drive Session Types --
export type DriveSession = components['schemas']['DriveSessionResponse']
export type DriveSessionListResponse = components['schemas']['DriveSessionListResponse']
export type DriveSessionDetail = components['schemas']['DriveSessionDetailResponse']

// -- DTC Types --
export type DTCDefinition = components['schemas']['DTCDefinitionResponse']
export type DTCSearchResponse = components['schemas']['DTCSearchResponse']
export type VehicleDTC = components['schemas']['VehicleDTCResponse']
export type VehicleDTCUpdate = components['schemas']['VehicleDTCUpdate']
export type VehicleDTCListResponse = components['schemas']['VehicleDTCListResponse']
export type DTCClearRequest = components['schemas']['DTCClearRequest']
export type DTCClearResponse = components['schemas']['DTCClearResponse']

// -- MQTT Types --
export type MQTTSettings = components['schemas']['MQTTSettingsResponse']
export type MQTTSettingsUpdate = components['schemas']['MQTTSettingsUpdate']
export type MQTTStatus = components['schemas']['MQTTStatusResponse']
export type MQTTTestResult = components['schemas']['MQTTTestResult']

// -- Device Command Types --
export type DeviceCommandRequest = components['schemas']['DeviceCommandRequest']
export type DeviceCommandResponse = components['schemas']['DeviceCommandResponse']

// =============================================================================
// Section B — Manual types (backend uses str, frontend-only, or no generated schema)
// =============================================================================

// -- DTC enums (backend uses str) --
export type DTCSeverity = 'info' | 'warning' | 'critical'
export type DTCCategory = 'powertrain' | 'body' | 'chassis' | 'network'

// -- MQTT connection status (frontend-only enum) --
export type MQTTConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error' | 'disabled'

// -- Frontend-only query parameter builders --
export interface TelemetryQueryParams {
  start: string
  end: string
  param_keys?: string[]
  interval_seconds?: number
  limit?: number
}

export interface TelemetryExportParams {
  start: string
  end: string
  param_keys?: string[]
  format: 'csv' | 'json'
  include_session_markers?: boolean
  downsample_seconds?: number
}

export interface SessionQueryParams {
  start?: string
  end?: string
  min_duration_seconds?: number
  limit?: number
  offset?: number
}

// -- Daily Summary Types (no generated schema) --
export interface DailySummaryEntry {
  date: string
  min_value: number | null
  max_value: number | null
  avg_value: number | null
  sample_count: number
}

export interface DailySummaryResponse {
  param_key: string
  display_name: string | null
  unit: string | null
  entries: DailySummaryEntry[]
}

// -- Session Telemetry Types (no generated schema) --
export interface SessionTelemetryDataPoint {
  timestamp: string
  param_key: string
  value: number
}

export interface SessionTelemetryResponse {
  session_id: number
  started_at: string
  ended_at: string | null
  data: SessionTelemetryDataPoint[]
  total_points: number
}
