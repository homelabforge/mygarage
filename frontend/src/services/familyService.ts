/**
 * Family Multi-User System API service
 *
 * Provides API calls for:
 * - Vehicle transfers
 * - Vehicle sharing
 * - Family dashboard
 * - Shareable users
 */

import api from './api'
import type {
  EligibleRecipient,
  FamilyDashboardResponse,
  FamilyMemberData,
  FamilyMemberUpdateRequest,
  ShareableUser,
  TransferHistoryResponse,
  VehicleShareCreate,
  VehicleShareResponse,
  VehicleSharesListResponse,
  VehicleShareUpdate,
  VehicleTransferRequest,
  VehicleTransferResponse,
} from '@/types/family'

export const familyService = {
  // ===========================================================================
  // Vehicle Transfer Operations
  // ===========================================================================

  /**
   * Transfer a vehicle to another user (admin only)
   */
  async transferVehicle(vin: string, request: VehicleTransferRequest): Promise<VehicleTransferResponse> {
    const response = await api.post<VehicleTransferResponse>(
      `/family/vehicles/${vin}/transfer`,
      request
    )
    return response.data
  },

  /**
   * Get transfer history for a vehicle
   */
  async getTransferHistory(vin: string): Promise<TransferHistoryResponse> {
    const response = await api.get<TransferHistoryResponse>(
      `/family/vehicles/${vin}/transfer-history`
    )
    return response.data
  },

  /**
   * Get eligible recipients for a vehicle transfer (admin only)
   */
  async getEligibleRecipients(vin: string): Promise<EligibleRecipient[]> {
    const response = await api.get<EligibleRecipient[]>(
      `/family/vehicles/${vin}/eligible-recipients`
    )
    return response.data
  },

  // ===========================================================================
  // Vehicle Sharing Operations
  // ===========================================================================

  /**
   * Share a vehicle with another user
   */
  async shareVehicle(vin: string, request: VehicleShareCreate): Promise<VehicleShareResponse> {
    const response = await api.post<VehicleShareResponse>(
      `/family/vehicles/${vin}/shares`,
      request
    )
    return response.data
  },

  /**
   * Get all shares for a vehicle
   */
  async getVehicleShares(vin: string): Promise<VehicleSharesListResponse> {
    const response = await api.get<VehicleSharesListResponse>(
      `/family/vehicles/${vin}/shares`
    )
    return response.data
  },

  /**
   * Update a share's permission level
   */
  async updateShare(shareId: number, request: VehicleShareUpdate): Promise<VehicleShareResponse> {
    const response = await api.put<VehicleShareResponse>(
      `/family/shares/${shareId}`,
      request
    )
    return response.data
  },

  /**
   * Revoke (delete) a share
   */
  async revokeShare(shareId: number): Promise<void> {
    await api.delete(`/family/shares/${shareId}`)
  },

  /**
   * Get users available for sharing (excludes current user and disabled users)
   */
  async getShareableUsers(): Promise<ShareableUser[]> {
    const response = await api.get<ShareableUser[]>('/auth/users/shareable')
    return response.data
  },

  // ===========================================================================
  // Family Dashboard Operations
  // ===========================================================================

  /**
   * Get the family dashboard (admin only)
   */
  async getFamilyDashboard(): Promise<FamilyDashboardResponse> {
    const response = await api.get<FamilyDashboardResponse>('/family/dashboard')
    return response.data
  },

  /**
   * Get all users for dashboard management (admin only)
   */
  async getDashboardMembers(): Promise<FamilyMemberData[]> {
    const response = await api.get<FamilyMemberData[]>('/family/dashboard/members')
    return response.data
  },

  /**
   * Update a member's dashboard display settings (admin only)
   */
  async updateDashboardMember(
    userId: number,
    request: FamilyMemberUpdateRequest
  ): Promise<FamilyMemberData> {
    const response = await api.put<FamilyMemberData>(
      `/family/dashboard/members/${userId}`,
      request
    )
    return response.data
  },

  // ===========================================================================
  // Relationship Operations
  // ===========================================================================

  /**
   * Get available relationship presets
   */
  async getRelationshipPresets(): Promise<Array<{ value: string; label: string }>> {
    const response = await api.get<Array<{ value: string; label: string }>>(
      '/auth/relationship-presets'
    )
    return response.data
  },
}

export default familyService
