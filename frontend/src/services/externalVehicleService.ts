import api from './api'
import type {
  ExternalVehicle,
  ExternalVehicleInput,
  ExternalVehicleKind,
  ExternalVehicleListResponse,
} from '../types/externalVehicle'

export async function listExternalVehicles(kind?: ExternalVehicleKind): Promise<ExternalVehicleListResponse> {
  const response = await api.get<ExternalVehicleListResponse>('/external-vehicles', {
    params: kind ? { kind } : undefined,
  })
  return response.data
}

export async function createExternalVehicle(payload: ExternalVehicleInput): Promise<ExternalVehicle> {
  const response = await api.post<ExternalVehicle>('/external-vehicles', payload)
  return response.data
}

export async function updateExternalVehicle(
  id: number,
  payload: Partial<ExternalVehicleInput>,
): Promise<ExternalVehicle> {
  const response = await api.put<ExternalVehicle>(`/external-vehicles/${id}`, payload)
  return response.data
}

export async function deleteExternalVehicle(id: number): Promise<void> {
  await api.delete(`/external-vehicles/${id}`)
}
