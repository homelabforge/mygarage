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
  DTCDefinition,
  DTCSearchResponse,
  DTCClearRequest,
  DTCClearResponse,
  MQTTSettings,
  MQTTSettingsUpdate,
  MQTTStatus,
  MQTTTestResult,
} from '../types/livelink'

export const livelinkService = {
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
   * Get all discovered parameters
   */
  async getParameters(): Promise<LiveLinkParameterListResponse> {
    const response = await api.get<LiveLinkParameterListResponse>('/livelink/parameters')
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

  // ===========================================================================
  // DTC Definitions (lookup database)
  // ===========================================================================

  /**
   * Look up a single DTC code
   */
  async getDTCDefinition(code: string): Promise<DTCDefinition> {
    const response = await api.get<DTCDefinition>(`/livelink/dtc-definitions/${encodeURIComponent(code)}`)
    return response.data
  },

  /**
   * Search DTC definitions
   */
  async searchDTCDefinitions(query: string, limit = 50): Promise<DTCSearchResponse> {
    const response = await api.get<DTCSearchResponse>('/livelink/dtc-definitions', {
      params: { q: query, limit },
    })
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

  /**
   * Check if vehicle has a linked LiveLink device
   */
  async hasLinkedDevice(vin: string): Promise<boolean> {
    try {
      const status = await this.getVehicleStatus(vin)
      return status.device_id !== null
    } catch {
      return false
    }
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
  // Vehicle DTCs
  // ===========================================================================

  /**
   * Get DTCs for a vehicle
   */
  async getVehicleDTCs(vin: string, activeOnly = false): Promise<VehicleDTCListResponse> {
    const response = await api.get<VehicleDTCListResponse>(`/vehicles/${vin}/livelink/dtcs`, {
      params: { active_only: activeOnly },
    })
    return response.data
  },

  /**
   * Get DTC history for a vehicle
   */
  async getVehicleDTCHistory(vin: string): Promise<VehicleDTCListResponse> {
    const response = await api.get<VehicleDTCListResponse>(`/vehicles/${vin}/livelink/dtcs/history`)
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
    return `/api/vehicles/${vin}/livelink/export/telemetry?${params.toString()}`
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
    return `/api/vehicles/${vin}/livelink/export/sessions?${params.toString()}`
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
}

export default livelinkService
