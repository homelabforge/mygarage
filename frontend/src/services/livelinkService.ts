/**
 * LiveLink API service for WiCAN OBD2 telemetry integration
 */

import api from './api'
import type {
  LiveLinkDevice,
  LiveLinkDeviceUpdate,
  LiveLinkDeviceListResponse,
  TokenGenerateResponse,
  LiveLinkParameter,
  LiveLinkParameterUpdate,
  LiveLinkParameterListResponse,
  LiveLinkSettings,
  LiveLinkSettingsUpdate,
  FirmwareInfo,
  DeviceFirmwareStatus,
  VehicleLiveLinkStatus,
  TelemetryQueryResponse,
  DriveSessionListResponse,
  DriveSessionDetail,
  SessionQueryParams,
  SessionTelemetryResponse,
  VehicleDTC,
  VehicleDTCUpdate,
  VehicleDTCListResponse,
  DTCClearRequest,
  DTCClearResponse,
  MQTTSettings,
  MQTTSettingsUpdate,
  MQTTStatus,
  MQTTTestResult,
  DeviceCommandResponse,
  SdConfigUpdate,
  BackfillResultResponse,
  TorqueSourceCreateResponse,
  TorqueSourceListResponse,
  IntegrationListResponse,
  DeviceReadingsResponse,
} from '../types/livelink'
import type { TripList, LocationTrackingResponse, TripPointsResponse, LastLocation } from '../types/trips'
import { withBase } from '../utils/basePath'
import type {
  DiscoveredTopic,
  PresetApplyRequest,
  PresetInfo,
  SourceInfo,
  TopicMap,
  TopicMapCreate,
} from '@/types/livelinkTopicMap'

export type DTCListFilter = 'active' | 'cleared' | 'all'

export const livelinkService = {

  // ===========================================================================
  // Source modules, topic maps, discovery and presets
  // ===========================================================================

  /** Distinct parameter keys THIS device has reported. */
  async getDeviceParamKeys(deviceId: string): Promise<string[]> {
    const response = await api.get<string[]>(`/livelink/devices/${deviceId}/param-keys`)
    return response.data
  },

  /** Registered source kinds and what each produces. */
  async listSources(): Promise<SourceInfo[]> {
    const response = await api.get<SourceInfo[]>('/livelink/sources')
    return response.data
  },

  /**
   * The integrations card's tab strip, with each tab's derived status.
   *
   * One request replaces the four the card used to make. The status rules live
   * in the backend so they are unit-tested rather than spread across JSX.
   */
  async getIntegrations(): Promise<IntegrationListResponse> {
    const response = await api.get<IntegrationListResponse>('/livelink/integrations')
    return response.data
  },

  /**
   * One device's mapped parameters and their current values.
   *
   * Device-attributed: values come from `vehicle_telemetry`, not from the
   * VIN-scoped latest cache, so a vehicle carrying two sources cannot show one
   * device's reading under the other's name.
   *
   * Encoded because a hand-created device id is free text: `rv/gw` would
   * otherwise route to a different path entirely.
   */
  async getDeviceReadings(deviceId: string): Promise<DeviceReadingsResponse> {
    const response = await api.get<DeviceReadingsResponse>(
      `/livelink/devices/${encodeURIComponent(deviceId)}/readings`,
    )
    return response.data
  },

  /** Create a device by hand (generic MQTT has no auto-discovery). */
  async createDevice(body: {
    device_id: string
    kind: string
    label?: string | null
    vin?: string | null
  }): Promise<LiveLinkDevice> {
    const response = await api.post<LiveLinkDevice>('/livelink/devices', body)
    return response.data
  },

  /** Topic maps, optionally for one device. */
  async listTopicMaps(deviceId?: string): Promise<TopicMap[]> {
    const response = await api.get<TopicMap[]>('/livelink/topic-maps', {
      params: deviceId ? { device_id: deviceId } : undefined,
    })
    return response.data
  },

  /** Add a mapping. The backend resubscribes. */
  async createTopicMap(body: TopicMapCreate): Promise<TopicMap> {
    const response = await api.post<TopicMap>('/livelink/topic-maps', body)
    return response.data
  },

  /** Change a mapping. The backend resubscribes. */
  async updateTopicMap(id: number, body: Partial<TopicMapCreate>): Promise<TopicMap> {
    const response = await api.patch<TopicMap>(`/livelink/topic-maps/${id}`, body)
    return response.data
  },

  /** Remove a mapping. The backend resubscribes. */
  async deleteTopicMap(id: number): Promise<void> {
    await api.delete(`/livelink/topic-maps/${id}`)
  },

  /** Listen briefly and report what the broker is publishing. */
  async discoverTopics(prefix: string, seconds = 15): Promise<DiscoveredTopic[]> {
    const response = await api.post<DiscoveredTopic[]>('/livelink/topic-discovery', {
      prefix,
      seconds,
    })
    return response.data
  },

  /** Named device templates. */
  async listPresets(): Promise<PresetInfo[]> {
    const response = await api.get<PresetInfo[]>('/livelink/presets')
    return response.data
  },

  /** Add one sensor from a preset: its own device, and a topic map per
   *  reading given. The server picks the device id. */
  async applyPreset(name: string, body: PresetApplyRequest): Promise<LiveLinkDevice> {
    const response = await api.post<LiveLinkDevice>(`/livelink/presets/${name}/apply`, body)
    return response.data
  },
  // ===========================================================================
  // Settings
  // ===========================================================================

  /**
   * Get LiveLink settings
   */
  async getSettings(): Promise<LiveLinkSettings> {
    const response = await api.get<LiveLinkSettings>('/livelink/settings')
    return response.data
  },

  /**
   * Update LiveLink settings
   */
  async updateSettings(settings: LiveLinkSettingsUpdate): Promise<LiveLinkSettings> {
    const response = await api.put<LiveLinkSettings>('/livelink/settings', settings)
    return response.data
  },

  /**
   * Regenerate global API token (returns new token once)
   */
  async regenerateGlobalToken(): Promise<TokenGenerateResponse> {
    const response = await api.post<TokenGenerateResponse>('/livelink/token')
    return response.data
  },

  // ===========================================================================
  // Devices
  // ===========================================================================

  /**
   * Get all discovered devices
   */
  async getDevices(): Promise<LiveLinkDeviceListResponse> {
    const response = await api.get<LiveLinkDeviceListResponse>('/livelink/devices')
    return response.data
  },

  /**
   * Get a single device by device_id
   */
  async getDevice(deviceId: string): Promise<LiveLinkDevice> {
    const response = await api.get<LiveLinkDevice>(`/livelink/devices/${deviceId}`)
    return response.data
  },

  /**
   * Update a device (link to vehicle, rename, enable/disable)
   */
  async updateDevice(deviceId: string, update: LiveLinkDeviceUpdate): Promise<LiveLinkDevice> {
    const response = await api.put<LiveLinkDevice>(`/livelink/devices/${deviceId}`, update)
    return response.data
  },

  /**
   * Delete a device (retains telemetry data)
   */
  async deleteDevice(deviceId: string): Promise<void> {
    await api.delete(`/livelink/devices/${deviceId}`)
  },

  /**
   * Generate per-device token (returns new token once)
   */
  async generateDeviceToken(deviceId: string): Promise<TokenGenerateResponse> {
    const response = await api.post<TokenGenerateResponse>(`/livelink/devices/${deviceId}/token`)
    return response.data
  },

  /**
   * Revoke per-device token (falls back to global token)
   */
  async revokeDeviceToken(deviceId: string): Promise<void> {
    await api.delete(`/livelink/devices/${deviceId}/token`)
  },

  // ===========================================================================
  // Parameters
  // ===========================================================================

  /**
   * Get all discovered parameters, fleet-wide. Admin surfaces only.
   */
  async getParameters(): Promise<LiveLinkParameterListResponse> {
    const response = await api.get<LiveLinkParameterListResponse>('/livelink/parameters')
    return response.data
  },

  /**
   * Get the parameters one vehicle actually reports.
   *
   * Anything vehicle-facing wants this, not `getParameters`: the global
   * catalog holds every parameter any device has ever sent, so charting from
   * it offers a propane trailer a list of engine PIDs that can only draw an
   * empty graph.
   */
  async getVehicleParameters(vin: string): Promise<LiveLinkParameterListResponse> {
    const response = await api.get<LiveLinkParameterListResponse>(
      `/vehicles/${vin}/livelink/parameters`,
    )
    return response.data
  },

  /**
   * Update parameter settings
   */
  async updateParameter(paramKey: string, update: LiveLinkParameterUpdate): Promise<LiveLinkParameter> {
    const response = await api.put<LiveLinkParameter>(`/livelink/parameters/${encodeURIComponent(paramKey)}`, update)
    return response.data
  },

  // ===========================================================================
  // Firmware
  // ===========================================================================

  /**
   * Get cached firmware info
   */
  async getFirmwareLatest(): Promise<FirmwareInfo> {
    const response = await api.get<FirmwareInfo>('/livelink/firmware/latest')
    return response.data
  },

  /**
   * Check for firmware updates (triggers GitHub API call)
   */
  async checkFirmwareUpdates(): Promise<FirmwareInfo> {
    const response = await api.post<FirmwareInfo>('/livelink/firmware/check')
    return response.data
  },

  /**
   * Get per-device firmware status
   */
  async getDeviceFirmwareStatus(): Promise<DeviceFirmwareStatus[]> {
    const response = await api.get<DeviceFirmwareStatus[]>('/livelink/firmware/devices')
    return response.data
  },

  /**
   * Skip firmware-update notifications for one release on one device.
   * The version is the one the client saw, so a release landing between
   * render and click is never silently skipped.
   */
  async skipFirmwareVersion(deviceId: string, version: string): Promise<DeviceFirmwareStatus> {
    const response = await api.post<DeviceFirmwareStatus>(
      `/livelink/devices/${deviceId}/firmware/skip`,
      { version },
    )
    return response.data
  },

  /**
   * Clear a device's skipped firmware version.
   */
  async unskipFirmwareVersion(deviceId: string): Promise<DeviceFirmwareStatus> {
    const response = await api.delete<DeviceFirmwareStatus>(
      `/livelink/devices/${deviceId}/firmware/skip`,
    )
    return response.data
  },

  // ===========================================================================
  // Vehicle LiveLink Status (live dashboard)
  // ===========================================================================

  /**
   * Get current LiveLink status for a vehicle (for live dashboard polling)
   */
  async getVehicleStatus(vin: string): Promise<VehicleLiveLinkStatus> {
    const response = await api.get<VehicleLiveLinkStatus>(`/vehicles/${vin}/livelink/status`)
    return response.data
  },


  // ===========================================================================
  // Vehicle Telemetry (historical)
  // ===========================================================================

  /**
   * Query historical telemetry for a vehicle
   */
  async getTelemetry(
    vin: string,
    start: string,
    end: string,
    paramKeys?: string[],
    intervalSeconds?: number,
    limit = 10000
  ): Promise<TelemetryQueryResponse> {
    const params: Record<string, unknown> = { start, end, limit }
    if (paramKeys && paramKeys.length > 0) {
      params.param_keys = paramKeys.join(',')
    }
    if (intervalSeconds) {
      params.interval_seconds = intervalSeconds
    }
    const response = await api.get<TelemetryQueryResponse>(`/vehicles/${vin}/livelink/telemetry`, { params })
    return response.data
  },

  // ===========================================================================
  // Drive Sessions
  // ===========================================================================

  /**
   * Get drive sessions for a vehicle
   */
  async getSessions(vin: string, params?: SessionQueryParams): Promise<DriveSessionListResponse> {
    const response = await api.get<DriveSessionListResponse>(`/vehicles/${vin}/livelink/sessions`, {
      params: params || {},
    })
    return response.data
  },

  /**
   * Get a single drive session with details
   */
  async getSession(vin: string, sessionId: number): Promise<DriveSessionDetail> {
    const response = await api.get<DriveSessionDetail>(`/vehicles/${vin}/livelink/sessions/${sessionId}`)
    return response.data
  },

  /**
   * Get telemetry data for a specific session
   */
  async getSessionTelemetry(
    vin: string,
    sessionId: number,
    paramKeys?: string[],
    downsampleSeconds?: number
  ): Promise<SessionTelemetryResponse> {
    const params: Record<string, unknown> = {}
    if (paramKeys && paramKeys.length > 0) {
      params.param_keys = paramKeys.join(',')
    }
    if (downsampleSeconds) {
      params.downsample_seconds = downsampleSeconds
    }
    const response = await api.get<SessionTelemetryResponse>(
      `/vehicles/${vin}/livelink/sessions/${sessionId}/telemetry`,
      { params }
    )
    return response.data
  },

  // ===========================================================================
  // Trips (GPS-tracked drive sessions, Task 14)
  // ===========================================================================

  /**
   * Get GPS-tracked trips for a vehicle (drive sessions with >=1 location point)
   */
  async getTrips(vin: string, params?: { limit?: number }): Promise<TripList> {
    const response = await api.get<TripList>(`/vehicles/${vin}/livelink/trips`, {
      params: params || {},
    })
    return response.data
  },

  /**
   * Set the vehicle's GPS location-tracking opt-out flag (R1-H4)
   */
  async setLocationTracking(vin: string, enabled: boolean): Promise<LocationTrackingResponse> {
    const response = await api.patch<LocationTrackingResponse>(`/vehicles/${vin}/livelink/location-tracking`, {
      enabled,
    })
    return response.data
  },

  /**
   * Get a trip's GPS points as an ordered polyline (for map rendering, Task 15)
   */
  async getTripPoints(vin: string, sessionId: number): Promise<TripPointsResponse> {
    const response = await api.get<TripPointsResponse>(`/vehicles/${vin}/livelink/trips/${sessionId}/points`)
    return response.data
  },

  /**
   * Get the vehicle's most recent GPS location point, if any (Overview
   * "Last seen here" card, Task 16). Returns null if no location has ever
   * been recorded.
   */
  async getLastLocation(vin: string): Promise<LastLocation | null> {
    const response = await api.get<LastLocation | null>(`/vehicles/${vin}/livelink/location/last`)
    return response.data
  },

  // ===========================================================================
  // Vehicle DTCs
  // ===========================================================================

  /**
   * Get DTCs for a vehicle
   */
  async getVehicleDTCs(vin: string, filter: DTCListFilter): Promise<VehicleDTCListResponse> {
    // The route returns active codes unless asked; cleared_only filters before
    // the limit, so recent active rows can't crowd the cleared ones out.
    const params =
      filter === 'all' ? { include_cleared: true }
      : filter === 'cleared' ? { include_cleared: true, cleared_only: true }
      : {}
    const response = await api.get<VehicleDTCListResponse>(`/vehicles/${vin}/livelink/dtcs`, { params })
    return response.data
  },

  /**
   * Update a vehicle DTC (notes, custom description)
   */
  async updateVehicleDTC(vin: string, dtcId: number, update: VehicleDTCUpdate): Promise<VehicleDTC> {
    const response = await api.put<VehicleDTC>(`/vehicles/${vin}/livelink/dtcs/${dtcId}`, update)
    return response.data
  },

  /**
   * Clear (mark as resolved) a vehicle DTC
   */
  async clearVehicleDTC(vin: string, dtcId: number, request?: DTCClearRequest): Promise<DTCClearResponse> {
    const response = await api.post<DTCClearResponse>(`/vehicles/${vin}/livelink/dtcs/${dtcId}/clear`, request || {})
    return response.data
  },

  // ===========================================================================
  // Export
  // ===========================================================================

  /**
   * Get telemetry export URL
   */
  getTelemetryExportUrl(
    vin: string,
    start: string,
    end: string,
    format: 'csv' | 'json' = 'csv',
    paramKeys?: string[],
    downsampleSeconds?: number
  ): string {
    const params = new URLSearchParams({
      start,
      end,
      format,
    })
    if (paramKeys && paramKeys.length > 0) {
      params.set('params', paramKeys.join(','))
    }
    if (downsampleSeconds) {
      params.set('downsample_seconds', downsampleSeconds.toString())
    }
    return withBase(`/api/vehicles/${vin}/livelink/export/telemetry?${params.toString()}`)
  },

  /**
   * Get sessions export URL
   */
  getSessionsExportUrl(vin: string, start: string, end: string, format: 'csv' | 'json' = 'csv'): string {
    const params = new URLSearchParams({
      start,
      end,
      format,
    })
    return withBase(`/api/vehicles/${vin}/livelink/export/sessions?${params.toString()}`)
  },

  // ===========================================================================
  // MQTT Settings
  // ===========================================================================

  /**
   * Get MQTT subscriber settings
   */
  async getMQTTSettings(): Promise<MQTTSettings> {
    const response = await api.get<MQTTSettings>('/livelink/mqtt/settings')
    return response.data
  },

  /**
   * Update MQTT subscriber settings
   */
  async updateMQTTSettings(settings: MQTTSettingsUpdate): Promise<MQTTSettings> {
    const response = await api.put<MQTTSettings>('/livelink/mqtt/settings', settings)
    return response.data
  },

  /**
   * Get MQTT subscriber status
   */
  async getMQTTStatus(): Promise<MQTTStatus> {
    const response = await api.get<MQTTStatus>('/livelink/mqtt/status')
    return response.data
  },

  /**
   * Restart MQTT subscriber (apply config changes)
   */
  async restartMQTTSubscriber(): Promise<MQTTStatus> {
    const response = await api.post<MQTTStatus>('/livelink/mqtt/restart')
    return response.data
  },

  /**
   * Test MQTT broker connection
   */
  async testMQTTConnection(): Promise<MQTTTestResult> {
    const response = await api.post<MQTTTestResult>('/livelink/mqtt/test')
    return response.data
  },

  // ===========================================================================
  // Device Commands
  // ===========================================================================

  /**
   * Send a command to a WiCAN device via MQTT
   */
  async sendDeviceCommand(deviceId: string, command: string): Promise<DeviceCommandResponse> {
    const response = await api.post<DeviceCommandResponse>(
      `/livelink/devices/${deviceId}/command`,
      { command }
    )
    return response.data
  },

  // ===========================================================================
  // SD-Card Backfill
  // ===========================================================================

  /**
   * Update SD-card pull config for a device (admin only)
   */
  async setSdConfig(deviceId: string, config: SdConfigUpdate): Promise<void> {
    await api.put(`/livelink/devices/${deviceId}/sd-config`, config)
  },

  /**
   * Trigger a manual SD-card backfill for a device (admin only)
   */
  async triggerSdBackfill(deviceId: string): Promise<BackfillResultResponse> {
    const response = await api.post<BackfillResultResponse>(`/livelink/devices/${deviceId}/backfill`)
    return response.data
  },

  // ===========================================================================
  // Torque Sources (owner-scoped, per-vehicle)
  // ===========================================================================

  /**
   * List this vehicle's registered Torque Pro sources (no token)
   */
  async getTorqueSources(vin: string): Promise<TorqueSourceListResponse> {
    const response = await api.get<TorqueSourceListResponse>(`/vehicles/${vin}/livelink/torque-sources`)
    return response.data
  },

  /**
   * Register a new Torque Pro source for a vehicle.
   * Returns the upload URL + one-time device token (shown once).
   */
  async createTorqueSource(vin: string, label?: string): Promise<TorqueSourceCreateResponse> {
    const response = await api.post<TorqueSourceCreateResponse>(`/vehicles/${vin}/livelink/torque-sources`, {
      label: label || null,
    })
    return response.data
  },

  /**
   * Revoke (delete) a Torque Pro source
   */
  async deleteTorqueSource(vin: string, deviceId: string): Promise<void> {
    await api.delete(`/vehicles/${vin}/livelink/torque-sources/${deviceId}`)
  },
}

export default livelinkService
