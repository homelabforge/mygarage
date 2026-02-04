/**
 * LiveLink type definitions for WiCAN OBD2 telemetry integration
 */

// =============================================================================
// Device Types
// =============================================================================

export type DeviceStatus = 'online' | 'offline' | 'unknown'
export type ECUStatus = 'online' | 'offline' | 'unknown'

export interface LiveLinkDevice {
  id: number
  device_id: string
  vin: string | null
  label: string | null
  hw_version: string | null
  fw_version: string | null
  git_version: string | null
  sta_ip: string | null
  rssi: number | null
  battery_voltage: number | null
  ecu_status: ECUStatus
  device_status: DeviceStatus
  has_device_token: boolean
  enabled: boolean
  last_seen: string | null
  created_at: string
  updated_at: string | null
}

export interface LiveLinkDeviceUpdate {
  label?: string | null
  vin?: string | null
  enabled?: boolean
}

export interface LiveLinkDeviceListResponse {
  devices: LiveLinkDevice[]
  total: number
  online_count: number
}

// =============================================================================
// Token Types
// =============================================================================

export interface TokenGenerateResponse {
  token: string
  expires_at: string | null
}

export interface TokenInfoResponse {
  masked_token: string
  created_at: string
  last_used: string | null
}

// =============================================================================
// Parameter Types
// =============================================================================

export interface LiveLinkParameter {
  id: number
  param_key: string
  display_name: string | null
  unit: string | null
  param_class: string | null
  category: string | null
  icon: string | null
  warning_min: number | null
  warning_max: number | null
  display_order: number
  show_on_dashboard: boolean
  archive_only: boolean
  storage_interval_seconds: number
  created_at: string
  updated_at: string | null
}

export interface LiveLinkParameterUpdate {
  display_name?: string | null
  category?: string | null
  icon?: string | null
  warning_min?: number | null
  warning_max?: number | null
  display_order?: number
  show_on_dashboard?: boolean
  archive_only?: boolean
  storage_interval_seconds?: number
}

export interface LiveLinkParameterListResponse {
  parameters: LiveLinkParameter[]
  total: number
}

// =============================================================================
// Settings Types
// =============================================================================

export interface LiveLinkSettings {
  enabled: boolean
  has_global_token: boolean
  ingestion_url: string
  telemetry_retention_days: number
  session_timeout_minutes: number
  device_offline_timeout_minutes: number
  daily_aggregation_enabled: boolean
  firmware_check_enabled: boolean
  alert_cooldown_minutes: number
  // Notification toggles
  notify_device_offline: boolean
  notify_threshold_alerts: boolean
  notify_firmware_update: boolean
  notify_new_device: boolean
}

export interface LiveLinkSettingsUpdate {
  enabled?: boolean
  telemetry_retention_days?: number
  session_timeout_minutes?: number
  device_offline_timeout_minutes?: number
  daily_aggregation_enabled?: boolean
  firmware_check_enabled?: boolean
  alert_cooldown_minutes?: number
  notify_device_offline?: boolean
  notify_threshold_alerts?: boolean
  notify_firmware_update?: boolean
  notify_new_device?: boolean
}

// =============================================================================
// Firmware Types
// =============================================================================

export interface FirmwareInfo {
  latest_version: string | null
  latest_tag: string | null
  release_url: string | null
  release_notes: string | null
  checked_at: string | null
}

export interface DeviceFirmwareStatus {
  device_id: string
  current_version: string | null
  latest_version: string | null
  update_available: boolean
  release_url: string | null
}

// =============================================================================
// Live Status Types (for dashboard polling)
// =============================================================================

export interface TelemetryLatestValue {
  param_key: string
  value: number
  unit: string | null
  display_name: string | null
  timestamp: string
  warning_min: number | null
  warning_max: number | null
  in_warning: boolean
}

export interface VehicleLiveLinkStatus {
  vin: string
  device_id: string | null
  device_status: DeviceStatus
  ecu_status: ECUStatus
  last_seen: string | null
  battery_voltage: number | null
  rssi: number | null
  // Current session info
  current_session_id: number | null
  session_started_at: string | null
  session_duration_seconds: number | null
  // Latest parameter values
  latest_values: TelemetryLatestValue[]
}

// =============================================================================
// Historical Telemetry Types
// =============================================================================

export interface TelemetryDataPoint {
  timestamp: string
  value: number
}

export interface TelemetrySeries {
  param_key: string
  display_name: string | null
  unit: string | null
  data: TelemetryDataPoint[]
  min_value: number | null
  max_value: number | null
  avg_value: number | null
}

export interface TelemetryQueryParams {
  start: string
  end: string
  param_keys?: string[]
  interval_seconds?: number
  limit?: number
}

export interface TelemetryQueryResponse {
  vin: string
  start: string
  end: string
  series: TelemetrySeries[]
  total_points: number
}

// =============================================================================
// Daily Summary Types
// =============================================================================

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

// =============================================================================
// Export Types
// =============================================================================

export interface TelemetryExportParams {
  start: string
  end: string
  param_keys?: string[]
  format: 'csv' | 'json'
  include_session_markers?: boolean
  downsample_seconds?: number
}

// =============================================================================
// Drive Session Types
// =============================================================================

export interface DriveSession {
  id: number
  vin: string
  device_id: string
  started_at: string
  ended_at: string | null
  duration_seconds: number | null
  // Odometer data
  start_odometer: number | null
  end_odometer: number | null
  distance_km: number | null
  // Speed aggregates
  avg_speed: number | null
  max_speed: number | null
  // RPM aggregates
  avg_rpm: number | null
  max_rpm: number | null
  // Temperature aggregates
  avg_coolant_temp: number | null
  max_coolant_temp: number | null
  // Throttle aggregates
  avg_throttle: number | null
  max_throttle: number | null
  // Fuel metrics
  avg_fuel_level: number | null
  fuel_used_estimate: number | null
  // Metadata
  created_at: string
}

export interface DriveSessionListResponse {
  sessions: DriveSession[]
  total: number
}

export interface DriveSessionDetail extends DriveSession {
  parameters_recorded: string[]
  data_points_count: number
  dtcs_appeared: string[]
  dtcs_cleared: string[]
}

export interface SessionQueryParams {
  start?: string
  end?: string
  min_duration_seconds?: number
  limit?: number
  offset?: number
}

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

// =============================================================================
// DTC (Diagnostic Trouble Code) Types
// =============================================================================

export type DTCSeverity = 'info' | 'warning' | 'critical'
export type DTCCategory = 'powertrain' | 'body' | 'chassis' | 'network'

export interface DTCDefinition {
  code: string
  description: string
  category: DTCCategory
  subcategory: string | null
  severity: DTCSeverity
  estimated_severity_level: number
  is_emissions_related: boolean
  common_causes: string[] | null
  symptoms: string[] | null
  fix_guidance: string | null
}

export interface DTCSearchResponse {
  results: DTCDefinition[]
  total: number
  query: string
}

export interface VehicleDTC {
  id: number
  vin: string
  device_id: string
  code: string
  description: string | null
  severity: DTCSeverity
  user_notes: string | null
  first_seen: string
  last_seen: string
  cleared_at: string | null
  is_active: boolean
  created_at: string
  // Enrichment from lookup
  category: DTCCategory | null
  subcategory: string | null
  is_emissions_related: boolean | null
  estimated_severity_level: number | null
}

export interface VehicleDTCUpdate {
  description?: string | null
  severity?: DTCSeverity
  user_notes?: string | null
}

export interface VehicleDTCListResponse {
  dtcs: VehicleDTC[]
  total: number
  active_count: number
  critical_count: number
}

export interface DTCClearRequest {
  notes?: string | null
}

export interface DTCClearResponse {
  success: boolean
  dtc_id: number
  code: string
  cleared_at: string
}

// =============================================================================
// MQTT Settings Types
// =============================================================================

export interface MQTTSettings {
  enabled: boolean
  broker_host: string
  broker_port: number
  username: string
  has_password: boolean
  topic_prefix: string
  use_tls: boolean
}

export interface MQTTSettingsUpdate {
  enabled?: boolean
  broker_host?: string
  broker_port?: number
  username?: string
  password?: string
  topic_prefix?: string
  use_tls?: boolean
}

export type MQTTConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error' | 'disabled'

export interface MQTTStatus {
  running: boolean
  connection_status: MQTTConnectionStatus
  last_message_at: string | null
  messages_processed: number
}

export interface MQTTTestResult {
  success: boolean
  message: string
  broker: string | null
}
