/**
 * Reminder API service
 */

import api from './api'
import type { Reminder, ReminderCreate, ReminderUpdate } from '../types/reminder'

export const reminderService = {
  async list(vin: string, status?: string): Promise<Reminder[]> {
    const params = status ? { status } : undefined
    const { data } = await api.get<Reminder[]>(`/vehicles/${vin}/reminders`, { params })
    return data
  },

  async create(vin: string, payload: ReminderCreate): Promise<Reminder> {
    const { data } = await api.post<Reminder>(`/vehicles/${vin}/reminders`, payload)
    return data
  },

  async update(vin: string, id: number, payload: ReminderUpdate): Promise<Reminder> {
    const { data } = await api.put<Reminder>(`/vehicles/${vin}/reminders/${id}`, payload)
    return data
  },

  async remove(vin: string, id: number): Promise<void> {
    await api.delete(`/vehicles/${vin}/reminders/${id}`)
  },

  async markDone(vin: string, id: number): Promise<Reminder> {
    const { data } = await api.post<Reminder>(`/vehicles/${vin}/reminders/${id}/done`)
    return data
  },

  async dismiss(vin: string, id: number): Promise<Reminder> {
    const { data } = await api.post<Reminder>(`/vehicles/${vin}/reminders/${id}/dismiss`)
    return data
  },
}
